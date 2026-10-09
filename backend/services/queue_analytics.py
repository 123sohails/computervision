"""Queue counting, rolling averages and growth trend."""
from __future__ import annotations

from collections import deque

import numpy as np


class RollingSeries:
    """Time-windowed rolling mean plus a history of smoothed values for trend queries."""

    def __init__(self, smoothing_s: float = 3.0, history_s: float = 300.0):
        self.smoothing_s = smoothing_s
        self.history_s = history_s
        self._raw: deque[tuple[float, float]] = deque()
        self._smooth: deque[tuple[float, float]] = deque()
        self.peak: float = 0.0
        self.peak_time: float | None = None

    def update(self, t: float, value: float) -> float:
        self._raw.append((t, value))
        while self._raw and t - self._raw[0][0] > self.smoothing_s:
            self._raw.popleft()
        avg = float(np.mean([v for _, v in self._raw]))
        self._smooth.append((t, avg))
        while self._smooth and t - self._smooth[0][0] > self.history_s:
            self._smooth.popleft()
        if value > self.peak or self.peak_time is None:
            self.peak, self.peak_time = value, t
        return avg

    @property
    def average(self) -> float | None:
        return self._smooth[-1][1] if self._smooth else None

    def change_over(self, window_s: float) -> float | None:
        """Smoothed value now minus smoothed value `window_s` ago (None until enough history)."""
        if not self._smooth:
            return None
        t_now, v_now = self._smooth[-1]
        if t_now - self._smooth[0][0] < window_s * 0.95:
            return None
        target = t_now - window_s
        for t, v in reversed(self._smooth):
            if t <= target:
                return v_now - v
        return v_now - self._smooth[0][1]

    def rise_within(self, window_s: float) -> float:
        """Smoothed value now minus the minimum smoothed value within the window."""
        if not self._smooth:
            return 0.0
        t_now, v_now = self._smooth[-1]
        low = min(v for t, v in self._smooth if t_now - t <= window_s)
        return v_now - low


class QueueAnalytics:
    """Per-queue-zone metrics: Q_t = |active track IDs inside the queue zone|."""

    def __init__(self, smoothing_s: float = 3.0, trend_window_s: float = 60.0):
        self.series = RollingSeries(smoothing_s, history_s=max(300.0, trend_window_s * 2))
        self.trend_window_s = trend_window_s

    def update(self, t: float, track_ids_inside) -> dict:
        count = len(set(int(i) for i in track_ids_inside))
        avg = self.series.update(t, count)
        trend = self.series.change_over(self.trend_window_s)
        return {
            "count": count,
            "rolling_avg": round(avg, 2),
            "trend": None if trend is None else round(trend, 2),
            "trend_window_s": self.trend_window_s,
        }
