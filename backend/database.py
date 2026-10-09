"""SQLite persistence: locations, zones, videos, jobs, metrics, events, dwell records."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator

from backend import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS locations (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    rules TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS zones (
    id TEXT PRIMARY KEY,
    location_id TEXT NOT NULL REFERENCES locations(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    zone_type TEXT NOT NULL,
    points TEXT NOT NULL,
    capacity INTEGER,
    settings TEXT NOT NULL DEFAULT '{}',
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS videos (
    id TEXT PRIMARY KEY,
    location_id TEXT REFERENCES locations(id) ON DELETE SET NULL,
    filename TEXT NOT NULL,
    path TEXT NOT NULL,
    size_bytes INTEGER,
    width INTEGER, height INTEGER,
    fps REAL, frame_count INTEGER, duration REAL,
    orientation TEXT, codec TEXT,
    warnings TEXT NOT NULL DEFAULT '[]',
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    video_id TEXT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    location_id TEXT,
    status TEXT NOT NULL,
    progress REAL NOT NULL DEFAULT 0,
    error TEXT,
    params TEXT NOT NULL DEFAULT '{}',
    zones_snapshot TEXT NOT NULL DEFAULT '[]',
    rules_snapshot TEXT NOT NULL DEFAULT '{}',
    summary TEXT,
    stats TEXT,
    created_at REAL NOT NULL,
    started_at REAL,
    finished_at REAL
);
CREATE TABLE IF NOT EXISTS metrics (
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    frame_index INTEGER NOT NULL,
    timestamp REAL NOT NULL,
    active_people INTEGER,
    queue_count INTEGER,
    occupancy_count INTEGER,
    occupancy_pct REAL,
    entries INTEGER,
    exits INTEGER,
    congestion_status TEXT,
    zones TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (job_id, frame_index)
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    zone_id TEXT,
    zone_name TEXT,
    start_time REAL NOT NULL,
    end_time REAL,
    peak_value REAL,
    threshold REAL,
    reason TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS dwell (
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    zone_id TEXT NOT NULL,
    track_id INTEGER NOT NULL,
    first_seen REAL NOT NULL,
    last_seen REAL NOT NULL,
    duration REAL NOT NULL,
    completed INTEGER NOT NULL,
    censored_start INTEGER NOT NULL,
    censored_end INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_job ON events(job_id);
CREATE INDEX IF NOT EXISTS idx_dwell_job ON dwell(job_id);
CREATE INDEX IF NOT EXISTS idx_zones_location ON zones(location_id);
"""

JSON_COLUMNS = {"rules", "points", "settings", "warnings", "params", "zones_snapshot",
                "rules_snapshot", "summary", "stats", "zones"}

DEFAULT_LOCATIONS = [
    ("cafeteria", "Cafeteria", "Serving-counter queue and seating area."),
    ("corridor", "Main corridor", "Through-traffic, occupancy and direction of movement."),
    ("entrance", "College entrance", "Entry/exit counting at the main gate or doorway."),
]

_lock = threading.Lock()


def _db_path() -> Path:
    return Path(config.DB_PATH)


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(_db_path(), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(seed: bool = True) -> None:
    _db_path().parent.mkdir(parents=True, exist_ok=True)
    with _lock, connect() as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA)
        if seed and conn.execute("SELECT COUNT(*) FROM locations").fetchone()[0] == 0:
            now = time.time()
            conn.executemany(
                "INSERT INTO locations (id, name, description, rules, created_at) VALUES (?,?,?,?,?)",
                [(i, n, d, json.dumps(config.DEFAULT_RULES), now) for i, n, d in DEFAULT_LOCATIONS],
            )


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    out = dict(row)
    for k in JSON_COLUMNS & out.keys():
        if isinstance(out[k], str):
            out[k] = json.loads(out[k])
    return out


def _dump(values: dict) -> dict:
    return {k: (json.dumps(v) if k in JSON_COLUMNS and not isinstance(v, str) and v is not None else v)
            for k, v in values.items()}


def fetch_one(sql: str, params: Iterable[Any] = ()) -> dict | None:
    with connect() as conn:
        return row_to_dict(conn.execute(sql, tuple(params)).fetchone())


def fetch_all(sql: str, params: Iterable[Any] = ()) -> list[dict]:
    with connect() as conn:
        return [row_to_dict(r) for r in conn.execute(sql, tuple(params)).fetchall()]


def insert(table: str, values: dict) -> None:
    values = _dump(values)
    cols = ", ".join(values)
    marks = ", ".join("?" for _ in values)
    with connect() as conn:
        conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", tuple(values.values()))


def upsert(table: str, values: dict, key: str = "id") -> None:
    values = _dump(values)
    cols = ", ".join(values)
    marks = ", ".join("?" for _ in values)
    updates = ", ".join(f"{c}=excluded.{c}" for c in values if c != key)
    with connect() as conn:
        conn.execute(
            f"INSERT INTO {table} ({cols}) VALUES ({marks}) ON CONFLICT({key}) DO UPDATE SET {updates}",
            tuple(values.values()),
        )


def update(table: str, row_id: str, values: dict) -> None:
    values = _dump(values)
    sets = ", ".join(f"{c}=?" for c in values)
    with connect() as conn:
        conn.execute(f"UPDATE {table} SET {sets} WHERE id=?", (*values.values(), row_id))


def delete(table: str, row_id: str) -> int:
    with connect() as conn:
        return conn.execute(f"DELETE FROM {table} WHERE id=?", (row_id,)).rowcount


def insert_many(table: str, rows: list[dict]) -> None:
    if not rows:
        return
    rows = [_dump(r) for r in rows]
    cols = list(rows[0].keys())
    sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})"
    with connect() as conn:
        conn.executemany(sql, [tuple(r[c] for c in cols) for r in rows])
