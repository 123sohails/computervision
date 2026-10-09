"""Approximate spatial density heatmap and movement trails in image coordinates.

Image-space density is distorted by perspective: distant and nearby regions do not
represent equal floor areas, so this is a qualitative visualisation only.
"""
from __future__ import annotations

from collections import defaultdict

import cv2
import numpy as np


class HeatmapAccumulator:
    def __init__(self, width: int, height: int, grid_width: int = 320, max_trail_points: int = 400):
        self.width, self.height = width, height
        self.scale = min(1.0, grid_width / float(width))
        self.gw, self.gh = max(1, int(width * self.scale)), max(1, int(height * self.scale))
        self.grid = np.zeros((self.gh, self.gw), dtype=np.float32)
        self.trails: dict[int, list[tuple[float, float]]] = defaultdict(list)
        self.max_trail_points = max_trail_points

    def add(self, points: np.ndarray, track_ids=None) -> None:
        points = np.asarray(points, dtype=float).reshape(-1, 2)
        if not len(points):
            return
        gx = np.clip((points[:, 0] * self.scale).astype(int), 0, self.gw - 1)
        gy = np.clip((points[:, 1] * self.scale).astype(int), 0, self.gh - 1)
        np.add.at(self.grid, (gy, gx), 1.0)
        if track_ids is not None:
            for tid, (x, y) in zip(track_ids, points):
                trail = self.trails[int(tid)]
                trail.append((float(x), float(y)))
                if len(trail) > self.max_trail_points:
                    del trail[::2]

    def density(self) -> np.ndarray:
        sigma = max(2.0, self.gw / 60.0)
        blurred = cv2.GaussianBlur(self.grid, (0, 0), sigma)
        peak = float(blurred.max())
        return blurred / peak if peak > 0 else blurred

    def render_heatmap(self, background: np.ndarray, alpha: float = 0.6) -> np.ndarray:
        h, w = background.shape[:2]
        dens = cv2.resize(self.density(), (w, h), interpolation=cv2.INTER_LINEAR)
        colored = cv2.applyColorMap((dens * 255).astype(np.uint8), cv2.COLORMAP_JET)
        weight = (np.clip(dens * 1.5, 0, 1) * alpha)[..., None]
        out = background.astype(np.float32) * (1 - weight) + colored.astype(np.float32) * weight
        return out.astype(np.uint8)

    def render_trails(self, background: np.ndarray, min_points: int = 3) -> np.ndarray:
        h, w = background.shape[:2]
        sx, sy = w / self.width, h / self.height
        out = (background * 0.45).astype(np.uint8)
        for tid, trail in self.trails.items():
            if len(trail) < min_points:
                continue
            pts = np.array([[x * sx, y * sy] for x, y in trail], dtype=np.int32)
            color = track_color(tid)
            cv2.polylines(out, [pts], False, color, 2, cv2.LINE_AA)
            cv2.circle(out, tuple(pts[-1]), 4, color, -1, cv2.LINE_AA)
        return out


def track_color(track_id: int) -> tuple[int, int, int]:
    hue = (int(track_id) * 47) % 180
    bgr = cv2.cvtColor(np.uint8([[[hue, 200, 255]]]), cv2.COLOR_HSV2BGR)[0, 0]
    return int(bgr[0]), int(bgr[1]), int(bgr[2])
