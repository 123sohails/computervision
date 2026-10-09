"""Zone definitions (polygons and virtual lines in relative coordinates) and geometry helpers."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

QUEUE_ZONE = "QUEUE_ZONE"
OCCUPANCY_ZONE = "OCCUPANCY_ZONE"
ENTRY_LINE = "ENTRY_LINE"
EXIT_LINE = "EXIT_LINE"
EXCLUSION_ZONE = "EXCLUSION_ZONE"

POLYGON_TYPES = {QUEUE_ZONE, OCCUPANCY_ZONE, EXCLUSION_ZONE}
LINE_TYPES = {ENTRY_LINE, EXIT_LINE}
ZONE_TYPES = POLYGON_TYPES | LINE_TYPES


@dataclass
class Zone:
    id: str
    name: str
    zone_type: str
    points: list[list[float]]  # relative [x, y] in 0..1
    capacity: int | None = None
    settings: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "Zone":
        return cls(id=str(d["id"]), name=d.get("name") or str(d["id"]), zone_type=d["zone_type"],
                   points=[[float(x), float(y)] for x, y in d["points"]],
                   capacity=d.get("capacity"), settings=dict(d.get("settings") or {}))

    def abs_points(self, width: int, height: int) -> np.ndarray:
        return np.array(self.points, dtype=float) * np.array([width, height], dtype=float)

    @property
    def is_line(self) -> bool:
        return self.zone_type in LINE_TYPES


def validate_zone(zone_type: str, points: list, capacity: int | None = None) -> None:
    if zone_type not in ZONE_TYPES:
        raise ValueError(f"zone_type must be one of {sorted(ZONE_TYPES)}")
    if not isinstance(points, list) or not all(isinstance(p, (list, tuple)) and len(p) == 2 for p in points):
        raise ValueError("points must be a list of [x, y] pairs")
    for x, y in points:
        if not (0.0 <= float(x) <= 1.0 and 0.0 <= float(y) <= 1.0):
            raise ValueError("points must be relative coordinates between 0 and 1")
    if zone_type in LINE_TYPES and len(points) != 2:
        raise ValueError("lines need exactly 2 points")
    if zone_type in POLYGON_TYPES:
        if len(points) < 3:
            raise ValueError("polygons need at least 3 points")
        if polygon_area(np.array(points, dtype=float)) < 1e-5:
            raise ValueError("polygon area is too small")
    if capacity is not None and capacity <= 0:
        raise ValueError("capacity must be a positive integer")


def polygon_area(poly: np.ndarray) -> float:
    x, y = poly[:, 0], poly[:, 1]
    return 0.5 * abs(float(np.dot(x, np.roll(y, 1)) - np.dot(y, np.roll(x, 1))))


def bottom_center(xyxy: np.ndarray) -> np.ndarray:
    """Approximate ground-contact point of each box: (centre-x, bottom-y)."""
    xyxy = np.asarray(xyxy, dtype=float).reshape(-1, 4)
    return np.stack([(xyxy[:, 0] + xyxy[:, 2]) / 2.0, xyxy[:, 3]], axis=1)


def points_in_polygon(points: np.ndarray, polygon: np.ndarray) -> np.ndarray:
    """Vectorised even-odd ray casting. Returns a boolean array, one per point."""
    points = np.asarray(points, dtype=float).reshape(-1, 2)
    poly = np.asarray(polygon, dtype=float)
    if len(points) == 0:
        return np.zeros(0, dtype=bool)
    px, py = points[:, 0:1], points[:, 1:2]
    x1, y1 = poly[:, 0], poly[:, 1]
    x2, y2 = np.roll(x1, -1), np.roll(y1, -1)
    crosses = (y1 > py) != (y2 > py)
    with np.errstate(divide="ignore", invalid="ignore"):
        x_at = x1 + (py - y1) * (x2 - x1) / (y2 - y1)
    inside = np.logical_and(crosses, px < x_at)
    return np.count_nonzero(inside, axis=1) % 2 == 1


class ZoneManager:
    """Holds zones for one camera view scaled to a concrete frame size."""

    def __init__(self, zones: list[Zone], width: int, height: int):
        self.width, self.height = width, height
        self.zones = zones
        self.abs = {z.id: z.abs_points(width, height) for z in zones}

    def of_type(self, *types: str) -> list[Zone]:
        return [z for z in self.zones if z.zone_type in types]

    def excluded(self, points: np.ndarray) -> np.ndarray:
        mask = np.zeros(len(points), dtype=bool)
        for z in self.of_type(EXCLUSION_ZONE):
            mask |= points_in_polygon(points, self.abs[z.id])
        return mask

    def membership(self, points: np.ndarray) -> dict[str, np.ndarray]:
        return {z.id: points_in_polygon(points, self.abs[z.id])
                for z in self.of_type(QUEUE_ZONE, OCCUPANCY_ZONE)}
