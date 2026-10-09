# CampusVision AI — Intelligent Campus Occupancy and Queue Analytics

CampusVision takes ordinary recorded campus video and produces people counts, tracked movement, queue estimates, occupancy trends and congestion alerts. One application covers several campus locations: each location (camera view) keeps its own zones and rules.

| Capability | How it works |
|---|---|
| Person detection | Pretrained YOLO11n, person class only. Boxes include confidence scores |
| Multi-object tracking | ByteTrack (`supervision`) assigns temporary track IDs |
| Queue analytics | Counts tracked people in a configured queue polygon, with a rolling average and trend |
| Occupancy and congestion | Occupancy compared with an **explicitly configured** capacity. Rules are transparent: threshold, sustained duration, rapid growth, cooldown |
| Movement analytics | Direction-aware entry/exit lines, observed dwell time, a density heatmap and movement trails |

> Detection and tracking are established techniques. Waiting time, queue ordering and movement metrics are engineering estimates and must be validated against real footage (see [Evaluation](#evaluation)).

## Quick start

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu   # or a CUDA build
pip install -r requirements.txt
python scripts/download_samples.py        # optional public test clips
uvicorn backend.app:app --host 0.0.0.0 --port 8000
```

Then open http://localhost:8000. The YOLO weights (`models/yolo11n.pt`) download on first use.

Typical workflow:
1. **Upload**: choose a location and upload an MP4/AVI/MOV. The video is validated and its metadata recorded: resolution, fps, duration, frame count, size, orientation and codec. Any resolution or orientation is accepted. Portrait or low-resolution files are processed with a warning.
2. **Zones**: draw queue/occupancy/exclusion polygons and entry/exit lines on a frame from that video.
3. **Analyse** (or "Re-run with current zones"): this creates a job that moves through `queued → processing → completed | failed`.
4. **Dashboard**: annotated video, KPI cards that follow the playhead, charts, congestion events with reasons, zone summary, heatmap and trails. Downloads are available as MP4, CSV and JSON.

Command-line runs, with no server, are also supported:

```bash
python scripts/run_pipeline.py sample_videos/people-detection.mp4 --zones my_zones.json --out outputs/cli
```

## Architecture

```
Video (MP4/AVI/…) ─▶ OpenCV decode + frame sampling (original timestamps kept)
                  ─▶ YOLO person detection ─▶ exclusion zones ─▶ ByteTrack IDs
                  ─▶ zone analytics (queue, occupancy, lines, dwell) ─▶ congestion rules
                  ─▶ SQLite (jobs, metrics, events, dwell) + outputs/<job_id>/ (MP4, CSV, PNG)
                  ─▶ FastAPI ─▶ browser dashboard (vanilla JS + Chart.js)
```

```
backend/
  app.py                 FastAPI app; also serves frontend/
  config.py              paths, default pipeline params and rules (env overridable, see .env.example)
  database.py            SQLite schema + helpers; seeds Cafeteria / Corridor / Entrance locations
  routes/                videos.py, metrics.py (jobs, exports), events.py, zones.py (zones + locations)
  services/
    video_reader.py      probe metadata, timestamp-preserving frame iterator
    detector.py          YOLO person detector (pluggable protocol)
    tracker.py           ByteTrack wrapper
    zone_manager.py      relative-coordinate zones, bottom-centre point-in-polygon
    queue_analytics.py   Q_t, rolling average, trend
    occupancy.py         O_t, U_t = O_t / C × 100%
    line_counter.py      direction-aware crossing with margin + per-track cooldown
    dwell_time.py        per-visit observed dwell with start/end censoring
    congestion.py        threshold, sustained, rapid-growth rules with reasons
    heatmap.py           density heatmap and trails
    annotator.py         boxes, IDs, zones, HUD
    video_writer.py      H.264 MP4 via ffmpeg (browser playable)
    pipeline.py          orchestrates everything; usable without the web layer
  workers/video_worker.py  single background worker thread
frontend/                index.html, styles/, scripts/ (upload, zones, dashboard, locations)
scripts/                 run_pipeline.py, evaluate.py, download_samples.py
tests/                   unit + end-to-end tests (fake detector, synthetic video)
```

## Zones

| Type | Geometry | Used for |
|---|---|---|
| `QUEUE_ZONE` | polygon | queue count, trend, dwell, queue alerts (optional `queue_threshold` override) |
| `OCCUPANCY_ZONE` | polygon + `capacity` | occupancy count, % of capacity, occupancy alerts |
| `ENTRY_LINE` / `EXIT_LINE` | 2-point line | entries/exits. The arrow marks the "forward" direction: forward is an entry on an ENTRY_LINE and an exit on an EXIT_LINE. Reverse crossings count the other way unless `bidirectional` is off |
| `EXCLUSION_ZONE` | polygon | detections whose feet fall inside are ignored (e.g. staff behind a counter, posters, mirrors) |

* Points are stored **relative to frame size** (0–1), so one configuration fits any resolution of the same fixed camera view.
* Membership uses each box's **bottom-centre** (approximate ground-contact point).
* Zones are snapshotted into each job, which keeps every result reproducible.

## Analytics definitions

* **Queue count** \(Q_t\) = number of distinct active track IDs inside the queue zone. This is a number of people, *not* a physical length.
* **Queue trend** = rolling-average queue count now minus its value `trend_window_seconds` earlier. It reads `null` until there is enough history.
* **Occupancy** \(O_t\) = tracks inside the occupancy zone. Utilisation \(U_t = O_t / C × 100\%\) is only reported when a capacity \(C\) is configured.
* **Entries/exits**: a crossing counts only if the track was clearly (> 1% of the frame diagonal) on one side before and on the other side after, the crossing point lies on the drawn segment, and the track has not crossed that line within `line_cooldown_seconds`. Net flow = entries − exits.
* **Dwell**: one record per visit, running from the first to the last timestamp inside the zone. A visit ends after the track has been absent for `dwell_absence_seconds`. Visits already in progress when the video starts, or still in progress when it ends, are flagged as censored. *Fully observed* dwell excludes them and is the closer estimate of waiting time.
* **Congestion rules** use rolling averages (`smoothing_seconds`):
  * `QUEUE_THRESHOLD` / `OCCUPANCY_THRESHOLD`: the value exceeds its configured limit.
  * `SUSTAINED_CONGESTION`: a threshold holds for `sustained_seconds`.
  * `RAPID_GROWTH`: the queue grows by `growth_amount` within `growth_window_seconds`.
  * The same alert is not re-raised for a zone within `cooldown_seconds`, and release uses a small hysteresis.
  * Every event stores a readable reason, e.g. *"Queue count in 'Counter' stayed above the configured limit of 10 for at least 30 s. Lasted 42 s, peak 15.0."*
  * Status is `normal`, `elevated` (a rule is active) or `congested` (sustained).
* **Heatmap** is built in image coordinates. Because of perspective it is qualitative, not a floor-area map.
* **unique_track_ids** is an upper bound on distinct people: ID switches and re-entry inflate it.
* Metrics that cannot be computed are returned as `null` (e.g. `queue_count` when no queue zone exists) and listed in `summary.available_metrics`.

## API

| Endpoint | Purpose |
|---|---|
| `POST /api/videos` | Upload (multipart `file`, `location_id`, `auto_process`, `frame_stride`, `conf_threshold`, `imgsz`) and optionally create a job |
| `GET /api/videos`, `GET /api/videos/{id}` | Video metadata |
| `GET /api/videos/{id}/frame?t=` | JPEG frame for the zone editor |
| `POST /api/videos/{id}/jobs` | Re-process with the location's current zones and rules |
| `GET /api/jobs`, `GET /api/jobs/{id}` | Status, progress, errors, summary, run stats |
| `GET /api/jobs/{id}/metrics` | Time series (one row per processed frame) |
| `GET /api/jobs/{id}/events` | Congestion events with reasons |
| `GET /api/jobs/{id}/dwell` | Per-visit dwell records |
| `GET /api/jobs/{id}/video` | Annotated H.264 MP4 (`?download=true`) |
| `GET /api/jobs/{id}/report.csv` / `report.json` / `detections.csv` | Exports |
| `GET /api/jobs/{id}/heatmap.png` / `trails.png` | Movement visualisations |
| `GET /api/zones?location_id=`, `PUT /api/zones/{id}`, `DELETE /api/zones/{id}` | Zone configuration |
| `GET/POST /api/locations`, `GET/PUT/DELETE /api/locations/{id}` | Locations and their rules |

Interactive docs are served at `/docs`.

Example metrics row:

```json
{"frame_index": 300, "timestamp": 12.5, "active_people": 23, "queue_count": 8, "occupancy_count": 23,
 "occupancy_pct": 38.3, "entries": 12, "exits": 7, "congestion_status": "normal",
 "zones": {"cafeteria-queue": {"count": 8, "rolling_avg": 7.67, "trend": 2.3, "avg_dwell_s": 41.2}}}
```

## Processing parameters

Defaults live in `backend/config.py` and can be overridden per upload:

| Param | Default | Notes |
|---|---|---|
| `frame_stride` | 2 | Process every Nth frame. The annotated video plays at `fps / stride` and keeps the original timing |
| `conf_threshold` | 0.35 | Minimum confidence to report a detection or start a track |
| `tracker_low_conf` | 0.10 | ByteTrack also associates weaker detections with *existing* tracks, which helps through occlusion |
| `imgsz` | 640 | Raise it (960–1280) for small or distant people, at the cost of speed |
| `track_buffer_seconds` | 1.5 | How long a lost track is kept before its ID is retired |

These are starting points: benchmark them on your own footage.

## Evaluation

Judge the system against manual annotations rather than by eye:

```bash
python scripts/evaluate.py --pred outputs/<job_id> --gt my_annotations.json
```

The ground-truth format is documented in the script. It reports:
* precision and recall at IoU 0.5 (when boxes are annotated)
* people-count MAE \(\frac{1}{N}\sum |\hat y_i - y_i|\) and queue-count MAE
* entry/exit counting error
* processing FPS and real-time factor
* IDF1/MOTA/ID switches via `motmetrics`, when a MOTChallenge `gt.txt` is supplied

Results are written to `evaluation.json` and `evaluation.md`. Annotate crowded frames, partial occlusion, varied lighting and both walking directions, and report the numbers even when they expose limitations.

## Tests

```bash
python -m pytest -q
```

The tests use a synthetic video and a scripted detector, so they run in seconds without a GPU. A YOLO smoke test runs when `sample_videos/people-detection.mp4` and the weights are present.

## Recommended footage and privacy

* Use a fixed camera, landscape 1280×720 or 1920×1080.
* Prepare three demo clips: cafeteria queue (Video A), corridor (B) and entrance (C).
* Use only footage you have permission to use.
* No facial recognition or identity data: track IDs are temporary and only aggregate metrics are stored.

## Known limitations

* Track IDs can switch or fragment under occlusion, crowding or re-entry.
* Dwell time is *observed* time in a zone. It equals waiting time only for fully observed visits from a camera that sees both the queue entrance and the service point.
* Small or distant people may be missed at 640 px; raise `imgsz` if so.
* Processing is offline (uploaded files) on a single worker thread. Live webcam/RTSP input is not implemented yet.
* ByteTrack comes from `supervision<0.31`, where it is deprecated; it will need to move to the `trackers` package eventually.
