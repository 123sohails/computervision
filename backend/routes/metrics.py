"""Job status, time-series metrics, artifacts and exports."""
from __future__ import annotations

import csv
import io
import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response

from backend import database as db
from backend.routes.common import get_or_404
from backend.services.pipeline import ARTIFACTS
from backend.workers.video_worker import job_output_dir, remove_job_outputs

router = APIRouter(prefix="/api", tags=["jobs"])

JOB_LIST_SQL = """
SELECT j.id, j.video_id, j.location_id, j.status, j.progress, j.error, j.created_at, j.started_at,
       j.finished_at, v.filename, l.name AS location_name
FROM jobs j JOIN videos v ON v.id = j.video_id LEFT JOIN locations l ON l.id = j.location_id
"""


@router.get("/jobs")
def list_jobs(location_id: str | None = None, limit: int = 50):
    if location_id:
        return db.fetch_all(JOB_LIST_SQL + " WHERE j.location_id=? ORDER BY j.created_at DESC LIMIT ?",
                            (location_id, limit))
    return db.fetch_all(JOB_LIST_SQL + " ORDER BY j.created_at DESC LIMIT ?", (limit,))


@router.get("/jobs/{job_id}")
def get_job(job_id: str):
    job = get_or_404("jobs", job_id, "Job")
    job["video"] = db.fetch_one("SELECT * FROM videos WHERE id=?", (job["video_id"],))
    loc = db.fetch_one("SELECT name FROM locations WHERE id=?", (job["location_id"],)) \
        if job["location_id"] else None
    job["location_name"] = loc["name"] if loc else None
    return job


@router.delete("/jobs/{job_id}", status_code=204)
def delete_job(job_id: str):
    job = get_or_404("jobs", job_id, "Job")
    if job["status"] == "processing":
        raise HTTPException(409, "Job is processing")
    db.delete("jobs", job_id)
    remove_job_outputs(job_id)


def _metrics(job_id: str) -> list[dict]:
    return db.fetch_all("SELECT frame_index, timestamp, active_people, queue_count, occupancy_count, "
                        "occupancy_pct, entries, exits, congestion_status, zones FROM metrics "
                        "WHERE job_id=? ORDER BY frame_index", (job_id,))


@router.get("/jobs/{job_id}/metrics")
def job_metrics(job_id: str):
    """Per-processed-frame time series. `null` means the metric is unavailable (no zone configured)."""
    get_or_404("jobs", job_id, "Job")
    return _metrics(job_id)


@router.get("/jobs/{job_id}/dwell")
def job_dwell(job_id: str):
    get_or_404("jobs", job_id, "Job")
    return db.fetch_all("SELECT * FROM dwell WHERE job_id=? ORDER BY zone_id, first_seen", (job_id,))


def _artifact(job_id: str, key: str, media_type: str, download: str | None = None) -> FileResponse:
    job = get_or_404("jobs", job_id, "Job")
    path = job_output_dir(job_id) / ARTIFACTS[key]
    if job["status"] != "completed" or not path.is_file():
        raise HTTPException(404, f"{key} not available (job status: {job['status']})")
    return FileResponse(path, media_type=media_type, filename=download)


@router.get("/jobs/{job_id}/video")
def job_video(job_id: str, download: bool = False):
    return _artifact(job_id, "annotated_video", "video/mp4",
                     f"campusvision_{job_id}.mp4" if download else None)


@router.get("/jobs/{job_id}/heatmap.png")
def job_heatmap(job_id: str):
    return _artifact(job_id, "heatmap", "image/png")


@router.get("/jobs/{job_id}/trails.png")
def job_trails(job_id: str):
    return _artifact(job_id, "trails", "image/png")


@router.get("/jobs/{job_id}/thumbnail.jpg")
def job_thumbnail(job_id: str):
    path = job_output_dir(job_id) / ARTIFACTS["thumbnail"]
    if not path.is_file():
        raise HTTPException(404, "thumbnail not available")
    return FileResponse(path, media_type="image/jpeg")


@router.get("/jobs/{job_id}/detections.csv")
def job_detections(job_id: str):
    return _artifact(job_id, "detections_csv", "text/csv", f"detections_{job_id}.csv")


@router.get("/jobs/{job_id}/report.csv")
def job_report_csv(job_id: str):
    """Flat CSV: one row per processed frame, one column per zone metric."""
    job = get_or_404("jobs", job_id, "Job")
    rows = _metrics(job_id)
    zones = {z["id"]: z for z in job["zones_snapshot"]}
    base = ["frame_index", "timestamp", "active_people", "queue_count", "occupancy_count",
            "occupancy_pct", "entries", "exits", "congestion_status"]
    zone_cols: list[tuple[str, str]] = []
    for zid, z in zones.items():
        keys = {"QUEUE_ZONE": ["count", "rolling_avg", "trend", "avg_dwell_s"],
                "OCCUPANCY_ZONE": ["count", "utilisation_pct", "avg_dwell_s"],
                "ENTRY_LINE": ["entries", "exits"], "EXIT_LINE": ["entries", "exits"]}.get(z["zone_type"], [])
        zone_cols += [(zid, k) for k in keys]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(base + [f"{zones[zid]['name']}:{k}" for zid, k in zone_cols])
    for r in rows:
        w.writerow([("" if r[c] is None else r[c]) for c in base] +
                   [("" if r["zones"].get(zid, {}).get(k) is None else r["zones"][zid][k])
                    for zid, k in zone_cols])
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="report_{job_id}.csv"'})


@router.get("/jobs/{job_id}/report.json")
def job_report_json(job_id: str):
    """Reproducible summary: parameters, rules, zones, summary statistics, events and run stats."""
    job = get_job(job_id)
    events = db.fetch_all("SELECT * FROM events WHERE job_id=? ORDER BY start_time", (job_id,))
    payload = {k: job.get(k) for k in ("id", "status", "location_id", "location_name", "params",
                                         "rules_snapshot", "zones_snapshot", "summary", "stats",
                                         "created_at", "finished_at")}
    payload["video"] = job["video"]
    payload["events"] = events
    return Response(json.dumps(payload, indent=2), media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="report_{job_id}.json"'})
