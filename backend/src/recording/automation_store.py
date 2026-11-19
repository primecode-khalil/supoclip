"""PostgreSQL is the authority for capture ownership, progress, and retries.

Each method commits its own short transaction. Callers must use a fresh session
per concurrent operation. Lock order is channel then lease, including renewal.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal
from uuid import uuid4

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import RecordingChannel, RecordingSession, Task
from .automation_models import ChannelAutomation, RecordingLease, RecordingWindow
from .automation_schema import AutomationPolicy, WindowRegistration
from .errors import RecordingError, WindowClearedError
from .history import visible_history


@dataclass(frozen=True)
class Lease:
    channel_id: str
    holder: str
    fence: int
    expires_at: datetime


@dataclass(frozen=True)
class AutomationChannel:
    channel_id: str
    user_id: str
    url: str
    quality: str
    policy: AutomationPolicy


class LostLeaseError(RecordingError):
    def __init__(self):
        super().__init__("Recording lease lost", 409)


_WINDOW_TRANSITIONS = {
    "pending": {"pending", "submitting", "blocked"},
    "submitting": {"submitting", "processing", "blocked"},
    "processing": {"processing", "publishing", "completed", "blocked"},
    "publishing": {"publishing", "completed", "blocked"},
    "completed": {"completed"},
    "blocked": {"blocked"},
}
_WINDOW_UPDATABLE = {"status", "task_id", "upload_ref", "attempts", "next_attempt_at", "last_error", "details"}


def _ttl(value: int):
    if not isinstance(value, int) or isinstance(value, bool) or not 10 <= value <= 3600:
        raise ValueError("Lease TTL must be 10 to 3600 seconds")
    return timedelta(seconds=value)


def _token(row: RecordingLease) -> Lease:
    return Lease(row.channel_id, row.holder, row.fence, row.expires_at)


class AutomationStore:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _now(self) -> datetime:
        return (await self.db.execute(select(func.clock_timestamp()))).scalar_one()

    async def _channel(self, channel_id: str, user_id: str | None = None, *, lock=False):
        query = select(RecordingChannel).where(RecordingChannel.id == channel_id)
        if user_id is not None:
            query = query.where(RecordingChannel.user_id == user_id)
        if lock:
            query = query.with_for_update()
        channel = (await self.db.execute(query.execution_options(populate_existing=True))).scalar_one_or_none()
        if channel is None:
            await self.db.rollback()
            raise RecordingError("Channel not found", 404)
        return channel

    async def _lease(self, channel_id: str):
        return (await self.db.execute(select(RecordingLease).where(RecordingLease.channel_id == channel_id).with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()

    async def _fenced(self, token: Lease):
        channel = await self._channel(token.channel_id, lock=True)
        row = await self._lease(token.channel_id)
        now = await self._now()
        if row is None or row.holder != token.holder or row.fence != token.fence or row.expires_at <= now:
            await self.db.rollback()
            raise LostLeaseError()
        return channel, row, now

    async def get_policy(self, user_id: str, channel_id: str) -> dict:
        await self._channel(channel_id, user_id)
        row = await self.db.get(ChannelAutomation, channel_id, populate_existing=True)
        lease = await self.db.get(RecordingLease, channel_id, populate_existing=True)
        now = await self._now()
        result = {
            "policy": AutomationPolicy.model_validate(row.policy if row else {}),
            "runtime": {
                "leased": lease is not None and lease.expires_at > now,
                "expires_at": lease.expires_at if lease else None,
                "last_heartbeat_at": lease.last_heartbeat_at if lease else None,
                "last_error": lease.last_error if lease else None,
            },
        }
        await self.db.commit()
        return result

    async def put_policy(self, user_id: str, channel_id: str, policy: AutomationPolicy) -> dict:
        await self._channel(channel_id, user_id, lock=True)
        # IDs alone are never authority to publish. Revoked and foreign accounts
        # are indistinguishable; credentials stay in the native social store.
        for account_id in policy.social_account_ids:
            found = (await self.db.execute(text("SELECT 1 FROM social_accounts WHERE id=:id AND user_id=:owner AND status='active'"), {"id": account_id, "owner": user_id})).scalar_one_or_none()
            if found is None:
                await self.db.rollback()
                raise RecordingError("Configure an active social account owned by this user", 409)
        row = await self.db.get(ChannelAutomation, channel_id)
        if row is None:
            row = ChannelAutomation(channel_id=channel_id, policy=policy.model_dump())
            self.db.add(row)
        else:
            row.policy = policy.model_dump()
            row.updated_at = await self._now()
        await self.db.commit()
        return await self.get_policy(user_id, channel_id)

    async def list_enabled_channels(self) -> list[AutomationChannel]:
        rows = (await self.db.execute(select(RecordingChannel, ChannelAutomation).join(ChannelAutomation, ChannelAutomation.channel_id == RecordingChannel.id).where(RecordingChannel.enabled.is_(True)).order_by(RecordingChannel.created_at, RecordingChannel.id))).all()
        channels = []
        for channel, settings in rows:
            policy = AutomationPolicy.model_validate(settings.policy)
            if policy.enabled:
                channels.append(AutomationChannel(channel.id, channel.user_id, channel.url, channel.quality, policy))
        await self.db.commit()
        return channels

    async def acquire(self, channel_id: str, holder: str, ttl: int = 60) -> Lease | None:
        delta = _ttl(ttl)
        if not holder or len(holder) > 255 or not holder.isprintable():
            raise ValueError("Holder must contain 1 to 255 printable characters")
        channel = await self._channel(channel_id, lock=True)
        settings = await self.db.get(ChannelAutomation, channel_id, populate_existing=True)
        if not channel.enabled or settings is None or not AutomationPolicy.model_validate(settings.policy).enabled:
            await self.db.commit()
            return None
        row = await self._lease(channel_id)
        now = await self._now()
        if row is not None and row.expires_at > now and row.holder != holder:
            await self.db.commit()
            return None
        if row is None:
            row = RecordingLease(channel_id=channel_id, holder=holder, fence=1, expires_at=now + delta, last_heartbeat_at=now)
            self.db.add(row)
        else:
            # Even the same holder must receive a new fence after expiry. An old
            # task in that process must not inherit its successor's authority.
            if row.expires_at <= now:
                row.fence += 1
            row.holder = holder
            row.expires_at = now + delta
            row.last_heartbeat_at = now
        await self.db.commit()
        return _token(row)

    async def renew(self, token: Lease, ttl: int = 60) -> Lease | None:
        delta = _ttl(ttl)
        try:
            channel, row, now = await self._fenced(token)
        except LostLeaseError:
            return None
        settings = await self.db.get(ChannelAutomation, token.channel_id, populate_existing=True)
        if not channel.enabled or settings is None or not AutomationPolicy.model_validate(settings.policy).enabled:
            await self.db.commit()
            return None
        row.expires_at = now + delta
        row.last_heartbeat_at = now
        await self.db.commit()
        return _token(row)

    async def release(self, token: Lease) -> bool:
        try:
            _, row, now = await self._fenced(token)
        except LostLeaseError:
            return False
        row.expires_at = now
        await self.db.commit()
        return True

    async def report_error(self, token: Lease, message: str | None) -> None:
        _, row, _ = await self._fenced(token)
        row.last_error = message[:2000] if message else None
        await self.db.commit()

    async def create_or_resume_session(self, token: Lease) -> RecordingSession:
        channel, _, now = await self._fenced(token)
        session = (await self.db.execute(select(RecordingSession).where(RecordingSession.channel_id == token.channel_id, RecordingSession.status.in_(["created", "recording", "interrupted"])).with_for_update())).scalar_one_or_none()
        if session is None:
            policy = await self.db.get(ChannelAutomation, token.channel_id)
            snapshot = {key: getattr(channel, key) for key in ("platform", "handle", "url", "name", "quality", "enabled")}
            snapshot["automation"] = policy.policy if policy else AutomationPolicy().model_dump()
            session = RecordingSession(channel_id=token.channel_id, external_id=f"automation:{uuid4()}", settings_snapshot=snapshot, status="recording", created_at=now, started_at=now, updated_at=now)
            self.db.add(session)
        else:
            session.status = "recording"
            session.started_at = session.started_at or now
            session.updated_at = now
        await self.db.commit()
        return session

    async def finish_session(self, token: Lease, session_id: str, status: Literal["interrupted", "completed", "failed", "cancelled"]) -> RecordingSession:
        if status not in {"interrupted", "completed", "failed", "cancelled"}:
            raise ValueError("Invalid finishing status")
        _, _, now = await self._fenced(token)
        session = (await self.db.execute(select(RecordingSession).where(RecordingSession.id == session_id, RecordingSession.channel_id == token.channel_id).with_for_update())).scalar_one_or_none()
        if session is None:
            await self.db.rollback()
            raise RecordingError("Session not found", 404)
        if session.status != status:
            if session.status in {"completed", "failed", "cancelled"} or (status in {"interrupted", "completed"} and session.started_at is None):
                await self.db.rollback()
                raise RecordingError("Session is already terminal or has not started", 409)
            session.status = status
            session.updated_at = now
            session.ended_at = None if status == "interrupted" else now
        await self.db.commit()
        return session

    async def register_window(self, token: Lease, session_id: str, epoch: str, sequence: int, source_path: str, sha256: str, size_bytes: int, start_seconds: float, end_seconds: float, overlap_seconds: float = 0, metadata: dict | None = None) -> RecordingWindow:
        values = WindowRegistration(epoch=epoch, sequence=sequence, source_path=source_path, sha256=sha256, size_bytes=size_bytes, start_seconds=start_seconds, end_seconds=end_seconds, overlap_seconds=overlap_seconds).model_dump()
        await self._fenced(token)
        session = (await self.db.execute(select(RecordingSession.id).where(RecordingSession.id == session_id, RecordingSession.channel_id == token.channel_id))).scalar_one_or_none()
        if session is None:
            await self.db.rollback()
            raise RecordingError("Session not found", 404)
        existing = (await self.db.execute(select(RecordingWindow).where(RecordingWindow.channel_id == token.channel_id, RecordingWindow.session_id == session_id, RecordingWindow.epoch == epoch, RecordingWindow.sequence == sequence).execution_options(populate_existing=True))).scalar_one_or_none()
        if existing is not None:
            if any(getattr(existing, key) != value for key, value in values.items()):
                await self.db.rollback()
                raise RecordingError("Window identity and media are immutable", 409)
            await self.db.commit()
            return existing
        window = RecordingWindow(channel_id=token.channel_id, session_id=session_id, details=metadata or {}, **values)
        self.db.add(window)
        await self.db.commit()
        return window

    async def list_pending(self, token: Lease, limit: int = 100, *, include_blocked: bool = False) -> list[RecordingWindow]:
        if not 1 <= limit <= 1000:
            raise ValueError("Limit must be 1 to 1000")
        _, _, now = await self._fenced(token)
        query = select(RecordingWindow).where(RecordingWindow.channel_id == token.channel_id, visible_history(), RecordingWindow.status != "completed", (RecordingWindow.next_attempt_at.is_(None)) | (RecordingWindow.next_attempt_at <= now))
        if not include_blocked:
            query = query.where(RecordingWindow.status != "blocked")
        rows = (await self.db.execute(query.order_by(RecordingWindow.created_at, RecordingWindow.id).limit(limit).execution_options(populate_existing=True))).scalars().all()
        await self.db.commit()
        return list(rows)

    async def update_window(self, token: Lease, window_id: str, **values) -> RecordingWindow:
        if not values or not values.keys() <= _WINDOW_UPDATABLE:
            raise ValueError("Only mutable work progress may be updated")
        channel, _, now = await self._fenced(token)
        window = (await self.db.execute(select(RecordingWindow).where(RecordingWindow.id == window_id, RecordingWindow.channel_id == token.channel_id).with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()
        if window is None:
            await self.db.rollback()
            raise RecordingError("Window not found", 404)
        if window.details.get("history_cleared") is True:
            await self.db.rollback()
            raise WindowClearedError()
        if "status" in values and values["status"] not in _WINDOW_TRANSITIONS[window.status]:
            await self.db.rollback()
            raise RecordingError("Window progress cannot move backwards or reopen terminal work", 409)
        if "attempts" in values and (not isinstance(values["attempts"], int) or isinstance(values["attempts"], bool) or values["attempts"] < window.attempts):
            await self.db.rollback()
            raise RecordingError("Attempt count cannot decrease", 409)
        if values.get("task_id") is not None:
            task = (await self.db.execute(select(Task.id).where(Task.id == values["task_id"], Task.user_id == channel.user_id))).scalar_one_or_none()
            if task is None:
                await self.db.rollback()
                raise RecordingError("Task not found", 404)
            if window.task_id is not None and window.task_id != task:
                await self.db.rollback()
                raise RecordingError("Window task binding is immutable", 409)
        if "task_id" in values and window.task_id is not None and values["task_id"] is None:
            await self.db.rollback()
            raise RecordingError("Window task binding is immutable", 409)
        if "upload_ref" in values and window.upload_ref is not None and values["upload_ref"] != window.upload_ref:
            await self.db.rollback()
            raise RecordingError("Window upload binding is immutable", 409)
        if "details" in values:
            if not isinstance(values["details"], dict) or any(key in window.details and values["details"].get(key) != window.details[key] for key in ("policy", "segments")):
                await self.db.rollback()
                raise RecordingError("Window policy and source manifest are immutable", 409)
        if "last_error" in values and values["last_error"]:
            values["last_error"] = values["last_error"][:2000]
        for key, value in values.items():
            setattr(window, key, value)
        window.updated_at = now
        await self.db.commit()
        return window

    async def list_windows(self, user_id: str, channel_id: str, limit: int = 50, offset: int = 0) -> dict:
        await self._channel(channel_id, user_id)
        scoped = (RecordingWindow.channel_id == channel_id) & visible_history()
        total = (await self.db.execute(select(func.count()).select_from(RecordingWindow).where(scoped))).scalar_one()
        rows = (await self.db.execute(select(RecordingWindow).where(scoped).order_by(RecordingWindow.created_at.desc(), RecordingWindow.id.desc()).limit(limit).offset(offset))).scalars().all()
        await self.db.commit()
        return {"windows": list(rows), "total": total}

    async def clear_history(self, user_id: str, channel_id: str, scope: Literal["failed", "finished"] = "finished") -> dict:
        """Hide terminal history without deleting media or replay-prevention rows."""
        if scope not in {"failed", "finished"}:
            raise RecordingError("Unknown history scope", 422)
        await self._channel(channel_id, user_id, lock=True)
        statuses = ["blocked"] if scope == "failed" else ["blocked", "completed"]
        rows = (await self.db.execute(select(RecordingWindow).where(
            RecordingWindow.channel_id == channel_id, RecordingWindow.status.in_(statuses), visible_history(),
        ).with_for_update().execution_options(populate_existing=True))).scalars().all()
        now = await self._now()
        for window in rows:
            window.details = {**window.details, "history_cleared": True,
                "history_cleared_at": now.isoformat(), "history_cleared_reason": "owner_cleared"}
            window.next_attempt_at = None
            window.updated_at = now
        await self.db.commit()
        return {"cleared": len(rows)}

    async def mark_publication_capped(self, token: Lease, window_id: str) -> RecordingWindow:
        """Stop new automatic posts while retaining every committed receipt.

        The caller can hold a stale window from before a post was created.
        Merge into the current locked row instead of replacing its metadata.
        Reaching a policy limit is not a failed attempt or a timed retry.
        """
        _, _, now = await self._fenced(token)
        window = (await self.db.execute(select(RecordingWindow).where(
            RecordingWindow.id == window_id,
            RecordingWindow.channel_id == token.channel_id,
        ).with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()
        if window is None:
            await self.db.rollback()
            raise RecordingError("Window not found", 404)
        if window.details.get("history_cleared") is True:
            await self.db.rollback()
            raise WindowClearedError()
        if window.status != "publishing":
            await self.db.rollback()
            raise RecordingError("Only publishing work can reach the publication limit", 409)
        window.details = {**window.details, "publication_capped": True}
        window.next_attempt_at = None
        window.last_error = None
        window.updated_at = now
        await self.db.commit()
        return window

    async def retry_window(self, user_id: str, channel_id: str, window_id: str):
        """Explicit owner action opens another retry budget, keeping receipts."""
        await self._channel(channel_id, user_id, lock=True)
        window = (await self.db.execute(select(RecordingWindow).where(RecordingWindow.id == window_id,
            RecordingWindow.channel_id == channel_id).with_for_update())).scalar_one_or_none()
        if window is None:
            await self.db.rollback()
            raise RecordingError("Window not found", 404)
        if window.details.get("history_cleared") is True:
            await self.db.rollback()
            raise WindowClearedError()
        if window.status != "blocked":
            await self.db.rollback()
            raise RecordingError("Only blocked work can be retried", 409)
        window.status = "processing" if window.task_id else "submitting" if window.upload_ref else "pending"
        details = dict(window.details)
        details.update(retry_base=window.attempts, render_retries=0, post_queue_retries=0,
            manual_retries=int(details.get("manual_retries", 0)) + 1)
        window.details = details
        window.last_error = None
        window.next_attempt_at = None
        window.updated_at = await self._now()
        await self.db.commit()
        return window
