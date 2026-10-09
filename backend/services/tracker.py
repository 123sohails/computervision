"""Multi-object tracking with ByteTrack (supervision implementation)."""
from __future__ import annotations

import warnings

import numpy as np
import supervision as sv

with warnings.catch_warnings():
    warnings.simplefilter("ignore", FutureWarning)
    from supervision.tracker.byte_tracker.core import ByteTrack


class PersonTracker:
    """Assigns temporary track IDs to person detections.

    IDs are only as stable as the visual evidence: occlusion, crowding and people
    leaving/re-entering the view can split one person into several IDs.
    """

    def __init__(self, fps: float, activation_conf: float = 0.35, buffer_seconds: float = 1.5,
                 match_thresh: float = 0.8, min_track_frames: int = 2):
        fps = max(1.0, float(fps))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", FutureWarning)
            self._bt = ByteTrack(
                track_activation_threshold=activation_conf,
                lost_track_buffer=max(1, int(round(buffer_seconds * fps))),
                minimum_matching_threshold=match_thresh,
                frame_rate=fps,
                minimum_consecutive_frames=max(1, int(min_track_frames)),
            )

    def update(self, detections: sv.Detections) -> sv.Detections:
        """Return only detections that belong to a confirmed track (with `tracker_id`)."""
        if detections.class_id is None and len(detections):
            detections.class_id = np.zeros(len(detections), dtype=int)
        tracked = self._bt.update_with_detections(detections)
        if tracked.tracker_id is None or not len(tracked):
            return sv.Detections.empty()
        keep = tracked.tracker_id >= 0
        return tracked[keep]
