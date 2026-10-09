"""Runtime configuration (paths, model, default pipeline parameters)."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _path(env: str, default: Path) -> Path:
    value = os.getenv(env)
    if not value:
        return default
    p = Path(value)
    return p if p.is_absolute() else ROOT / p


DATA_DIR = _path("CV_DATA_DIR", ROOT / "data")
UPLOAD_DIR = DATA_DIR / "uploads"
OUTPUT_DIR = _path("CV_OUTPUT_DIR", ROOT / "outputs")
DB_PATH = _path("CV_DB_PATH", DATA_DIR / "campusvision.db")
MODEL_PATH = str(_path("CV_MODEL", ROOT / "models" / "yolo11n.pt"))
DEVICE = os.getenv("CV_DEVICE", "cpu")
MAX_UPLOAD_MB = int(os.getenv("CV_MAX_UPLOAD_MB", "1024"))
FRONTEND_DIR = ROOT / "frontend"

ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".m4v", ".webm"}

DEFAULT_PIPELINE_PARAMS: dict = {
    "frame_stride": 2,          # process every Nth frame
    "conf_threshold": 0.35,     # min confidence for a detection to be reported / start a track
    "tracker_low_conf": 0.10,   # ByteTrack second-stage association uses weaker detections
    "imgsz": 640,               # model input size (longer side)
    "track_buffer_seconds": 1.5,
    "min_track_frames": 2,      # frames a track must persist before it gets an ID
    "max_output_width": 1280,   # annotated video is downscaled above this width
}

# Default congestion / analytics rules for a location. Zones may override any key via `settings`.
DEFAULT_RULES: dict = {
    "queue_threshold": 10,            # people in a queue zone
    "occupancy_pct_threshold": 80.0,  # % of configured capacity
    "sustained_seconds": 30.0,        # threshold must hold this long to count as sustained congestion
    "growth_amount": 5,               # queue increase (people) ...
    "growth_window_seconds": 60.0,    # ... within this window counts as rapid growth
    "smoothing_seconds": 3.0,         # rolling-average window used by alert rules
    "trend_window_seconds": 60.0,     # window for reported queue trend
    "cooldown_seconds": 60.0,         # min gap before re-raising the same alert for the same zone
    "dwell_absence_seconds": 2.0,     # track absent this long from a zone => visit completed
    "line_cooldown_seconds": 2.0,     # per-track cooldown between line crossings
}

for d in (DATA_DIR, UPLOAD_DIR, OUTPUT_DIR, Path(MODEL_PATH).parent):
    d.mkdir(parents=True, exist_ok=True)
