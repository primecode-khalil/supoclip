"""Strict contracts for recording bookkeeping inputs."""
import re
import unicodedata
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_core import PydanticCustomError

Platform = Literal["twitch", "kick", "youtube"]
SessionStatus = Literal["created", "recording", "interrupted", "completed", "failed", "cancelled"]


def invalid(message: str):
    # No exception objects in validation context: the app serializes errors as JSON.
    raise PydanticCustomError("value_error", message)


def printable(value: str) -> str:
    if not value.isprintable():
        invalid("Must contain printable characters only")
    return value


def display_name(value: str) -> str:
    printable(value)
    value = value.strip()
    if not value or len(value) > 120:
        invalid("Name must contain 1 to 120 characters")
    return value


def quality_name(value: str) -> str:
    if len(value) > 255 or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]*(?:,[a-zA-Z0-9][a-zA-Z0-9_-]*)*", value):
        invalid("Quality must be comma-separated stream names, such as 720p,best")
    return value


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ChannelCreate(StrictInput):
    platform: Platform
    handle: str = Field(max_length=255)
    name: str
    enabled: bool = True
    quality: str = "best"

    _name = field_validator("name")(display_name)
    _quality = field_validator("quality")(quality_name)

    @model_validator(mode="after")
    def normalize_identity(self):
        printable(self.handle)
        handle = unicodedata.normalize("NFC", self.handle.strip()).lower()
        if self.platform == "youtube":
            handle = handle.removeprefix("@")
            if not (3 <= len(handle) <= 30) or not all(c.isalpha() or c.isdecimal() or c in "_.-" for c in handle):
                invalid("YouTube handle must contain 3 to 30 letters, numbers, dots, underscores or hyphens")
            if handle[0] in "_.-" or handle[-1] in "_.-":
                invalid("YouTube handle must start and end with a letter or number")
        else:
            pattern = r"[a-z0-9_]{3,25}" if self.platform == "twitch" else r"[a-z0-9_][a-z0-9_-]{2,24}"
            if not re.fullmatch(pattern, handle):
                invalid("Invalid platform handle")
        self.handle = handle
        return self

    @property
    def url(self) -> str:
        if self.platform == "youtube":
            return f"https://www.youtube.com/@{self.handle}"
        if self.platform == "twitch":
            return f"https://www.twitch.tv/{self.handle}"
        return f"https://kick.com/{self.handle}"


class ChannelUpdate(StrictInput):
    name: str | None = None
    enabled: bool | None = None
    quality: str | None = None

    @field_validator("name", "enabled", "quality", mode="before")
    @classmethod
    def nonnull(cls, value):
        if value is None:
            invalid("Updated fields cannot be null")
        return value

    _name = field_validator("name")(display_name)
    _quality = field_validator("quality")(quality_name)

    @model_validator(mode="after")
    def nonempty(self):
        if not self.model_fields_set:
            invalid("Provide at least one setting to update")
        return self


class SessionCreate(StrictInput):
    external_id: str = Field(min_length=1, max_length=255)
    _external_id = field_validator("external_id")(printable)


class SessionUpdate(StrictInput):
    status: SessionStatus


class ChannelResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    platform: Platform
    handle: str
    url: str
    name: str
    enabled: bool
    quality: str
    created_at: datetime
    updated_at: datetime


class SessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    channel_id: str
    external_id: str
    status: SessionStatus
    settings_snapshot: dict
    started_at: datetime | None
    ended_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ChannelList(BaseModel):
    channels: list[ChannelResponse]
    total: int


class SessionList(BaseModel):
    sessions: list[SessionResponse]
    total: int
