import os

import numpy as np
import pytest

from backend.services.video_reader import VideoError, iter_frames, probe_video, read_frame_at


def test_probe_landscape(synthetic_video):
    m = probe_video(str(synthetic_video))
    assert (m.width, m.height, m.orientation) == (640, 480, "landscape")
    assert m.fps == pytest.approx(10.0)
    assert m.frame_count == 60 and m.duration == pytest.approx(6.0)
    assert m.size_bytes > 0


def test_probe_portrait_warns_but_succeeds(portrait_video):
    m = probe_video(str(portrait_video))
    assert m.orientation == "portrait"
    assert any("Portrait" in w for w in m.warnings)


def test_probe_rejects_non_video(tmp_path):
    bad = tmp_path / "notavideo.mp4"
    bad.write_bytes(b"hello world" * 100)
    with pytest.raises(VideoError):
        probe_video(str(bad))


def test_iter_frames_stride_preserves_timestamps(synthetic_video):
    frames = list(iter_frames(str(synthetic_video), stride=3))
    assert [f[0] for f in frames[:4]] == [0, 3, 6, 9]
    assert [round(f[1], 2) for f in frames[:4]] == [0.0, 0.3, 0.6, 0.9]
    assert len(frames) == 20


def test_read_frame_at(synthetic_video):
    assert read_frame_at(str(synthetic_video), 2.0).shape == (480, 640, 3)


SAMPLE = os.path.join(os.path.dirname(__file__), "..", "sample_videos", "people-detection.mp4")
MODEL = os.path.join(os.path.dirname(__file__), "..", "models", "yolo11n.pt")


@pytest.mark.skipif(not (os.path.exists(SAMPLE) and os.path.exists(MODEL)),
                    reason="needs sample_videos/people-detection.mp4 and models/yolo11n.pt")
def test_yolo_detects_people_on_sample():
    from backend.services.detector import YoloPersonDetector

    det = YoloPersonDetector(MODEL)
    found = 0
    for _, _, frame in iter_frames(SAMPLE, stride=30, max_frames=20):
        d = det.detect(frame, conf=0.35)
        assert d.xyxy.shape[1] == 4 and np.all(d.class_id == 0)
        assert np.all(d.confidence >= 0.35)
        found += len(d)
    assert found > 0
