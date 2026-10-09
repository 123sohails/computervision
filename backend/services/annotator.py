"""Draws detections, track IDs, zones, lines and a metrics HUD onto frames."""
from __future__ import annotations

import cv2
import numpy as np

from backend.services.heatmap import track_color
from backend.services.zone_manager import (ENTRY_LINE, EXCLUSION_ZONE, OCCUPANCY_ZONE, QUEUE_ZONE,
                                           ZoneManager)

ZONE_COLORS = {
    QUEUE_ZONE: (0, 165, 255),       # orange (BGR)
    OCCUPANCY_ZONE: (255, 160, 40),  # blue
    EXCLUSION_ZONE: (128, 128, 128),
}
STATUS_COLORS = {"normal": (80, 200, 80), "elevated": (0, 200, 255), "congested": (40, 40, 230)}
FONT = cv2.FONT_HERSHEY_SIMPLEX


def _label(img, text, org, scale, color, bg=(0, 0, 0), thickness=1):
    (tw, th), base = cv2.getTextSize(text, FONT, scale, thickness)
    x, y = int(org[0]), int(org[1])
    y = max(th + 2, y)
    cv2.rectangle(img, (x, y - th - 4), (x + tw + 4, y + base - 2), bg, -1)
    cv2.putText(img, text, (x + 2, y - 2), FONT, scale, color, thickness, cv2.LINE_AA)


def annotate(frame: np.ndarray, scale: float, zm: ZoneManager, xyxy: np.ndarray, conf: np.ndarray,
             track_ids: np.ndarray, zone_counts: dict, line_counts: dict, hud: dict) -> np.ndarray:
    """Return a resized, annotated copy of `frame`. Coordinates are in source pixels."""
    h, w = frame.shape[:2]
    out = cv2.resize(frame, (int(w * scale), int(h * scale))) if scale != 1 else frame.copy()
    oh, ow = out.shape[:2]
    lw = max(1, int(round(max(ow, oh) / 640)))
    fs = max(0.4, max(ow, oh) / 1800)

    overlay = out.copy()
    for z in zm.of_type(QUEUE_ZONE, OCCUPANCY_ZONE, EXCLUSION_ZONE):
        pts = (zm.abs[z.id] * scale).astype(np.int32)
        cv2.fillPoly(overlay, [pts], ZONE_COLORS[z.zone_type])
    cv2.addWeighted(overlay, 0.18, out, 0.82, 0, out)

    for z in zm.of_type(QUEUE_ZONE, OCCUPANCY_ZONE, EXCLUSION_ZONE):
        pts = (zm.abs[z.id] * scale).astype(np.int32)
        color = ZONE_COLORS[z.zone_type]
        cv2.polylines(out, [pts], True, color, lw + 1, cv2.LINE_AA)
        text = z.name
        if z.id in zone_counts:
            c = zone_counts[z.id]
            text += f": {c['count']}"
            if c.get("capacity"):
                text += f"/{c['capacity']}"
        top = pts[np.argmin(pts[:, 1])]
        _label(out, text, (top[0], top[1] - 4), fs, (255, 255, 255), color, 1)

    for z in zm.of_type(ENTRY_LINE, "EXIT_LINE"):
        p1, p2 = (zm.abs[z.id] * scale).astype(int)
        color = (60, 220, 60) if z.zone_type == ENTRY_LINE else (60, 60, 230)
        cv2.line(out, tuple(p1), tuple(p2), color, lw + 2, cv2.LINE_AA)
        d = (p2 - p1).astype(float)
        n = np.array([-d[1], d[0]]) / (np.hypot(*d) or 1)
        mid = (p1 + p2) / 2
        tip = mid + n * max(20, 0.05 * max(ow, oh))
        cv2.arrowedLine(out, tuple(mid.astype(int)), tuple(tip.astype(int)), color, lw + 1,
                        cv2.LINE_AA, tipLength=0.35)
        lc = line_counts.get(z.id, {"entries": 0, "exits": 0})
        _label(out, f"{z.name}  in {lc['entries']} / out {lc['exits']}", (p1[0], p1[1] - 6), fs,
               (255, 255, 255), color, 1)

    for (x1, y1, x2, y2), c, tid in zip(xyxy * scale, conf, track_ids):
        color = track_color(int(tid))
        cv2.rectangle(out, (int(x1), int(y1)), (int(x2), int(y2)), color, lw, cv2.LINE_AA)
        cv2.circle(out, (int((x1 + x2) / 2), int(y2)), lw + 2, color, -1, cv2.LINE_AA)
        _label(out, f"#{int(tid)} {c:.2f}", (x1, y1 - 2), fs * 0.85, (0, 0, 0), color, 1)

    lines = [f"t={hud['timestamp']:.1f}s", f"People: {hud['active_people']}"]
    if hud.get("queue_count") is not None:
        lines.append(f"Queue: {hud['queue_count']}")
    if hud.get("occupancy_pct") is not None:
        lines.append(f"Occupancy: {hud['occupancy_count']} ({hud['occupancy_pct']:.0f}%)")
    if hud.get("entries") is not None:
        lines.append(f"In {hud['entries']} / Out {hud['exits']}")
    status = hud.get("congestion_status", "normal")
    line_h = int(28 * fs * 1.6)
    box_h = line_h * (len(lines) + 1) + 10
    cv2.rectangle(out, (8, 8), (int(260 * fs * 1.9), 8 + box_h), (20, 20, 20), -1)
    for i, text in enumerate(lines):
        cv2.putText(out, text, (16, 8 + line_h * (i + 1)), FONT, fs * 1.1, (255, 255, 255), 1, cv2.LINE_AA)
    cv2.putText(out, status.upper(), (16, 8 + line_h * (len(lines) + 1)), FONT, fs * 1.1,
                STATUS_COLORS.get(status, (255, 255, 255)), 2, cv2.LINE_AA)
    return out
