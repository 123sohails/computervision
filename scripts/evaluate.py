"""Compare CampusVision outputs with manual annotations.

Inputs
  --pred   a job output folder (outputs/<job_id>) that contains detections.csv, plus either the
           job id (reads metrics from the SQLite DB) or a metrics.json written by run_pipeline.py.
  --gt     ground-truth JSON:

    {
      "frames": [
        {"frame_index": 120, "count": 7, "queue_count": 3,
         "boxes": [[x1, y1, x2, y2], ...]},          # boxes optional; count defaults to len(boxes)
        ...
      ],
      "entries": 12, "exits": 7,                      # optional manual crossing totals
      "mot_gt": "path/to/gt.txt"                      # optional MOTChallenge file for IDF1
    }

Annotate frames that were actually processed (frame_index divisible by the job's frame stride);
other frames are matched to the nearest processed frame and reported.

Outputs evaluation.json and evaluation.md next to the predictions.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def iou_matrix(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    if not len(a) or not len(b):
        return np.zeros((len(a), len(b)))
    x1 = np.maximum(a[:, None, 0], b[None, :, 0])
    y1 = np.maximum(a[:, None, 1], b[None, :, 1])
    x2 = np.minimum(a[:, None, 2], b[None, :, 2])
    y2 = np.minimum(a[:, None, 3], b[None, :, 3])
    inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    area = lambda r: (r[:, 2] - r[:, 0]) * (r[:, 3] - r[:, 1])  # noqa: E731
    return inter / (area(a)[:, None] + area(b)[None, :] - inter + 1e-9)


def match(pred: np.ndarray, gt: np.ndarray, thr: float = 0.5) -> int:
    """Greedy one-to-one matching by IoU; returns number of true positives."""
    ious = iou_matrix(pred, gt)
    tp = 0
    while ious.size and ious.max() >= thr:
        i, j = np.unravel_index(ious.argmax(), ious.shape)
        tp += 1
        ious[i, :] = -1
        ious[:, j] = -1
    return tp


def load_detections(path: Path, kind: str) -> dict[int, list]:
    out: dict[int, list] = defaultdict(list)
    with open(path) as f:
        for r in csv.DictReader(f):
            if r["kind"] == kind:
                out[int(r["frame_index"])].append(
                    [float(r["x1"]), float(r["y1"]), float(r["x2"]), float(r["y2"]),
                     int(r["track_id"]) if r["track_id"] else -1])
    return out


def load_metrics(pred_dir: Path, job_id: str | None) -> tuple[list[dict], dict]:
    if (pred_dir / "metrics.json").exists():
        stats = json.loads((pred_dir / "stats.json").read_text()) if (pred_dir / "stats.json").exists() else {}
        return json.loads((pred_dir / "metrics.json").read_text()), stats
    from backend import database as db

    job_id = job_id or pred_dir.name
    rows = db.fetch_all("SELECT * FROM metrics WHERE job_id=? ORDER BY frame_index", (job_id,))
    job = db.fetch_one("SELECT stats FROM jobs WHERE id=?", (job_id,))
    if not rows:
        raise SystemExit(f"No metrics found for job {job_id}")
    return rows, (job or {}).get("stats") or {}


def idf1(mot_gt: Path, tracks: dict[int, list]) -> dict:
    try:
        import motmetrics as mm
    except ImportError:
        return {"error": "pip install motmetrics to compute IDF1"}
    gt: dict[int, list] = defaultdict(list)
    for line in mot_gt.read_text().splitlines():
        p = line.split(",")
        if len(p) >= 6:  # MOT: frame(1-based), id, left, top, width, height, ...
            f, tid, x, y, w, h = int(p[0]) - 1, int(p[1]), *map(float, p[2:6])
            gt[f].append([x, y, x + w, y + h, tid])
    acc = mm.MOTAccumulator(auto_id=False)
    for f in sorted(gt):
        g = np.array(gt[f])
        pr = np.array(tracks.get(f, [])).reshape(-1, 5)
        dist = 1 - iou_matrix(g[:, :4], pr[:, :4]) if len(pr) else np.empty((len(g), 0))
        dist[dist > 0.5] = np.nan
        acc.update(g[:, 4].astype(int).tolist(), pr[:, 4].astype(int).tolist(), dist, frameid=f)
    s = mm.metrics.create().compute(acc, metrics=["idf1", "mota", "num_switches"], name="all")
    return {k: float(s[k].iloc[0]) for k in s.columns}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pred", required=True, help="job output folder (outputs/<job_id>)")
    ap.add_argument("--gt", required=True)
    ap.add_argument("--job-id")
    ap.add_argument("--iou", type=float, default=0.5)
    args = ap.parse_args()

    pred_dir, gt = Path(args.pred), json.loads(Path(args.gt).read_text())
    metrics, stats = load_metrics(pred_dir, args.job_id)
    by_frame = {m["frame_index"]: m for m in metrics}
    processed = np.array(sorted(by_frame))
    dets = load_detections(pred_dir / "detections.csv", "detection")
    tracks = load_detections(pred_dir / "detections.csv", "track")

    tp = fp = fn = 0
    count_err, queue_err, snapped = [], [], []
    rows = []
    for fr in gt["frames"]:
        idx = int(fr["frame_index"])
        near = int(processed[np.abs(processed - idx).argmin()])
        if near != idx:
            snapped.append((idx, near))
        m = by_frame[near]
        true_count = fr.get("count", len(fr.get("boxes", [])))
        count_err.append(abs(m["active_people"] - true_count))
        row = {"frame_index": idx, "true_count": true_count, "pred_count": m["active_people"]}
        if "queue_count" in fr and m.get("queue_count") is not None:
            queue_err.append(abs(m["queue_count"] - fr["queue_count"]))
            row.update(true_queue=fr["queue_count"], pred_queue=m["queue_count"])
        if "boxes" in fr:
            p = np.array([d[:4] for d in dets.get(near, [])]).reshape(-1, 4)
            g = np.array(fr["boxes"], dtype=float).reshape(-1, 4)
            t = match(p, g, args.iou)
            tp, fp, fn = tp + t, fp + len(p) - t, fn + len(g) - t
        rows.append(row)

    result: dict = {"annotated_frames": len(gt["frames"]), "snapped_frames": snapped,
                    "count_mae": round(float(np.mean(count_err)), 3) if count_err else None,
                    "count_max_error": int(max(count_err)) if count_err else None,
                    "queue_mae": round(float(np.mean(queue_err)), 3) if queue_err else None,
                    "processing_fps": stats.get("processing_fps"),
                    "realtime_factor": stats.get("realtime_factor"), "per_frame": rows}
    if tp + fp + fn:
        result.update(precision=round(tp / (tp + fp), 3) if tp + fp else None,
                      recall=round(tp / (tp + fn), 3) if tp + fn else None,
                      iou_threshold=args.iou, tp=tp, fp=fp, fn=fn)
    last = metrics[-1]
    for key in ("entries", "exits"):
        if key in gt and last.get(key) is not None:
            result[f"{key}_true"], result[f"{key}_pred"] = gt[key], last[key]
            result[f"{key}_error"] = last[key] - gt[key]
    if gt.get("mot_gt"):
        result["tracking"] = idf1(Path(gt["mot_gt"]), tracks)

    (pred_dir / "evaluation.json").write_text(json.dumps(result, indent=2))
    lines = ["# CampusVision evaluation", "", "| Metric | Value |", "|---|---|"]
    for k in ("annotated_frames", "precision", "recall", "count_mae", "count_max_error", "queue_mae",
              "entries_true", "entries_pred", "exits_true", "exits_pred", "processing_fps", "realtime_factor"):
        if result.get(k) is not None:
            lines.append(f"| {k} | {result[k]} |")
    for k, v in (result.get("tracking") or {}).items():
        lines.append(f"| tracking.{k} | {v} |")
    if snapped:
        lines += ["", f"{len(snapped)} annotated frames were not processed and were matched to the nearest processed frame."]
    (pred_dir / "evaluation.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
