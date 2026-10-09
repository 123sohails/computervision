"""End-to-end CV pipeline: frames -> detection -> tracking -> zone analytics -> outputs.

Independent of the web layer so it can be run from scripts and tests.
"""
from __future__ import annotations

import csv
import time
from pathlib import Path
from typing import Callable

import cv2
import numpy as np
import supervision as sv

from backend.services.annotator import annotate
from backend.services.congestion import STATUS_ORDER, CongestionEngine
from backend.services.detector import Detector
from backend.services.dwell_time import DwellTracker
from backend.services.heatmap import HeatmapAccumulator
from backend.services.line_counter import LineCounter
from backend.services.occupancy import OccupancyAnalytics, utilisation_pct
from backend.services.queue_analytics import QueueAnalytics
from backend.services.tracker import PersonTracker
from backend.services.video_reader import iter_frames, probe_video
from backend.services.video_writer import VideoSink
from backend.services.zone_manager import (ENTRY_LINE, EXIT_LINE, OCCUPANCY_ZONE, QUEUE_ZONE, Zone,
                                           ZoneManager, bottom_center)

ProgressCallback = Callable[[float, dict], None]

ARTIFACTS = {
    "annotated_video": "annotated.mp4",
    "detections_csv": "detections.csv",
    "heatmap": "heatmap.png",
    "trails": "trails.png",
    "thumbnail": "thumbnail.jpg",
}


def _merge_params(params: dict | None) -> dict:
    from backend.config import DEFAULT_PIPELINE_PARAMS

    merged = dict(DEFAULT_PIPELINE_PARAMS)
    merged.update({k: v for k, v in (params or {}).items() if v is not None})
    return merged


def _merge_rules(rules: dict | None) -> dict:
    from backend.config import DEFAULT_RULES

    merged = dict(DEFAULT_RULES)
    merged.update({k: v for k, v in (rules or {}).items() if v is not None})
    return merged


