import time

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.workers.video_worker import VideoWorker
from tests.conftest import ScriptedDetector


@pytest.fixture
def client():
    app = create_app(VideoWorker(detector_factory=lambda: ScriptedDetector(fps=10)))
    with TestClient(app) as c:
        yield c


def wait_job(client, job_id, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("completed", "failed"):
            return job
        time.sleep(0.2)
    raise AssertionError("job timed out")


def test_locations_seeded(client):
    ids = {loc["id"] for loc in client.get("/api/locations").json()}
    assert {"cafeteria", "corridor", "entrance"} <= ids


def test_zone_crud_and_validation(client):
    body = {"location_id": "cafeteria", "name": "Counter queue", "zone_type": "QUEUE_ZONE",
            "points": [[0, 0.7], [0.4, 0.7], [0.4, 1], [0, 1]], "settings": {"queue_threshold": 3}}
    r = client.put("/api/zones/caf-q", json=body)
    assert r.status_code == 200 and r.json()["points"][0] == [0, 0.7]
    assert any(z["id"] == "caf-q" for z in client.get("/api/zones?location_id=cafeteria").json())
    bad = {**body, "points": [[0, 0], [2, 2], [0, 1]]}
    assert client.put("/api/zones/caf-bad", json=bad).status_code == 422
    assert client.put("/api/zones/caf-cap", json={**body, "capacity": 10}).status_code == 422
    assert client.delete("/api/zones/caf-q").status_code == 204
    assert client.get("/api/zones/caf-q").status_code == 404


def test_upload_rejects_bad_files(client, tmp_path):
    r = client.post("/api/videos", files={"file": ("notes.txt", b"hi", "text/plain")})
    assert r.status_code == 415
    r = client.post("/api/videos", files={"file": ("fake.mp4", b"not a video" * 50, "video/mp4")})
    assert r.status_code == 422


def test_upload_process_and_exports(client, synthetic_video):
    client.put("/api/zones/ent-door", json={"location_id": "entrance", "name": "Door",
                                            "zone_type": "ENTRY_LINE", "points": [[0.5, 0.5], [0.5, 1]]})
    client.put("/api/zones/ent-room", json={"location_id": "entrance", "name": "Lobby",
                                            "zone_type": "OCCUPANCY_ZONE", "capacity": 4,
                                            "points": [[0, 0], [1, 0], [1, 1], [0, 1]]})
    with open(synthetic_video, "rb") as f:
        r = client.post("/api/videos", data={"location_id": "entrance", "frame_stride": "2"},
                        files={"file": ("synthetic.avi", f, "video/x-msvideo")})
    assert r.status_code == 201, r.text
    video, job = r.json()["video"], r.json()["job"]
    assert video["width"] == 640 and video["orientation"] == "landscape"
    assert job["status"] == "queued" and job["params"]["frame_stride"] == 2
    assert len(job["zones_snapshot"]) == 2

    job = wait_job(client, job["id"])
    assert job["status"] == "completed", job["error"]
    assert job["summary"]["exits"] == 1 and job["stats"]["frames_processed"] == 30

    metrics = client.get(f"/api/jobs/{job['id']}/metrics").json()
    assert len(metrics) == 30 and metrics[-1]["occupancy_pct"] == 50.0
    assert metrics[-1]["queue_count"] is None
    assert client.get(f"/api/jobs/{job['id']}/events").status_code == 200
    v = client.get(f"/api/jobs/{job['id']}/video")
    assert v.status_code == 200 and v.headers["content-type"] == "video/mp4"
    csv_text = client.get(f"/api/jobs/{job['id']}/report.csv").text
    assert csv_text.splitlines()[0].startswith("frame_index,timestamp,active_people")
    assert "Door:entries" in csv_text.splitlines()[0]
    assert client.get(f"/api/jobs/{job['id']}/report.json").json()["summary"]["exits"] == 1
    assert client.get(f"/api/jobs/{job['id']}/detections.csv").status_code == 200
    assert client.get(f"/api/videos/{video['id']}/frame?t=1").headers["content-type"] == "image/jpeg"

    # Re-run uses current zones
    client.delete("/api/zones/ent-door")
    job2 = client.post(f"/api/videos/{video['id']}/jobs", json={"frame_stride": 3}).json()
    job2 = wait_job(client, job2["id"])
    assert job2["status"] == "completed" and job2["summary"]["entries"] is None

    assert client.delete(f"/api/videos/{video['id']}").status_code == 204
    assert client.get(f"/api/jobs/{job['id']}").status_code == 404
