"""Owned PostgreSQL persistence; locks serialize registrations and state reports."""
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import RecordingChannel, RecordingSession
from ..recording.errors import RecordingError


class RecordingRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def commit(self) -> None:
        try:
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            if getattr(exc.orig, "sqlstate", None) == "23505":
                raise RecordingError(
                    "Channel identity or active session already exists", 409
                ) from exc
            raise

    async def channel(
        self, user_id: str, channel_id: str, *, lock: bool = False
    ) -> RecordingChannel:
        query = select(RecordingChannel).where(
            RecordingChannel.id == channel_id, RecordingChannel.user_id == user_id
        )
        if lock:
            query = query.with_for_update()
        result = (await self.db.execute(query)).scalar_one_or_none()
        if result is None:
            raise RecordingError("Channel not found", 404)
        return result

    async def create_channel(self, user_id: str, values: dict) -> RecordingChannel:
        channel = RecordingChannel(user_id=user_id, **values)
        self.db.add(channel)
        await self.commit()
        return channel

    async def list_channels(self, user_id: str, limit: int, offset: int) -> dict:
        owned = RecordingChannel.user_id == user_id
        total = (
            await self.db.execute(
                select(func.count()).select_from(RecordingChannel).where(owned)
            )
        ).scalar_one()
        rows = (
            await self.db.execute(
                select(RecordingChannel)
                .where(owned)
                .order_by(RecordingChannel.created_at.desc(), RecordingChannel.id.desc())
                .limit(limit)
                .offset(offset)
            )
        ).scalars().all()
        return {"channels": rows, "total": total}

    async def update_channel(
        self, user_id: str, channel_id: str, values: dict
    ) -> RecordingChannel:
        channel = await self.channel(user_id, channel_id, lock=True)
        for key, value in values.items():
            setattr(channel, key, value)
        channel.updated_at = func.clock_timestamp()
        await self.commit()
        await self.db.refresh(channel)
        return channel

    async def register_session(
        self, user_id: str, channel_id: str, external_id: str
    ) -> tuple[RecordingSession, bool]:
        # All registrars lock this durable channel row before checking replay/active
        # identity. The unique partial index also protects independent DB writers.
        channel = await self.channel(user_id, channel_id, lock=True)
        existing = (
            await self.db.execute(
                select(RecordingSession).where(
                    RecordingSession.channel_id == channel_id,
                    RecordingSession.external_id == external_id,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            await self.commit()
            return existing, False
        snapshot = {
            key: getattr(channel, key)
            for key in ("platform", "handle", "url", "name", "quality", "enabled")
        }
        session = RecordingSession(
            channel_id=channel_id,
            external_id=external_id,
            settings_snapshot=snapshot,
        )
        self.db.add(session)
        await self.commit()
        return session, True

    async def list_sessions(
        self, user_id: str, channel_id: str, limit: int, offset: int
    ) -> dict:
        await self.channel(user_id, channel_id)
        scoped = RecordingSession.channel_id == channel_id
        total = (
            await self.db.execute(
                select(func.count()).select_from(RecordingSession).where(scoped)
            )
        ).scalar_one()
        rows = (
            await self.db.execute(
                select(RecordingSession)
                .where(scoped)
                .order_by(RecordingSession.created_at.desc(), RecordingSession.id.desc())
                .limit(limit)
                .offset(offset)
            )
        ).scalars().all()
        return {"sessions": rows, "total": total}

    async def session(
        self, user_id: str, session_id: str, *, lock: bool = False
    ) -> RecordingSession:
        query = (
            select(RecordingSession)
            .join(RecordingChannel, RecordingSession.channel_id == RecordingChannel.id)
            .where(
                RecordingSession.id == session_id,
                RecordingChannel.user_id == user_id,
            )
        )
        if lock:
            query = query.with_for_update(of=RecordingSession)
        session = (await self.db.execute(query)).scalar_one_or_none()
        if session is None:
            raise RecordingError("Session not found", 404)
        return session

    async def save_session(self, session: RecordingSession) -> RecordingSession:
        await self.commit()
        await self.db.refresh(session)
        return session
