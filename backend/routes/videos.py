"""Video upload, metadata, preview frames and job creation."""
from __future__ import annotations

import os
import time
import uuid
from pathlib import Path

import cv2
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response

from backend import config, database as db
from backend.routes.common import get_or_404
from backend.schemas import JobParams
from backend.services.video_reader import VideoError, probe_video, read_frame_at
from backend.workers.video_worker import remove_job_outputs

router = APIRouter(prefix="/api", tags=["videos"])
CHUNK = 1024 * 1024


def create_job(request: Request, video: dict, params: dict) -> dict:
    location_id = video["location_id"]
    zones, rules = [], dict(config.DEFAULT_RULES)
    if location_id:
        loc = db.fetch_one("SELECT * FROM locations WHERE id=?", (location_id,))
        if loc:
            rules.update(loc["rules"])
        zones = db.fetch_all("SELECT id, name, zone_type, points, capacity, settings FROM zones "
                             "WHERE location_id=?", (location_id,))
    job_id = uuid.uuid4().hex[:12]
    merged = {**config.DEFAULT_PIPELINE_PARAMS, **{k: v for k, v in params.items() if v is not None}}
    db.insert("jobs", {"id": job_id, "video_id": video["id"], "location_id": location_id,
                       "status": "queued", "progress": 0, "params": merged, "zones_snapshot": zones,
                       "rules_snapshot": rules, "created_at": time.time()})
    request.app.state.worker.submit(job_id)
    return db.fetch_one("SELECT * FROM jobs WHERE id=?", (job_id,))


@router.post("/videos", status_code=201)
async def upload_video(request: Request, file: UploadFile = File(...), location_id: str = Form(""),
                       auto_process: bool = Form(True), frame_stride: int | None = Form(None),
                       conf_threshold: float | None = Form(None), imgsz: int | None = Form(None)):
    """Upload a video, validate it, store metadata and (optionally) queue a processing job."""
    ext = Path(file.filename or "").suffix.lower()
    if ext not in config.ALLOWED_VIDEO_EXTENSIONS:
        raise HTTPException(415, f"Unsupported file type '{ext}'. Allowed: "
                                 f"{', '.join(sorted(config.ALLOWED_VIDEO_EXTENSIONS))}")
    if location_id:
        get_or_404("locations", location_id, "Location")
    params = JobParams(frame_stride=frame_stride, conf_threshold=conf_threshold, imgsz=imgsz)

    video_id = uuid.uuid4().hex[:12]
    dest = Path(config.UPLOAD_DIR) / f"{video_id}{ext}"
    limit = config.MAX_UPLOAD_MB * CHUNK
    size = 0
    try:
        with open(dest, "wb") as out:
            while chunk := await file.read(CHUNK):
                size += len(chunk)
                if size > limit:
                    raise HTTPException(413, f"File exceeds {config.MAX_UPLOAD_MB} MB limit")
                out.write(chunk)
        meta = probe_video(str(dest))
    except VideoError as e:
        dest.unlink(missing_ok=True)
        raise HTTPException(422, f"Invalid video: {e}") from e
    except BaseException:
        dest.unlink(missing_ok=True)
        raise

    video = {"id": video_id, "location_id": location_id or None, "filename": file.filename,
             "path": str(dest), "created_at": time.time(), **meta.to_dict()}
    db.insert("videos", video)
    job = create_job(request, video, params.model_dump()) if auto_process else None
    return {"video": db.fetch_one("SELECT * FROM videos WHERE id=?", (video_id,)), "job": job}


@router.get("/videos")
def list_videos(location_id: str | None = None):
    if location_id:
        return db.fetch_all("SELECT * FROM videos WHERE location_id=? ORDER BY created_at DESC",
                            (location_id,))
    return db.fetch_all("SELECT * FROM videos ORDER BY created_at DESC")


@router.get("/videos/{video_id}")
def get_video(video_id: str):
    return get_or_404("videos", video_id, "Video")


@router.get("/videos/{video_id}/frame")
def video_frame(video_id: str, t: float = 0.0, max_width: int = 1280):
    """A JPEG frame used as the background for the zone editor."""
    video = get_or_404("videos", video_id, "Video")
    try:
        frame = read_frame_at(video["path"], max(0.0, t))
    except VideoError as e:
        raise HTTPException(422, str(e)) from e
    h, w = frame.shape[:2]
    if w > max_width:
        frame = cv2.resize(frame, (max_width, int(h * max_width / w)))
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return Response(buf.tobytes(), media_type="image/jpeg")


@router.get("/videos/{video_id}/source")
def video_source(video_id: str):
    video = get_or_404("videos", video_id, "Video")
    return FileResponse(video["path"], filename=video["filename"])


@router.post("/videos/{video_id}/jobs", status_code=201)
def reprocess(request: Request, video_id: str, params: JobParams | None = None):
    """Queue a new job for an existing video using the location's *current* zones and rules."""
    video = get_or_404("videos", video_id, "Video")
    if not os.path.isfile(video["path"]):
        raise HTTPException(410, "The original video file is no longer available")
    return create_job(request, video, (params or JobParams()).model_dump())


@router.patch("/videos/{video_id}")
def set_video_location(video_id: str, location_id: str):
    get_or_404("videos", video_id, "Video")
    get_or_404("locations", location_id, "Location")
    db.update("videos", video_id, {"location_id": location_id})
    return get_video(video_id)


@router.delete("/videos/{video_id}", status_code=204)
def delete_video(video_id: str):
    video = get_or_404("videos", video_id, "Video")
    for job in db.fetch_all("SELECT id FROM jobs WHERE video_id=?", (video_id,)):
        remove_job_outputs(job["id"])
    db.delete("videos", video_id)
    Path(video["path"]).unlink(missing_ok=True)
