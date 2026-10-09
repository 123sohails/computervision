"""Run the CV pipeline on a video from the command line (no web server needed).

Example:
  python scripts/run_pipeline.py sample_videos/people-detection.mp4 --zones zones.json --out outputs/cli
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import config  # noqa: E402
from backend.services.detector import get_detector  # noqa: E402
from backend.services.pipeline import run_pipeline  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video")
    ap.add_argument("--zones", help="JSON file: list of zones, or a location export with a 'zones' key")
    ap.add_argument("--rules", help="JSON file with rule overrides")
    ap.add_argument("--out", default="outputs/cli")
    ap.add_argument("--stride", type=int, default=None)
    ap.add_argument("--conf", type=float, default=None)
    ap.add_argument("--imgsz", type=int, default=None)
    ap.add_argument("--model", default=config.MODEL_PATH)
    ap.add_argument("--device", default=config.DEVICE)
    args = ap.parse_args()

    zones = []
    if args.zones:
        data = json.loads(Path(args.zones).read_text())
        zones = data["zones"] if isinstance(data, dict) else data
    rules = json.loads(Path(args.rules).read_text()) if args.rules else None
    params = {"frame_stride": args.stride, "conf_threshold": args.conf, "imgsz": args.imgsz}

    def progress(p, info):
        print(f"\r{p * 100:5.1f}%  t={info['timestamp']:.1f}s", end="", flush=True)

    result = run_pipeline(args.video, zones, rules, params, args.out,
                          get_detector(args.model, args.device), progress)
    print()
    out = Path(args.out)
    (out / "summary.json").write_text(json.dumps(result["summary"], indent=2))
    (out / "events.json").write_text(json.dumps(result["events"], indent=2))
    (out / "metrics.json").write_text(json.dumps(result["metrics"]))
    (out / "stats.json").write_text(json.dumps(result["stats"], indent=2))
    print(json.dumps(result["stats"], indent=2))
    print(f"Outputs written to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
