"""Versioned, strict inputs for unattended recording policy and media manifests."""
from datetime import datetime
from pathlib import PurePosixPath
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..caption_templates import CAPTION_TEMPLATES
from .schemas import StrictInput, invalid

WindowStatus = Literal["pending", "submitting", "processing", "publishing", "completed", "blocked"]


class AutomationPolicy(StrictInput):
    enabled: bool = False
    segment_seconds: int = Field(default=600, ge=60, le=1800)
    overlap_seconds: int = Field(default=60, ge=0, le=120)
    processing_mode: Literal["fast", "balanced", "quality"] = "balanced"
    caption_template: str = "default"
    clip_length: Literal["auto", "short", "medium", "long"] = "auto"
    min_score: float = Field(default=75.0, ge=0, le=100, allow_inf_nan=False)
    max_clips_per_window: int = Field(default=3, ge=1, le=10)
    max_posts_per_day: int = Field(default=10, ge=1, le=100)
    social_account_ids: list[str] = Field(default_factory=list, max_length=10)
    publish_privacy: Literal["private", "public", "unlisted"] = "private"
    archive: bool = False
    retain_days: int = Field(default=7, ge=1, le=365)

    @field_validator("caption_template")
    @classmethod
    def known_template(cls, value: str):
        if value not in CAPTION_TEMPLATES:
            invalid("Unknown caption template")
        return value

    @field_validator("social_account_ids")
    @classmethod
    def account_ids(cls, value: list[str]):
        if len(value) != len(set(value)):
            invalid("Social account IDs must be unique")
        for account_id in value:
            try:
                if str(UUID(account_id)) != account_id:
                    invalid("Social account IDs must be canonical UUIDs")
            except ValueError:
                invalid("Social account IDs must be canonical UUIDs")
        return value

    @model_validator(mode="after")
    def overlap_fits_segment(self):
        if self.overlap_seconds >= self.segment_seconds:
            invalid("Overlap must be shorter than the segment")
        return self


class WindowRegistration(StrictInput):
    epoch: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")
    sequence: int = Field(ge=0)
    source_path: str = Field(min_length=1, max_length=1024)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(gt=0)
    start_seconds: float = Field(ge=0, allow_inf_nan=False)
    end_seconds: float = Field(gt=0, allow_inf_nan=False)
    overlap_seconds: float = Field(default=0, ge=0, allow_inf_nan=False)

    @field_validator("source_path")
    @classmethod
    def relative_path(cls, value: str):
        path = PurePosixPath(value)
        if value == "." or not value.isprintable() or "\\" in value or path.is_absolute() or ".." in path.parts or ":" in value or str(path) != value:
            invalid("Source path must be a normalized relative media path")
        return value

    @model_validator(mode="after")
    def valid_range(self):
        if self.end_seconds <= self.start_seconds:
            invalid("Window end must follow its start")
        if self.overlap_seconds >= self.end_seconds - self.start_seconds:
            invalid("Overlap must be shorter than the window")
        return self


class AutomationRuntime(BaseModel):
    leased: bool = False
    expires_at: datetime | None = None
    last_heartbeat_at: datetime | None = None
    last_error: str | None = None


class AutomationResponse(BaseModel):
    policy: AutomationPolicy
    runtime: AutomationRuntime


class WindowResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    channel_id: str
    session_id: str
    epoch: str
    sequence: int
    sha256: str
    size_bytes: int
    start_seconds: float
    end_seconds: float
    overlap_seconds: float
    status: WindowStatus
    task_id: str | None
    attempts: int
    next_attempt_at: datetime | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime


class WindowList(BaseModel):
    windows: list[WindowResponse]
    total: int
