"""Posting patterns use elapsed intervals or explicit local weekly times."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import math
import subprocess
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator, model_validator
from pydantic_core import PydanticCustomError

UTC = timezone.utc
PUBLICATION_LEAD = timedelta(minutes=15)
NATIVE_SCOPE = "https://www.googleapis.com/auth/youtube.force-ssl"


class SchedulePattern(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["interval", "weekly"] = "interval"
    interval_minutes: int = Field(default=360, ge=15, le=10080, strict=True)
    anchor_at: datetime | None = None
    weekdays: list[StrictInt] = Field(default_factory=lambda: list(range(7)), max_length=7)
    times: list[str] = Field(default_factory=lambda: ["09:00"], max_length=24)

    @field_validator("anchor_at")
    @classmethod
    def aware_anchor(cls, value):
        if value is not None and value.tzinfo is None:
            raise PydanticCustomError("invalid_pattern", "The interval anchor must include its timezone offset")
        return value

    @field_validator("weekdays")
    @classmethod
    def valid_days(cls, value):
        if len(value) != len(set(value)) or any(day < 0 or day > 6 for day in value):
            raise PydanticCustomError("invalid_pattern", "Choose unique weekdays from Monday to Sunday")
        return sorted(value)

    @field_validator("times")
    @classmethod
    def valid_times(cls, value):
        import re
        if len(value) != len(set(value)) or any(not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", t) for t in value):
            raise PydanticCustomError("invalid_pattern", "Choose unique posting times in HH:MM format")
        return sorted(value)

    @model_validator(mode="after")
    def nonempty_weekly(self):
        if self.kind == "weekly" and (not self.weekdays or not self.times):
            raise PydanticCustomError("invalid_pattern", "Weekly schedules need at least one day and time")
        return self


class PublishingPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["review", "automatic"] = "review"
    enabled: StrictBool = True
    uploads_paused: StrictBool = False
    timezone: str = "UTC"
    min_score: float = Field(default=75, ge=0, le=100, allow_inf_nan=False)
    category_id: str = Field(default="22", pattern=r"^[0-9]{1,3}$")
    made_for_kids: StrictBool = False
    contains_synthetic_media: StrictBool | None = None
    schedule: SchedulePattern = Field(default_factory=SchedulePattern)

    @field_validator("timezone")
    @classmethod
    def known_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise PydanticCustomError("invalid_timezone", "Choose a valid IANA timezone") from None
        return value


def _local_candidate(naive: datetime, zone: ZoneInfo) -> datetime | None:
    local = naive.replace(tzinfo=zone, fold=0)
    utc = local.astimezone(UTC)
    return utc if utc.astimezone(zone).replace(tzinfo=None) == naive else None


def next_publication_time(pattern: SchedulePattern, timezone_name: str, after: datetime) -> datetime:
    if after.tzinfo is None:
        raise ValueError("A publication boundary must include a timezone")
    if pattern.kind == "interval":
        anchor = pattern.anchor_at or datetime(1970, 1, 1, tzinfo=UTC)
        period = timedelta(minutes=pattern.interval_minutes)
        steps = max(0, math.ceil((after - anchor).total_seconds() / period.total_seconds()))
        return (anchor + steps * period).astimezone(UTC)
    zone = ZoneInfo(timezone_name)
    first = after.astimezone(zone).date()
    for offset in range(15):
        day = first + timedelta(days=offset)
        if day.weekday() not in pattern.weekdays:
            continue
        for clock in pattern.times:
            hour, minute = map(int, clock.split(":"))
            candidate = _local_candidate(datetime(day.year, day.month, day.day, hour, minute), zone)
            if candidate is not None and candidate >= after:
                return candidate
    raise ValueError("No valid publication slot was found in the next two weeks")


def local_publication_time(value: str, timezone_name: str, after: datetime) -> datetime:
    try:
        naive = datetime.fromisoformat(value)
        if naive.tzinfo is not None:
            raise ValueError()
        result = _local_candidate(naive, ZoneInfo(timezone_name))
    except (TypeError, ValueError, ZoneInfoNotFoundError):
        result = None
    if result is None or result < after:
        raise ValueError("Choose a valid future local time with at least 15 minutes of lead")
    return result


def validate_youtube_short(path: str) -> None:
    try:
        probe = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", path],
            capture_output=True, text=True, timeout=30)
        data = json.loads(probe.stdout) if probe.returncode == 0 else {}
        streams = data.get("streams", [])
        video = next((s for s in streams if s.get("codec_type") == "video"), {})
        audio = next((s for s in streams if s.get("codec_type") == "audio"), {})
        duration = float(data.get("format", {}).get("duration", 0))
        width, height = int(video.get("width", 0)), int(video.get("height", 0))
        if not (math.isfinite(duration) and 0 < duration <= 180 and width > 0 and height > 0
                and abs(width / height - 9 / 16) <= 0.01 and audio.get("codec_name")):
            raise ValueError()
        decoded = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-xerror", "-threads", "1", "-i", path,
            "-t", "1", "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "-"], capture_output=True, timeout=30)
        if decoded.returncode:
            raise ValueError()
    except (OSError, subprocess.TimeoutExpired, ValueError, TypeError, KeyError):
        raise ValueError("A Short must be a playable 9:16 video with audio, no longer than three minutes.") from None


async def reserve_publication_slot(db, review_id: str, now: datetime, *, custom_local: str | None = None,
                                  move_if_late: bool = False) -> datetime:
    from ..repositories.social_publication_policy_repository import SocialPublicationPolicyRepository as Policies
    return await Policies.reserve(db, review_id, now, custom_local=custom_local, move_if_late=move_if_late)


class SocialPublicationPolicyService:
    def __init__(self, db):
        self.db = db

    async def account(self, user_id: str, account_id: str) -> dict:
        from ..repositories.social_repository import SocialRepository
        from .social_service import SocialNotFound
        account = await SocialRepository.get_user_account(self.db, user_id, account_id)
        if not account or account.get("revoked_at") or account["provider"] != "youtube":
            raise SocialNotFound("Connected YouTube account not found")
        return account

    async def get(self, user_id: str, account_id: str) -> dict:
        from sqlalchemy import text
        from ..repositories.social_publication_policy_repository import SocialPublicationPolicyRepository as Policies
        account = await self.account(user_id, account_id)
        row = await Policies.get(self.db, user_id, account_id)
        policy = PublishingPolicy.model_validate(row["policy"] if row else {})
        now = (await self.db.execute(text("SELECT clock_timestamp()"))).scalar_one()
        if policy.schedule.anchor_at is None:
            anchor = (now + PUBLICATION_LEAD).replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            policy.schedule.anchor_at = anchor
        next_slot = await Policies.next_slot(self.db, user_id, account_id, policy, now)
        pending = (await self.db.execute(text("SELECT count(*) FROM social_review_items WHERE user_id=:user AND account_id=:account AND status='pending' AND clip_id IS NOT NULL"),
            {"user": user_id, "account": account_id})).scalar_one()
        return {"policy": policy.model_dump(mode="json"), "legacy": row is None,
            "enabled_at": row["enabled_at"].isoformat() if row and row["enabled_at"] else None,
            "next_slot": next_slot.isoformat(), "pending_review": pending,
            "private_test_completed": bool(account.get("metadata", {}).get("youtube_private_test_completed_at")),
            "permissions_complete": NATIVE_SCOPE in (account.get("scopes") or "").split()}

    async def save(self, user_id: str, account_id: str, changes: dict) -> dict:
        from ..repositories.social_publication_policy_repository import SocialPublicationPolicyRepository as Policies
        from .social_service import SocialValidationError
        account = await self.account(user_id, account_id)
        existing = await self.get(user_id, account_id)
        merged = {**existing["policy"], **changes}
        if "schedule" in changes:
            merged["schedule"] = {**existing["policy"]["schedule"], **changes["schedule"]}
        policy = PublishingPolicy.model_validate(merged)
        if policy.mode == "automatic" and policy.enabled and not policy.uploads_paused:
            if not existing["private_test_completed"]:
                raise SocialValidationError("Complete a verified private upload before enabling automatic approval.")
            if not existing["permissions_complete"]:
                raise SocialValidationError("Reconnect YouTube to grant native schedule management access.")
        if not await Policies.lock_account(self.db, user_id, account_id):
            raise SocialValidationError("The destination was disconnected.")
        await Policies.save(self.db, user_id, account_id, policy.model_dump(mode="json"))
        return await self.get(user_id, account_id)
