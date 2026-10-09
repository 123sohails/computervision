"""Video ingestion: metadata probing and timestamp-preserving frame sampling."""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from typing import Iterator

import cv2
import numpy as np

FALLBACK_FPS = 30.0


class VideoError(ValueError):
    """Raised when a file cannot be opened or decoded as video."""


@dataclass
class VideoMetadata:
    width: int
    height: int
    fps: float
    frame_count: int
    duration: float
    size_bytes: int
    orientation: str
    codec: str
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _fourcc(value: float) -> str:
    code = int(value)
    chars = "".join(chr((code >> (8 * i)) & 0xFF) for i in range(4))
    return chars if chars.isprintable() and chars.strip() else "unknown"


def _open(path: str) -> cv2.VideoCapture:
    if not os.path.isfile(path):
        raise VideoError(f"File not found: {path}")
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        cap.release()
        raise VideoError("OpenCV could not open the file as a video.")
    return cap


def probe_video(path: str) -> VideoMetadata:
    """Read container metadata and verify the first frame decodes."""
    cap = _open(path)
    try:
        ok, frame = cap.read()
        if not ok or frame is None:
            raise VideoError("The video contains no decodable frames.")
        height, width = frame.shape[:2]  # decoded size (rotation already applied)
        warnings: list[str] = []

        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        if not np.isfinite(fps) or fps <= 0 or fps > 240:
            warnings.append(f"Frame rate missing or invalid; assuming {FALLBACK_FPS:.0f} fps.")
            fps = FALLBACK_FPS

        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if frame_count <= 0:
            warnings.append("Frame count unavailable in container; progress will be approximate.")
            frame_count = 0
        duration = frame_count / fps if frame_count else 0.0

        if height > width:
            orientation = "portrait"
            warnings.append("Portrait video: a landscape (16:9) view is recommended for wide queues.")
        elif height == width:
            orientation = "square"
        else:
            orientation = "landscape"
        if max(width, height) < 640:
            warnings.append(f"Low resolution ({width}x{height}); small or distant people may be missed.")

        return VideoMetadata(
            width=width, height=height, fps=round(fps, 3), frame_count=frame_count,
            duration=round(duration, 3), size_bytes=os.path.getsize(path),
            orientation=orientation, codec=_fourcc(cap.get(cv2.CAP_PROP_FOURCC)), warnings=warnings,
        )
    finally:
        cap.release()


def iter_frames(path: str, stride: int = 1, fps: float | None = None,
                max_frames: int | None = None) -> Iterator[tuple[int, float, np.ndarray]]:
    """Yield (frame_index, timestamp_seconds, frame) for every `stride`-th frame.

    Skipped frames are grabbed but not decoded, so timestamps always refer to the
    original video timeline regardless of the sampling rate.
    """
    stride = max(1, int(stride))
    cap = _open(path)
    fps = fps or float(cap.get(cv2.CAP_PROP_FPS) or 0) or FALLBACK_FPS
    idx = -1
    yielded = 0
    last_ts = -1.0
    try:
        while True:
            if not cap.grab():
                break
            idx += 1
            if idx % stride:
                continue
            ok, frame = cap.retrieve()
            if not ok or frame is None:
                continue
            pos = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
            ts = pos if (pos > 0 or idx == 0) and pos > last_ts else idx / fps
            last_ts = ts
            yield idx, ts, frame
            yielded += 1
            if max_frames and yielded >= max_frames:
                break
    finally:
        cap.release()


def read_frame_at(path: str, t_seconds: float = 0.0) -> np.ndarray:
    cap = _open(path)
    try:
        if t_seconds > 0:
            cap.set(cv2.CAP_PROP_POS_MSEC, t_seconds * 1000.0)
        ok, frame = cap.read()
        if not ok or frame is None:
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = cap.read()
        if not ok or frame is None:
            raise VideoError("Could not decode a frame.")
        return frame
    finally:
        cap.release()
