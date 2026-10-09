import json

from backend.services.pipeline import run_pipeline
from tests.conftest import ScriptedDetector

ZONES = [
    {"id": "q", "name": "Queue", "zone_type": "QUEUE_ZONE",
     "points": [[0.0, 0.7], [0.4, 0.7], [0.4, 1.0], [0.0, 1.0]]},
    {"id": "o", "name": "Room", "zone_type": "OCCUPANCY_ZONE",
     "points": [[0, 0], [1, 0], [1, 1], [0, 1]], "capacity": 4},
    {"id": "door", "name": "Door", "zone_type": "ENTRY_LINE", "points": [[0.5, 0.5], [0.5, 1.0]]},
]


def test_pipeline_end_to_end(synthetic_video, tmp_path):
    det = ScriptedDetector(fps=10)
    r = run_pipeline(str(synthetic_video), ZONES, {"queue_threshold": 0, "sustained_seconds": 1},
                     {"frame_stride": 2, "min_track_frames": 1}, tmp_path / "out", det)
    assert det.calls == 30 and len(r["metrics"]) == 30
    last = r["metrics"][-1]
    assert last["active_people"] == 2
    assert last["occupancy_count"] == 2 and last["occupancy_pct"] == 50.0
    # Person A walks from x=60 to x=~520 and crosses the door line at x=320 (left -> right).
    # Line points downward, so the positive side is -x: moving +x is "backward" => exit.
    assert (last["entries"], last["exits"]) == (0, 1)
    # Person B stands in the queue zone the whole time.
    assert last["queue_count"] == 1
    assert r["summary"]["people"]["unique_track_ids"] == 2
    assert {e["event_type"] for e in r["events"]} >= {"QUEUE_THRESHOLD", "SUSTAINED_CONGESTION"}
    # A starts inside the queue zone and walks out (completed); B never leaves (censored both ends).
    dwell_q = sorted((d for d in r["dwell"] if d["zone_id"] == "q"), key=lambda d: d["duration"])
    assert len(dwell_q) == 2
    assert dwell_q[0]["completed"] and not dwell_q[0]["censored_end"]
    assert dwell_q[1]["censored_start"] and dwell_q[1]["censored_end"]
    for path in r["artifacts"].values():
        assert (tmp_path / "out").joinpath(path.rsplit("/", 1)[-1]).stat().st_size > 0
    json.dumps(r["summary"])  # serialisable


def test_pipeline_without_zones_marks_metrics_unavailable(synthetic_video, tmp_path):
    r = run_pipeline(str(synthetic_video), [], None, {"frame_stride": 3}, tmp_path / "out",
                     ScriptedDetector(fps=10))
    m = r["metrics"][-1]
    assert m["queue_count"] is None and m["entries"] is None and m["occupancy_pct"] is None
    assert m["occupancy_count"] == m["active_people"]
    assert r["summary"]["available_metrics"] == ["active_people"]


def test_exclusion_zone_removes_detections(synthetic_video, tmp_path):
    zones = [{"id": "x", "name": "Staff", "zone_type": "EXCLUSION_ZONE",
              "points": [[0.0, 0.8], [0.4, 0.8], [0.4, 1.0], [0.0, 1.0]]}]
    r = run_pipeline(str(synthetic_video), zones, None, {"frame_stride": 2, "min_track_frames": 1},
                     tmp_path / "out", ScriptedDetector(fps=10))
    assert max(m["active_people"] for m in r["metrics"]) == 1
