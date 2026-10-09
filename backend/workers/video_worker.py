"""Background worker: processes queued jobs one at a time and persists results to SQLite."""
from __future__ import annotations

import logging
import queue
import shutil
import threading
import time
import traceback
from pathlib import Path
from typing import Callable

from backend import config, database as db
from backend.services.detector import Detector, get_detector
from backend.services.pipeline import run_pipeline

log = logging.getLogger("campusvision.worker")

DetectorFactory = Callable[[], Detector]


def job_output_dir(job_id: str) -> Path:
    return Path(config.OUTPUT_DIR) / job_id


class VideoWorker:
    def __init__(self, detector_factory: DetectorFactory | None = None):
        self._queue: "queue.Queue[str]" = queue.Queue()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._detector_factory = detector_factory or (lambda: get_detector(config.MODEL_PATH, config.DEVICE))

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="video-worker", daemon=True)
        self._thread.start()
        for job in db.fetch_all("SELECT id FROM jobs WHERE status IN ('queued','processing') "
                                "ORDER BY created_at"):
            db.update("jobs", job["id"], {"status": "queued", "progress": 0})
            self._queue.put(job["id"])

    def stop(self) -> None:
        self._stop.set()
        self._queue.put("")

    def submit(self, job_id: str) -> None:
        self._queue.put(job_id)

    def _run(self) -> None:
        while not self._stop.is_set():
            job_id = self._queue.get()
            if not job_id:
                continue
            try:
                self.process(job_id)
            except Exception:  # never let the worker thread die
                log.exception("Unexpected worker error for job %s", job_id)

    def process(self, job_id: str) -> None:
        job = db.fetch_one("SELECT * FROM jobs WHERE id=?", (job_id,))
        if not job or job["status"] not in ("queued", "processing"):
            return
        video = db.fetch_one("SELECT * FROM videos WHERE id=?", (job["video_id"],))
        if not video:
            db.update("jobs", job_id, {"status": "failed", "error": "Video record not found."})
            return
        db.update("jobs", job_id, {"status": "processing", "progress": 0, "started_at": time.time(),
                                   "error": None})
        out_dir = job_output_dir(job_id)
        last = [0.0]

        def progress(p: float, info: dict) -> None:
            now = time.time()
            if now - last[0] > 0.5:
                last[0] = now
                db.update("jobs", job_id, {"progress": round(p, 4)})

        try:
            result = run_pipeline(video["path"], job["zones_snapshot"], job["rules_snapshot"],
                                  job["params"], out_dir, self._detector_factory(), progress)
            self._save(job_id, result)
            db.update("jobs", job_id, {"status": "completed", "progress": 1.0, "finished_at": time.time(),
                                       "summary": result["summary"], "stats": result["stats"],
                                       "params": result["params"], "rules_snapshot": result["rules"]})
        except Exception as exc:
            log.error("Job %s failed: %s\n%s", job_id, exc, traceback.format_exc())
            db.update("jobs", job_id, {"status": "failed", "error": f"{type(exc).__name__}: {exc}",
                                       "finished_at": time.time()})

    @staticmethod
    def _save(job_id: str, result: dict) -> None:
        with db.connect() as conn:
            for table in ("metrics", "events", "dwell"):
                conn.execute(f"DELETE FROM {table} WHERE job_id=?", (job_id,))
        db.insert_many("metrics", [{**m, "job_id": job_id} for m in result["metrics"]])
        db.insert_many("events", [{**e, "job_id": job_id} for e in result["events"]])
        db.insert_many("dwell", [{
            "job_id": job_id, "zone_id": d["zone_id"], "track_id": d["track_id"],
            "first_seen": d["first_seen"], "last_seen": d["last_seen"], "duration": d["duration"],
            "completed": int(d["completed"]), "censored_start": int(d["censored_start"]),
            "censored_end": int(d["censored_end"]),
        } for d in result["dwell"]])


def remove_job_outputs(job_id: str) -> None:
    shutil.rmtree(job_output_dir(job_id), ignore_errors=True)
