"""Download public test clips (Intel IoT DevKit sample videos, Apache-2.0) into sample_videos/."""
from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

BASE = "https://github.com/intel-iot-devkit/sample-videos/raw/master/"
CLIPS = ["people-detection.mp4", "one-by-one-person-detection.mp4", "store-aisle-detection.mp4",
         "face-demographics-walking.mp4"]
DEST = Path(__file__).resolve().parent.parent / "sample_videos"


def main() -> int:
    DEST.mkdir(exist_ok=True)
    for name in CLIPS:
        target = DEST / name
        if target.exists():
            print(f"exists  {target}")
            continue
        print(f"fetch   {name}")
        urllib.request.urlretrieve(BASE + name, target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