def run_pipeline(video_path: str, zones: list[dict], rules: dict | None, params: dict | None,
                 out_dir: str | Path, detector: Detector,
                 progress_cb: ProgressCallback | None = None) -> dict:
    t_start = time.perf_counter()
    params, rules = _merge_params(params), _merge_rules(rules)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    meta = probe_video(video_path)
    W, H, fps = meta.width, meta.height, meta.fps
    stride = max(1, int(params["frame_stride"]))
    eff_fps = fps / stride
    conf_thr = float(params["conf_threshold"])
    low_conf = min(float(params["tracker_low_conf"]), conf_thr)
    imgsz = int(params["imgsz"])
    expected = (meta.frame_count + stride - 1) // stride if meta.frame_count else 0

    zone_objs = [Zone.from_dict(z) for z in zones]
    zm = ZoneManager(zone_objs, W, H)
    queue_zones = zm.of_type(QUEUE_ZONE)
    occ_zones = zm.of_type(OCCUPANCY_ZONE)
    line_zones = zm.of_type(ENTRY_LINE, EXIT_LINE)
    smoothing = float(rules["smoothing_seconds"])

    tracker = PersonTracker(eff_fps, activation_conf=conf_thr,
                            buffer_seconds=float(params["track_buffer_seconds"]),
                            min_track_frames=int(params["min_track_frames"]))
    queues = {z.id: QueueAnalytics(smoothing, float(z.settings.get("trend_window_seconds",
                                                                    rules["trend_window_seconds"])))
              for z in queue_zones}
    occs = {z.id: OccupancyAnalytics(z.capacity, smoothing) for z in occ_zones}
    dwells = {z.id: DwellTracker(z.id, float(rules["dwell_absence_seconds"]))
              for z in queue_zones + occ_zones}
    diag = float(np.hypot(W, H))
    lines = {z.id: LineCounter(*zm.abs[z.id], zone_type=z.zone_type, margin_px=0.01 * diag,
                               cooldown_s=float(z.settings.get("line_cooldown_seconds",
                                                               rules["line_cooldown_seconds"])),
                               bidirectional=bool(z.settings.get("bidirectional", True)))
             for z in line_zones}
    engine = CongestionEngine(zone_objs, rules)
    heat = HeatmapAccumulator(W, H)

    out_scale = min(1.0, float(params["max_output_width"]) / W)
    out_w, out_h = int(W * out_scale), int(H * out_scale)
    sink = VideoSink(str(out_dir / ARTIFACTS["annotated_video"]), out_w, out_h, eff_fps)

    det_file = open(out_dir / ARTIFACTS["detections_csv"], "w", newline="")
    det_csv = csv.writer(det_file)
    det_csv.writerow(["frame_index", "timestamp", "kind", "track_id", "x1", "y1", "x2", "y2",
                      "confidence", "zones"])

    metrics: list[dict] = []
    all_track_ids: set[int] = set()
    line_events: list[dict] = []
    time_in_status = {"elevated": 0.0, "congested": 0.0}
    time_above: dict[str, float] = {z.id: 0.0 for z in queue_zones + occ_zones}
    detect_time = 0.0
    background = None
    prev_t = None
    t = 0.0
    n = 0

    try:
        for frame_index, t, frame in iter_frames(video_path, stride=stride, fps=fps):
            if n == 0:
                cv2.imwrite(str(out_dir / ARTIFACTS["thumbnail"]), frame)
            if expected and n == expected // 2:
                background = frame.copy()
            dt = 0.0 if prev_t is None else max(0.0, t - prev_t)
            prev_t = t

            t0 = time.perf_counter()
            raw = detector.detect(frame, conf=low_conf, imgsz=imgsz)
            detect_time += time.perf_counter() - t0
            if len(raw):
                raw = raw[~zm.excluded(bottom_center(raw.xyxy))]
            confident = raw[raw.confidence >= conf_thr] if len(raw) else raw
            tracked = tracker.update(raw) if len(raw) else tracker.update(sv.Detections.empty())

            ids = tracked.tracker_id.astype(int) if len(tracked) else np.zeros(0, dtype=int)
            boxes = tracked.xyxy if len(tracked) else np.zeros((0, 4))
            confs = tracked.confidence if len(tracked) and tracked.confidence is not None \
                else np.ones(len(ids))
            pts = bottom_center(boxes)
            all_track_ids.update(ids.tolist())
            member = zm.membership(pts)

            zone_out: dict[str, dict] = {}
            engine_in: dict[str, dict] = {}
            for z in queue_zones:
                inside = ids[member[z.id]]
                q = queues[z.id].update(t, inside)
                dwells[z.id].update(t, inside)
                cur = dwells[z.id].current_dwell(t)
                q["avg_dwell_s"] = round(float(np.mean(cur)), 1) if cur else None
                zone_out[z.id] = q
                engine_in[z.id] = {"avg": q["rolling_avg"], "rise": queues[z.id].series.rise_within(
                    float(z.settings.get("growth_window_seconds", rules["growth_window_seconds"])))}
            for z in occ_zones:
                inside = ids[member[z.id]]
                o = occs[z.id].update(t, inside)
                dwells[z.id].update(t, inside)
                cur = dwells[z.id].current_dwell(t)
                o["avg_dwell_s"] = round(float(np.mean(cur)), 1) if cur else None
                zone_out[z.id] = o
                engine_in[z.id] = {"utilisation": o["rolling_utilisation_pct"]}
            for z in line_zones:
                for ev in lines[z.id].update(t, ids, pts):
                    ev["zone_id"] = z.id
                    line_events.append(ev)
                zone_out[z.id] = {"entries": lines[z.id].entries, "exits": lines[z.id].exits}

            status = engine.update(t, engine_in)
            if status in time_in_status:
                time_in_status[status] += dt
            for zid, zs in engine.zone_status.items():
                if zs != "normal":
                    time_above[zid] += dt

            heat.add(pts, ids)

            active = int(len(ids))
            queue_count = sum(zone_out[z.id]["count"] for z in queue_zones) if queue_zones else None
            if occ_zones:
                occ_count = sum(zone_out[z.id]["count"] for z in occ_zones)
                caps = [z.capacity for z in occ_zones]
                occ_pct = utilisation_pct(occ_count, sum(caps)) if all(caps) else None
            else:
                occ_count, occ_pct = active, None
            entries = sum(ln.entries for ln in lines.values()) if lines else None
            exits = sum(ln.exits for ln in lines.values()) if lines else None
            row = {
                "frame_index": frame_index, "timestamp": round(t, 3), "active_people": active,
                "queue_count": queue_count, "occupancy_count": occ_count, "occupancy_pct": occ_pct,
                "entries": entries, "exits": exits, "congestion_status": status, "zones": zone_out,
            }
            metrics.append(row)

            for b, c in zip(confident.xyxy if len(confident) else [], confident.confidence
                            if len(confident) else []):
                det_csv.writerow([frame_index, f"{t:.3f}", "detection", "", *np.round(b, 1), f"{c:.3f}", ""])
            for tid, b, c, p_idx in zip(ids, boxes, confs, range(len(ids))):
                in_z = "|".join(zid for zid, m in member.items() if m[p_idx])
                det_csv.writerow([frame_index, f"{t:.3f}", "track", int(tid), *np.round(b, 1),
                                  f"{float(c):.3f}", in_z])

            line_counts = {zid: {"entries": ln.entries, "exits": ln.exits} for zid, ln in lines.items()}
            sink.write(annotate(frame, out_scale, zm, boxes, confs, ids, zone_out, line_counts, row))

            n += 1
            if progress_cb and (n % 10 == 0):
                progress_cb(min(0.99, n / expected) if expected else 0.0, {"frames": n, "timestamp": t})
    finally:
        det_file.close()
        sink.close()

    if n == 0:
        raise RuntimeError("No frames could be decoded from the video.")

    events = [e.to_dict() for e in engine.finalize(t)]
    dwell_records = {zid: d.finalize(t) for zid, d in dwells.items()}

    if background is None:
        background = cv2.imread(str(out_dir / ARTIFACTS["thumbnail"]))
    cv2.imwrite(str(out_dir / ARTIFACTS["heatmap"]), heat.render_heatmap(background))
    cv2.imwrite(str(out_dir / ARTIFACTS["trails"]), heat.render_trails(background))

    wall = time.perf_counter() - t_start
    stats = {
        "frames_processed": n,
        "wall_time_s": round(wall, 2),
        "processing_fps": round(n / wall, 2) if wall else None,
        "detector_ms_per_frame": round(1000 * detect_time / n, 1),
        "realtime_factor": round((t + 1 / eff_fps) / wall, 2) if wall else None,
        "detector": getattr(detector, "name", type(detector).__name__),
    }
    summary = _summarize(meta.to_dict(), params, rules, metrics, zm, queue_zones, occ_zones, line_zones,
                         queues, occs, lines, dwell_records, events, time_in_status, time_above,
                         all_track_ids, eff_fps)
    return {
        "metadata": meta.to_dict(),
        "params": params,
        "rules": rules,
        "metrics": metrics,
        "events": events,
        "line_events": line_events,
        "dwell": [r.to_dict() for recs in dwell_records.values() for r in recs],
        "summary": summary,
        "stats": stats,
        "artifacts": {k: str(out_dir / v) for k, v in ARTIFACTS.items()},
    }


