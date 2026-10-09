"""Occupancy estimation against an explicitly configured capacity."""
from __future__ import annotations

from backend.services.queue_analytics import RollingSeries


def utilisation_pct(count: float, capacity: int | None) -> float | None:
    """U_t = O_t / C * 100. None when no capacity is configured."""
    if not capacity or capacity <= 0:
        return None
    return round(100.0 * count / capacity, 1)


class OccupancyAnalytics:
    def __init__(self, capacity: int | None, smoothing_s: float = 3.0):
        self.capacity = capacity
        self.series = RollingSeries(smoothing_s)

    def update(self, t: float, track_ids_inside) -> dict:
        count = len(set(int(i) for i in track_ids_inside))
        avg = self.series.update(t, count)
        return {
            "count": count,
            "rolling_avg": round(avg, 2),
            "capacity": self.capacity,
            "utilisation_pct": utilisation_pct(count, self.capacity),
            "rolling_utilisation_pct": utilisation_pct(avg, self.capacity),
        }
