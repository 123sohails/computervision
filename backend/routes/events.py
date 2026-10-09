from __future__ import annotations

from fastapi import APIRouter

from backend import database as db
from backend.routes.common import get_or_404

router = APIRouter(prefix="/api", tags=["events"])


@router.get("/jobs/{job_id}/events")
def job_events(job_id: str):
    """Congestion events with the rule and reason that triggered each one."""
    get_or_404("jobs", job_id, "Job")
    return db.fetch_all("SELECT * FROM events WHERE job_id=? ORDER BY start_time, id", (job_id,))
