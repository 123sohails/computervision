"""Direction-aware virtual line crossing (entries / exits)."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from backend.services.zone_manager import ENTRY_LINE, EXIT_LINE


@dataclass
class _TrackState:
    side: int            # last confirmed side: -1 or +1
    point: np.ndarray    # position when side was last confirmed
    last_seen: float
    last_cross: float = -1e9


class LineCounter:
    """Counts tracks crossing a directed line segment p1 -> p2.

    "Forward" means moving from the negative to the positive side, where the
    positive side is the left-hand normal (-dy, dx) of p1->p2 in image coordinates.
    ENTRY_LINE: forward = entry, backward = exit. EXIT_LINE: the opposite.

    A crossing only counts when the track is clearly (> margin px) on one side before
    and on the other side after, the crossing point lies on the segment, and the
    track has not crossed this line within `cooldown_s`.
    """

    def __init__(self, p1, p2, zone_type: str = ENTRY_LINE, margin_px: float = 6.0,
                 cooldown_s: float = 2.0, bidirectional: bool = True, stale_after_s: float = 10.0):
        self.p1 = np.asarray(p1, dtype=float)
        self.p2 = np.asarray(p2, dtype=float)
        d = self.p2 - self.p1
        self.length = float(np.hypot(*d)) or 1.0
        self.normal = np.array([-d[1], d[0]]) / self.length
        self.forward_is_entry = zone_type != EXIT_LINE
        self.margin = margin_px
        self.cooldown = cooldown_s
        self.bidirectional = bidirectional
        self.stale_after = stale_after_s
        self.entries = 0
        self.exits = 0
        self._tracks: dict[int, _TrackState] = {}

    def signed_distance(self, pts: np.ndarray) -> np.ndarray:
        return (np.asarray(pts, dtype=float).reshape(-1, 2) - self.p1) @ self.normal

    def _crosses_segment(self, a: np.ndarray, b: np.ndarray) -> bool:
        da, db = float(self.signed_distance(a)[0]), float(self.signed_distance(b)[0])
        if da == db:
            return False
        t = da / (da - db)
        hit = a + t * (b - a)
        u = float(np.dot(hit - self.p1, (self.p2 - self.p1))) / (self.length ** 2)
        tol = self.margin / self.length
        return -tol <= u <= 1 + tol

    def update(self, t: float, track_ids, points) -> list[dict]:
        events: list[dict] = []
        points = np.asarray(points, dtype=float).reshape(-1, 2)
        if len(points):
            dists = self.signed_distance(points)
            for tid, pt, dist in zip(track_ids, points, dists):
                tid = int(tid)
                state = self._tracks.get(tid)
                if abs(dist) <= self.margin:
                    if state:
                        state.last_seen = t
                    continue
                side = 1 if dist > 0 else -1
                if state is None:
                    self._tracks[tid] = _TrackState(side=side, point=pt.copy(), last_seen=t)
                    continue
                state.last_seen = t
                if side != state.side:
                    forward = side > 0
                    if (self._crosses_segment(state.point, pt) and t - state.last_cross >= self.cooldown
                            and (forward or self.bidirectional)):
                        is_entry = forward == self.forward_is_entry
                        if is_entry:
                            self.entries += 1
                        else:
                            self.exits += 1
                        state.last_cross = t
                        events.append({"track_id": tid, "timestamp": t,
                                       "direction": "entry" if is_entry else "exit"})
                    state.side = side
                state.point = pt.copy()
        for tid in [k for k, s in self._tracks.items() if t - s.last_seen > self.stale_after]:
            del self._tracks[tid]
        return events
