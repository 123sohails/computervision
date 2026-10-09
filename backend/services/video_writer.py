"""Browser-playable (H.264) MP4 writer that pipes frames to ffmpeg, with an OpenCV fallback."""
from __future__ import annotations

import shutil
import subprocess
import tempfile

import cv2
import numpy as np


def ffmpeg_exe() -> str | None:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


class VideoSink:
    def __init__(self, path: str, width: int, height: int, fps: float):
        self.path, self.size = path, (width, height)
        self.proc = None
        self.cv_writer = None
        self._log = tempfile.TemporaryFile()
        exe = ffmpeg_exe()
        if exe:
            cmd = [exe, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24",
                   "-s", f"{width}x{height}", "-r", f"{fps:.4f}", "-i", "-",
                   "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2", "-c:v", "libx264", "-preset", "veryfast",
                   "-crf", "23", "-pix_fmt", "yuv420p", "-movflags", "+faststart", path]
            self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=self._log)
        else:
            self.cv_writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))

    def write(self, frame: np.ndarray) -> None:
        if frame.shape[1::-1] != self.size:
            frame = cv2.resize(frame, self.size)
        if self.proc:
            self.proc.stdin.write(np.ascontiguousarray(frame).tobytes())
        else:
            self.cv_writer.write(frame)

    def close(self) -> None:
        if self.proc:
            self.proc.stdin.close()
            code = self.proc.wait()
            if code != 0:
                self._log.seek(0)
                raise RuntimeError(f"ffmpeg failed ({code}): {self._log.read().decode(errors='ignore')[-500:]}")
        elif self.cv_writer:
            self.cv_writer.release()
        self._log.close()
