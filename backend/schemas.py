"""Request bodies for the API."""
from __future__ import annotations

from pydantic import BaseModel, Field


class ZoneIn(BaseModel):
    location_id: str
    name: str = Field(min_length=1, max_length=80)
    zone_type: str
    points: list[list[float]]
    capacity: int | None = None
    settings: dict = Field(default_factory=dict)


class LocationIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = ""
    rules: dict = Field(default_factory=dict)


class JobParams(BaseModel):
    frame_stride: int | None = Field(default=None, ge=1, le=30)
    conf_threshold: float | None = Field(default=None, gt=0, lt=1)
    imgsz: int | None = Field(default=None, ge=320, le=1920)
    track_buffer_seconds: float | None = Field(default=None, gt=0, le=10)
