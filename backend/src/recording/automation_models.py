"""Durable capture ownership and immutable work identities shared across workers."""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from ..database import Base


class ChannelAutomation(Base):
    __tablename__ = "recording_automation"

    channel_id: Mapped[str] = mapped_column(String(36), ForeignKey("recording_channels.id", ondelete="CASCADE"), primary_key=True)
    policy: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class RecordingLease(Base):
    __tablename__ = "recording_automation_leases"
    __table_args__ = (CheckConstraint("fence > 0", name="ck_recording_lease_fence"),)

    channel_id: Mapped[str] = mapped_column(String(36), ForeignKey("recording_channels.id", ondelete="CASCADE"), primary_key=True)
    holder: Mapped[str] = mapped_column(String(255), nullable=False)
    fence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class RecordingWindow(Base):
    __tablename__ = "recording_windows"
    __table_args__ = (
        Index("uq_recording_window_identity", "channel_id", "session_id", "epoch", "sequence", unique=True),
        Index("ix_recording_windows_pending", "channel_id", "status", "next_attempt_at", "created_at"),
        CheckConstraint("status IN ('pending', 'submitting', 'processing', 'publishing', 'completed', 'blocked')", name="ck_recording_window_status"),
        CheckConstraint("sequence >= 0 AND size_bytes > 0 AND attempts >= 0", name="ck_recording_window_counts"),
        CheckConstraint("start_seconds >= 0 AND end_seconds > start_seconds AND end_seconds < 'Infinity'::double precision AND overlap_seconds >= 0 AND overlap_seconds < end_seconds - start_seconds", name="ck_recording_window_range"),
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="ck_recording_window_hash"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    channel_id: Mapped[str] = mapped_column(String(36), ForeignKey("recording_channels.id", ondelete="CASCADE"), nullable=False)
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("recording_sessions.id", ondelete="CASCADE"), nullable=False)
    epoch: Mapped[str] = mapped_column(String(80), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    source_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    start_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    end_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    overlap_seconds: Mapped[float] = mapped_column(Float, nullable=False, server_default=text("0"))
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'pending'"))
    task_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True)
    upload_ref: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    details: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    @property
    def publication_capped(self) -> bool:
        return (self.details or {}).get("publication_capped") is True
