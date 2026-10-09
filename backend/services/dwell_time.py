"""Observed dwell time of tracks inside a zone."""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np


@dataclass
class DwellRecord:
    zone_id: str
    track_id: int
    first_seen: float
    last_seen: float
    completed: bool = False        # left the zone (absent > timeout) before the video ended
    censored_start: bool = False   # already inside when observation began
    censored_end: bool = False     # still inside when the video ended

    @property
    def duration(self) -> float:
        return max(0.0, self.last_seen - self.first_seen)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["duration"] = round(self.duration, 3)
        return d


class DwellTracker:
    """Tracks per-visit time in a zone.

    Reported values are *observed* dwell times. They are only an estimate of true
    waiting time when the visit is fully observed (not censored at start or end).
    """

    def __init__(self, zone_id: str, absence_timeout_s: float = 2.0, start_time: float = 0.0):
        self.zone_id = zone_id
        self.timeout = absence_timeout_s
        self.start_time = start_time
        self._first_update: float | None = None
        self.active: dict[int, DwellRecord] = {}
        self.finished: list[DwellRecord] = []

    def update(self, t: float, track_ids_inside) -> None:
        if self._first_update is None:
            self._first_update = t
        for tid in set(int(i) for i in track_ids_inside):
            rec = self.active.get(tid)
            if rec is None:
                self.active[tid] = DwellRecord(self.zone_id, tid, t, t,
                                               censored_start=(t <= self._first_update))
            else:
                rec.last_seen = t
        for tid in [k for k, r in self.active.items() if t - r.last_seen > self.timeout]:
            rec = self.active.pop(tid)
            rec.completed = True
            self.finished.append(rec)

    def current_dwell(self, t: float) -> list[float]:
        return [t - r.first_seen for r in self.active.values()]

    def finalize(self, end_time: float) -> list[DwellRecord]:
        for rec in self.active.values():
            rec.censored_end = True
            self.finished.append(rec)
        self.active = {}
        return self.finished

    @staticmethod
    def summarize(records: list[DwellRecord], min_duration_s: float = 1.0) -> dict:
        observed = [r.duration for r in records if r.duration >= min_duration_s]
        full = [r.duration for r in records
                if r.completed and not r.censored_start and r.duration >= min_duration_s]

        def stats(values: list[float]) -> dict:
            if not values:
                return {"count": 0, "mean": None, "median": None, "p90": None, "max": None}
            a = np.array(values)
            return {"count": int(a.size), "mean": round(float(a.mean()), 1),
                    "median": round(float(np.median(a)), 1),
                    "p90": round(float(np.percentile(a, 90)), 1), "max": round(float(a.max()), 1)}

        return {"observed": stats(observed), "fully_observed": stats(full),
                "min_duration_s": min_duration_s,
                "note": "fully_observed excludes visits already in progress at video start or still "
                        "in progress at video end; it is the closer estimate of waiting time."}
