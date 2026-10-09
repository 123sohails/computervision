"""Person detection with a pretrained YOLO model (COCO class 0 = person)."""
from __future__ import annotations

import threading
from typing import Protocol

import numpy as np
import supervision as sv

PERSON_CLASS_ID = 0


class Detector(Protocol):
    name: str

    def detect(self, frame: np.ndarray, conf: float, imgsz: int) -> sv.Detections: ...


class YoloPersonDetector:
    """Thin wrapper over ultralytics YOLO restricted to the person class."""

    def __init__(self, model_path: str, device: str = "cpu"):
        from ultralytics import YOLO  # imported lazily: heavy

        self.model = YOLO(model_path)  # downloads official weights if missing
        self.device = device
        self.name = str(model_path).rsplit("/", 1)[-1]
        self._lock = threading.Lock()

    def detect(self, frame: np.ndarray, conf: float = 0.35, imgsz: int = 640) -> sv.Detections:
        with self._lock:
            result = self.model.predict(
                frame, classes=[PERSON_CLASS_ID], conf=conf, imgsz=imgsz,
                device=self.device, verbose=False,
            )[0]
        dets = sv.Detections.from_ultralytics(result)
        return dets[dets.class_id == PERSON_CLASS_ID] if len(dets) else dets


_cache: dict[tuple[str, str], YoloPersonDetector] = {}
_cache_lock = threading.Lock()


def get_detector(model_path: str, device: str = "cpu") -> YoloPersonDetector:
    key = (model_path, device)
    with _cache_lock:
        if key not in _cache:
            _cache[key] = YoloPersonDetector(model_path, device)
        return _cache[key]
