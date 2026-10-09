import numpy as np

from backend.services.line_counter import LineCounter
from backend.services.queue_analytics import QueueAnalytics

# Vertical line x=50 from top to bottom. p1=(50,0) -> p2=(50,100): positive side is x < 50
# (left-hand normal of a downward vector in image coordinates points to -x).


def walk(counter, tid, xs, y=50, t0=0.0, dt=0.1):
    events = []
    for i, x in enumerate(xs):
        events += counter.update(t0 + i * dt, [tid], np.array([[x, y]]))
    return events


def test_forward_crossing_counts_entry():
    lc = LineCounter((50, 0), (50, 100), "ENTRY_LINE", margin_px=2)
    ev = walk(lc, 1, [80, 70, 60, 40, 30])
    assert [e["direction"] for e in ev] == ["entry"]
    assert (lc.entries, lc.exits) == (1, 0)


def test_backward_crossing_counts_exit():
    lc = LineCounter((50, 0), (50, 100), "ENTRY_LINE", margin_px=2)
    walk(lc, 1, [20, 30, 45, 60, 80])
    assert (lc.entries, lc.exits) == (0, 1)


def test_exit_line_inverts_direction():
    lc = LineCounter((50, 0), (50, 100), "EXIT_LINE", margin_px=2)
    walk(lc, 1, [80, 60, 40, 20])
    assert (lc.entries, lc.exits) == (0, 1)


def test_jitter_near_line_is_ignored():
    lc = LineCounter((50, 0), (50, 100), margin_px=5)
    walk(lc, 1, [60, 52, 48, 53, 47, 51, 56])
    assert (lc.entries, lc.exits) == (0, 0)


def test_cooldown_prevents_double_count():
    lc = LineCounter((50, 0), (50, 100), margin_px=2, cooldown_s=2.0)
    walk(lc, 1, [80, 20, 80, 20], dt=0.2)  # back and forth within 0.6 s
    assert lc.entries + lc.exits == 1
    walk(lc, 1, [80, 20], t0=5.0)
    assert lc.entries + lc.exits == 2


def test_crossing_outside_segment_not_counted():
    lc = LineCounter((50, 0), (50, 100), margin_px=2)
    walk(lc, 1, [80, 20], y=300)  # crosses the infinite line far below the segment
    assert (lc.entries, lc.exits) == (0, 0)


def test_unidirectional_line():
    lc = LineCounter((50, 0), (50, 100), margin_px=2, bidirectional=False)
    walk(lc, 1, [20, 80])   # backward: ignored
    walk(lc, 2, [80, 20])   # forward: counted
    assert (lc.entries, lc.exits) == (1, 0)


def test_multiple_tracks_independent():
    lc = LineCounter((50, 0), (50, 100), margin_px=2)
    lc.update(0.0, [1, 2], np.array([[80, 50], [20, 50]]))
    lc.update(0.1, [1, 2], np.array([[20, 50], [80, 50]]))
    assert (lc.entries, lc.exits) == (1, 1)


def test_queue_count_uses_unique_track_ids():
    qa = QueueAnalytics(smoothing_s=1.0, trend_window_s=2.0)
    assert qa.update(0.0, [1, 2, 2, 3])["count"] == 3


def test_queue_trend_needs_history_then_reports_growth():
    qa = QueueAnalytics(smoothing_s=0.5, trend_window_s=2.0)
    out = None
    for i in range(31):  # 3 s at 10 fps, queue grows from 2 to 8 people
        t = i * 0.1
        n = 2 + int(t * 2)
        out = qa.update(t, list(range(n)))
        if t < 1.8:
            assert out["trend"] is None
    assert out["count"] == 8
    assert out["trend"] is not None and out["trend"] > 3