def _summarize(meta, params, rules, metrics, zm, queue_zones, occ_zones, line_zones, queues, occs,
               lines, dwell_records, events, time_in_status, time_above, all_track_ids, eff_fps) -> dict:
    people = np.array([m["active_people"] for m in metrics])
    times = np.array([m["timestamp"] for m in metrics])
    peak_i = int(people.argmax())
    summary: dict = {
        "video": meta,
        "processed_frames": len(metrics),
        "processed_duration_s": round(float(times[-1] - times[0]) + 1 / eff_fps, 2),
        "effective_fps": round(eff_fps, 2),
        "people": {
            "peak": int(people[peak_i]), "peak_time": float(times[peak_i]),
            "mean": round(float(people.mean()), 2),
            "unique_track_ids": len(all_track_ids),
        },
        "queues": {}, "occupancy": {}, "lines": {},
        "entries": None, "exits": None, "net_flow": None,
        "congestion": {
            "events": len(events),
            "by_type": {t: sum(1 for e in events if e["event_type"] == t)
                        for t in sorted({e["event_type"] for e in events})},
            "time_elevated_s": round(time_in_status["elevated"], 1),
            "time_congested_s": round(time_in_status["congested"], 1),
            "worst_status": max((m["congestion_status"] for m in metrics), key=STATUS_ORDER.get),
        },
        "available_metrics": ["active_people"],
        "notes": [
            "unique_track_ids is an upper bound on distinct people: occlusion and re-entry create new IDs.",
            "Queue count is a number of people, not a physical length.",
            "Heatmap is in image coordinates and distorted by perspective.",
        ],
    }
    for z in queue_zones:
        counts = np.array([m["zones"][z.id]["count"] for m in metrics])
        i = int(counts.argmax())
        summary["queues"][z.id] = {
            "name": z.name, "peak": int(counts[i]), "peak_time": float(times[i]),
            "mean": round(float(counts.mean()), 2),
            "final_trend": metrics[-1]["zones"][z.id]["trend"],
            "threshold": z.settings.get("queue_threshold", rules["queue_threshold"]),
            "time_alerting_s": round(time_above[z.id], 1),
            "dwell": DwellTracker.summarize(dwell_records[z.id]),
        }
    for z in occ_zones:
        counts = np.array([m["zones"][z.id]["count"] for m in metrics])
        i = int(counts.argmax())
        summary["occupancy"][z.id] = {
            "name": z.name, "capacity": z.capacity, "peak": int(counts[i]), "peak_time": float(times[i]),
            "peak_utilisation_pct": utilisation_pct(int(counts[i]), z.capacity),
            "mean": round(float(counts.mean()), 2),
            "threshold_pct": z.settings.get("occupancy_pct_threshold", rules["occupancy_pct_threshold"]),
            "time_alerting_s": round(time_above[z.id], 1),
            "dwell": DwellTracker.summarize(dwell_records[z.id]),
        }
    for z in line_zones:
        summary["lines"][z.id] = {"name": z.name, "type": z.zone_type,
                                  "entries": lines[z.id].entries, "exits": lines[z.id].exits}
    if queue_zones:
        summary["available_metrics"] += ["queue_count", "queue_trend", "queue_dwell"]
    if occ_zones:
        summary["available_metrics"] += ["occupancy_count", "occupancy_dwell"]
        if all(z.capacity for z in occ_zones):
            summary["available_metrics"].append("occupancy_pct")
    if line_zones:
        e = sum(ln.entries for ln in lines.values())
        x = sum(ln.exits for ln in lines.values())
        summary.update(entries=e, exits=x, net_flow=e - x)
        summary["available_metrics"] += ["entries", "exits", "net_flow"]
    return summary
