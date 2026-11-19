"""Private transfer state. Never serialize these rows into a public response."""
from __future__ import annotations

import json
from uuid import uuid4

from sqlalchemy import text


class YouTubeUploadRepository:
    FIELDS = frozenset({"session_url_encrypted", "confirmed_bytes", "bytes_started", "video_id", "stage",
        "reason_code", "actual_visibility", "next_attempt_at", "processing_started_at"})

    @staticmethod
    async def get(db, post_id: str) -> dict | None:
        row = (await db.execute(text("SELECT * FROM youtube_uploads WHERE post_id=:id"), {"id": post_id})).mappings().first()
        return dict(row) if row else None

    @staticmethod
    async def ensure(db, post_id: str, user_id: str, digest: str, size_bytes: int, metadata: dict) -> None:
        await db.execute(text("""
            INSERT INTO youtube_uploads (post_id,user_id,media_sha256,size_bytes,metadata_snapshot)
            SELECT p.id,p.user_id,:digest,:size,CAST(:metadata AS JSONB)
            FROM social_posts p WHERE p.id=:id AND p.user_id=:user
            ON CONFLICT(post_id) DO NOTHING
        """), {"id": post_id, "user": user_id, "digest": digest, "size": size_bytes, "metadata": json.dumps(metadata)})
        await db.commit()

    @staticmethod
    async def claim(db, post_id: str) -> dict | None:
        row = (await db.execute(text("""
            UPDATE youtube_uploads SET lease_token=:token, lease_expires_at=NOW()+INTERVAL '2 hours',
                attempts=attempts+1,updated_at=NOW()
            WHERE post_id=:id AND (lease_expires_at IS NULL OR lease_expires_at < NOW())
                AND (next_attempt_at IS NULL OR next_attempt_at <= NOW())
            RETURNING *
        """), {"id": post_id, "token": str(uuid4())})).mappings().first()
        await db.commit()
        return dict(row) if row else None

    @staticmethod
    async def update(db, post_id: str, token: str, *, release: bool = False, **fields) -> bool:
        if not fields or not set(fields).issubset(YouTubeUploadRepository.FIELDS):
            raise ValueError("Invalid YouTube transfer update")
        assignments = [f"{name}=:{name}" for name in fields]
        if release:
            assignments.extend(["lease_token=NULL", "lease_expires_at=NULL"])
        result = await db.execute(text(f"""
            UPDATE youtube_uploads SET {','.join(assignments)}, updated_at=NOW()
            WHERE post_id=:id AND lease_token=:token AND lease_expires_at > NOW()
        """), {**fields, "id": post_id, "token": token})
        await db.commit()
        return result.rowcount == 1
