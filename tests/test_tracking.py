import numpy as np
import supervision as sv

from backend.services.tracker import PersonTracker


def dets(boxes, conf=0.9):
    return sv.Detections(xyxy=np.array(boxes, dtype=float), confidence=np.full(len(boxes), conf),
                         class_id=np.zeros(len(boxes), dtype=int))


def test_same_person_keeps_id_across_frames():
    tr = PersonTracker(fps=10, min_track_frames=1)
    ids = []
    for i in range(20):
        out = tr.update(dets([[100 + 3 * i, 100, 140 + 3 * i, 220]]))
        ids += out.tracker_id.tolist()
    assert len(set(ids)) == 1 and len(ids) >= 19


def test_two_people_get_distinct_ids():
    tr = PersonTracker(fps=10, min_track_frames=1)
    seen = set()
    for i in range(10):
        out = tr.update(dets([[100 + 2 * i, 100, 140 + 2 * i, 220], [400 - 2 * i, 100, 440 - 2 * i, 220]]))
        seen.update(out.tracker_id.tolist())
    assert len(seen) == 2


def test_short_occlusion_keeps_id():
    tr = PersonTracker(fps=10, buffer_seconds=1.0, min_track_frames=1)
    first = None
    for i in range(10):
        out = tr.update(dets([[100 + 2 * i, 100, 140 + 2 * i, 220]]))
        first = first or int(out.tracker_id[0])
    for _ in range(4):  # 0.4 s with no detection
        tr.update(sv.Detections.empty())
    for i in range(14, 20):
        out = tr.update(dets([[100 + 2 * i, 100, 140 + 2 * i, 220]]))
    assert int(out.tracker_id[0]) == first


def test_low_confidence_detection_does_not_start_track():
    tr = PersonTracker(fps=10, activation_conf=0.5, min_track_frames=1)
    for _ in range(5):
        out = tr.update(dets([[100, 100, 140, 220]], conf=0.2))
    assert len(out) == 0
