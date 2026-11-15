"""Recording registry and lifecycle rules; this service never starts capture."""
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from ..recording.errors import RecordingError
from ..recording.schemas import ChannelCreate, ChannelUpdate, SessionCreate, SessionUpdate
from ..repositories.recording_repository import RecordingRepository

_TRANSITIONS = {
    "created": {"recording", "failed", "cancelled"},
    "recording": {"interrupted", "completed", "failed", "cancelled"},
    "interrupted": {"recording", "failed", "cancelled"},
    "completed": set(),
    "failed": set(),
    "cancelled": set(),
}


class RecordingService:
    def __init__(self, db: AsyncSession):
        self.repository = RecordingRepository(db)

    async def create_channel(self, user_id: str, payload: ChannelCreate):
        return await self.repository.create_channel(
            user_id, {**payload.model_dump(), "url": payload.url}
        )

    async def list_channels(self, user_id: str, limit: int, offset: int):
        return await self.repository.list_channels(user_id, limit, offset)

    async def get_channel(self, user_id: str, channel_id: str):
        return await self.repository.channel(user_id, channel_id)

    async def update_channel(self, user_id: str, channel_id: str, payload: ChannelUpdate):
        return await self.repository.update_channel(
            user_id, channel_id, payload.model_dump(exclude_unset=True)
        )

    async def register_session(self, user_id: str, channel_id: str, payload: SessionCreate):
        return await self.repository.register_session(
            user_id, channel_id, payload.external_id
        )

    async def list_sessions(self, user_id: str, channel_id: str, limit: int, offset: int):
        return await self.repository.list_sessions(user_id, channel_id, limit, offset)

    async def get_session(self, user_id: str, session_id: str):
        return await self.repository.session(user_id, session_id)

    async def update_session(self, user_id: str, session_id: str, payload: SessionUpdate):
        session = await self.repository.session(user_id, session_id, lock=True)
        if payload.status == session.status:
            await self.repository.commit()
            return session
        if payload.status not in _TRANSITIONS[session.status]:
            raise RecordingError(
                f"Cannot transition from {session.status} to {payload.status}", 409
            )
        now = datetime.now(timezone.utc)
        if payload.status == "recording" and session.started_at is None:
            session.started_at = now
        if payload.status in {"completed", "failed", "cancelled"}:
            session.ended_at = now
        session.status = payload.status
        session.updated_at = now
        return await self.repository.save_session(session)
