import pytest

from backend.services.congestion import CongestionEngine
from backend.services.dwell_time import DwellTracker
from backend.services.occupancy import OccupancyAnalytics, utilisation_pct
from backend.services.zone_manager import Zone

RULES = {"queue_threshold": 5, "occupancy_pct_threshold": 80, "sustained_seconds": 10,
         "growth_amount": 4, "growth_window_seconds": 20, "smoothing_seconds": 1, "cooldown_seconds": 30}
QZ = Zone("q", "Counter", "QUEUE_ZONE", [[0, 0], [1, 0], [1, 1]])
OZ = Zone("o", "Hall", "OCCUPANCY_ZONE", [[0, 0], [1, 0], [1, 1]], capacity=60)


def test_utilisation():
    assert utilisation_pct(42, 60) == 70.0
    assert utilisation_pct(5, None) is None


def test_occupancy_analytics():
    occ = OccupancyAnalytics(capacity=60)
    out = occ.update(0, range(42))
    assert out["count"] == 42 and out["utilisation_pct"] == 70.0


def test_dwell_completed_and_censoring():
    d = DwellTracker("q", absence_timeout_s=1.0)
    for i in range(0, 50):  # 5 s at 10 fps
        t = i * 0.1
        inside = [1]                      # track 1 present from the first frame (censored start)
        if 1.0 <= t <= 3.0:
            inside.append(2)              # track 2 fully observed for 2 s
        d.update(t, inside)
    recs = {r.track_id: r for r in d.finalize(4.9)}
    assert recs[1].censored_start and recs[1].censored_end and not recs[1].completed
    assert recs[2].completed and not recs[2].censored_start
    assert recs[2].duration == pytest.approx(2.0, abs=0.11)
    s = DwellTracker.summarize(list(recs.values()))
    assert s["fully_observed"]["count"] == 1
    assert s["observed"]["count"] == 2


def test_dwell_reentry_after_timeout_is_new_visit():
    d = DwellTracker("q", absence_timeout_s=0.5)
    for t, ids in [(0, []), (0.1, [7]), (0.2, [7]), (1.0, []), (1.5, [7]), (1.6, [7])]:
        d.update(t, ids)
    assert len(d.finalize(1.6)) == 2


def run_queue(engine, series, dt=1.0):
    statuses = []
    for i, v in enumerate(series):
        statuses.append(engine.update(i * dt, {"q": {"avg": v, "rise": 0}}))
    return statuses


def test_queue_threshold_then_sustained():
    eng = CongestionEngine([QZ], RULES)
    statuses = run_queue(eng, [3] * 3 + [8] * 15 + [2] * 3)
    assert statuses[2] == "normal" and statuses[4] == "elevated" and statuses[15] == "congested"
    assert statuses[-1] == "normal"
    types = [e.event_type for e in eng.finalize(21)]
    assert types == ["QUEUE_THRESHOLD", "SUSTAINED_CONGESTION"]
    sustained = eng.events[1]
    assert sustained.start_time == 3 and sustained.end_time == 18
    assert "stayed above the configured limit of 5" in sustained.reason
    assert "Lasted 15 s" in sustained.reason


def test_cooldown_suppresses_repeat_alerts():
    eng = CongestionEngine([QZ], RULES)
    run_queue(eng, [8, 8, 2, 8, 8, 2])
    assert [e.event_type for e in eng.events] == ["QUEUE_THRESHOLD"]


def test_rapid_growth():
    eng = CongestionEngine([QZ], RULES)
    eng.update(0, {"q": {"avg": 1, "rise": 0}})
    status = eng.update(5, {"q": {"avg": 4, "rise": 4.5}})
    assert status == "elevated"
    assert eng.events[0].event_type == "RAPID_GROWTH"
    assert "grew by 4.5 people within 20 s" in eng.events[0].reason


def test_occupancy_rule_and_finalize_open_event():
    eng = CongestionEngine([OZ], RULES)
    for i in range(5):
        eng.update(i, {"o": {"utilisation": 90.0}})
    events = eng.finalize(4)
    assert events[0].event_type == "OCCUPANCY_THRESHOLD"
    assert "Still active when the video ended" in events[0].reason


def test_zone_override_threshold():
    z = Zone("q2", "Small", "QUEUE_ZONE", [[0, 0], [1, 0], [1, 1]], settings={"queue_threshold": 2})
    eng = CongestionEngine([z], RULES)
    assert eng.update(0, {"q2": {"avg": 3, "rise": 0}}) == "elevated"
