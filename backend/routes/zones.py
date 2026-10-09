"""Locations (camera views) and their zone configurations."""
from __future__ import annotations

import re
import time
import uuid

from fastapi import APIRouter, HTTPException

from backend import config, database as db
from backend.routes.common import get_or_404
from backend.schemas import LocationIn, ZoneIn
from backend.services.zone_manager import ZONE_TYPES, validate_zone

router = APIRouter(prefix="/api", tags=["zones"])


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40]
    return s or uuid.uuid4().hex[:8]


@router.get("/config")
def get_config():
    return {"zone_types": sorted(ZONE_TYPES), "default_params": config.DEFAULT_PIPELINE_PARAMS,
            "default_rules": config.DEFAULT_RULES, "model": config.MODEL_PATH.rsplit("/", 1)[-1]}


@router.get("/locations")
def list_locations():
    locs = db.fetch_all("SELECT * FROM locations ORDER BY created_at, name")
    counts = {r["location_id"]: r["n"] for r in
              db.fetch_all("SELECT location_id, COUNT(*) AS n FROM zones GROUP BY location_id")}
    for loc in locs:
        loc["rules"] = {**config.DEFAULT_RULES, **loc["rules"]}
        loc["zone_count"] = counts.get(loc["id"], 0)
    return locs


@router.get("/locations/{location_id}")
def get_location(location_id: str):
    loc = get_or_404("locations", location_id, "Location")
    loc["rules"] = {**config.DEFAULT_RULES, **loc["rules"]}
    loc["zones"] = db.fetch_all("SELECT * FROM zones WHERE location_id=? ORDER BY name", (location_id,))
    return loc


def _clean_rules(rules: dict) -> dict:
    unknown = set(rules) - set(config.DEFAULT_RULES)
    if unknown:
        raise HTTPException(422, f"Unknown rule keys: {sorted(unknown)}")
    out = {}
    for k, v in rules.items():
        try:
            out[k] = float(v)
        except (TypeError, ValueError):
            raise HTTPException(422, f"Rule '{k}' must be a number") from None
        if out[k] < 0:
            raise HTTPException(422, f"Rule '{k}' must be >= 0")
    return out


@router.post("/locations", status_code=201)
def create_location(body: LocationIn):
    loc_id = _slug(body.name)
    if db.fetch_one("SELECT id FROM locations WHERE id=?", (loc_id,)):
        loc_id = f"{loc_id}-{uuid.uuid4().hex[:4]}"
    db.insert("locations", {"id": loc_id, "name": body.name, "description": body.description,
                            "rules": _clean_rules(body.rules), "created_at": time.time()})
    return get_location(loc_id)


@router.put("/locations/{location_id}")
def update_location(location_id: str, body: LocationIn):
    get_or_404("locations", location_id, "Location")
    db.update("locations", location_id, {"name": body.name, "description": body.description,
                                         "rules": _clean_rules(body.rules)})
    return get_location(location_id)


@router.delete("/locations/{location_id}", status_code=204)
def delete_location(location_id: str):
    get_or_404("locations", location_id, "Location")
    db.delete("locations", location_id)


@router.get("/zones")
def list_zones(location_id: str | None = None):
    if location_id:
        return db.fetch_all("SELECT * FROM zones WHERE location_id=? ORDER BY name", (location_id,))
    return db.fetch_all("SELECT * FROM zones ORDER BY location_id, name")


@router.get("/zones/{zone_id}")
def get_zone(zone_id: str):
    return get_or_404("zones", zone_id, "Zone")


@router.put("/zones/{zone_id}")
def put_zone(zone_id: str, body: ZoneIn):
    """Create or update a zone. Points are relative (0..1) to the frame width/height."""
    get_or_404("locations", body.location_id, "Location")
    try:
        validate_zone(body.zone_type, body.points, body.capacity)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    if body.capacity is not None and body.zone_type != "OCCUPANCY_ZONE":
        raise HTTPException(422, "capacity only applies to OCCUPANCY_ZONE")
    unknown = set(body.settings) - set(config.DEFAULT_RULES) - {"bidirectional"}
    if unknown:
        raise HTTPException(422, f"Unknown zone settings: {sorted(unknown)}")
    db.upsert("zones", {"id": zone_id, "location_id": body.location_id, "name": body.name,
                        "zone_type": body.zone_type, "points": body.points, "capacity": body.capacity,
                        "settings": body.settings, "updated_at": time.time()})
    return get_zone(zone_id)


@router.delete("/zones/{zone_id}", status_code=204)
def delete_zone(zone_id: str):
    get_or_404("zones", zone_id, "Zone")
    db.delete("zones", zone_id)
