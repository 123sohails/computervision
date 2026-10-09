import os
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np
import pytest
import supervision as sv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_tmp = tempfile.mkdtemp(prefix="campusvision-test-")
os.environ.setdefault("CV_DATA_DIR", os.path.join(_tmp, "data"))
os.environ.setdefault("CV_OUTPUT_DIR", os.path.join(_tmp, "outputs"))


def person_box(cx, bottom, w=40, h=110):
    return [cx - w / 2, bottom - h, cx + w / 2, bottom]


def scripted_people(t):
    """Two synthetic people: A walks left->right across x=320, B stands still at x=150."""
    a = person_box(60 + 80 * t, 400)
    b = person_box(150, 420)
    return [a, b]


class ScriptedDetector:
    """Fake detector returning boxes from a function of time (frames carry an encoded index)."""

    name = "scripted"

    def __init__(self, fps, fn=scripted_people):
        self.fps, self.fn, self.calls = fps, fn, 0

    def detect(self, frame, conf=0.35, imgsz=640):
        idx = int(round(float(frame[0:16, 0:16].mean()) / 4))
        boxes = self.fn(idx / self.fps)
        self.calls += 1
        if not boxes:
            return sv.Detections.empty()
        return sv.Detections(xyxy=np.array(boxes, dtype=float), confidence=np.full(len(boxes), 0.9),
                             class_id=np.zeros(len(boxes), dtype=int))


def make_video(path, width=640, height=480, fps=10.0, seconds=6.0):
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), fps, (width, height))
    for i in range(int(fps * seconds)):
        frame = np.full((height, width, 3), 60, dtype=np.uint8)
        cv2.putText(frame, str(i), (width // 2, height // 2), cv2.FONT_HERSHEY_SIMPLEX, 2, (255, 255, 255), 3)
        frame[0:16, 0:16] = 4 * i  # flat block survives JPEG: encodes the frame index (i < 64)
        writer.write(frame)
    writer.release()
    return path


@pytest.fixture
def synthetic_video(tmp_path):
    return make_video(tmp_path / "synthetic.avi")


@pytest.fixture
def portrait_video(tmp_path):
    return make_video(tmp_path / "portrait.avi", width=360, height=640, fps=12, seconds=2)
