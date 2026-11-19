"""Private transfer state. Never serialize these rows into a public response."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import text


class YouTubeUploadRepository:
    FIELDS = frozenset({"session_url_encrypted", "confirmed_bytes", "bytes_started", "video_id", "stage",
        "reason_code", "actual_visibility", "next_attempt_at", "processing_started_at", "desired_publish_at", "confirmed_publish_at", "schedule_requested_at"})

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

    @staticmethod
    async def request_retry(db, post_id: str) -> None:
        await db.execute(text("""
            UPDATE youtube_uploads SET next_attempt_at=NOW(), reason_code=NULL,
                stage=CASE WHEN video_id IS NULL THEN 'uploading' ELSE 'processing' END,
                processing_started_at=CASE WHEN video_id IS NOT NULL THEN NOW() ELSE processing_started_at END
            WHERE post_id=:id AND (lease_expires_at IS NULL OR lease_expires_at < NOW())
        """), {"id": post_id})
        await db.commit()

    @staticmethod
    async def finish(db, post_id: str, token: str, account_id: str, visibility: str) -> bool:
        """Commit processing proof, publication and private-test receipt together."""
        row = (await db.execute(text("""
            UPDATE youtube_uploads SET stage='ready',actual_visibility=:privacy,
                lease_token=NULL,lease_expires_at=NULL,next_attempt_at=NULL,reason_code=NULL,updated_at=NOW()
            WHERE post_id=:id AND lease_token=:token AND lease_expires_at > NOW() AND video_id IS NOT NULL
            RETURNING video_id,user_id
        """), {"id": post_id, "token": token, "privacy": visibility})).mappings().first()
        if row is None:
            await db.rollback()
            return False
        result = await db.execute(text("""
            UPDATE social_posts SET status='published',external_post_id=:video,
                external_url=:url,pending_handle=NULL,error_message=NULL,published_at=NOW(),
                media_token_expires_at=NOW()+INTERVAL '1 hour',updated_at=NOW()
            WHERE id=:id AND status='publishing'
        """), {"id": post_id, "video": row["video_id"], "url": f"https://www.youtube.com/shorts/{row['video_id']}"})
        if result.rowcount != 1:
            await db.rollback()
            return False
        if visibility == "private":
            await db.execute(text("""
                UPDATE social_accounts SET metadata=COALESCE(metadata,'{}'::jsonb) ||
                    jsonb_build_object('youtube_private_test_completed_at',NOW())
                WHERE id=:account AND user_id=:user AND revoked_at IS NULL
            """), {"account": account_id, "user": row["user_id"]})
        await db.commit()
        return True

    @staticmethod
    async def native_finish(db, post_id, token, account_id, *, stage, status, visibility, publish_at=None, next_at=None):
        """Fence the checkpoint and publish truthful state together, honoring late cancellation."""
        post = (await db.execute(text("SELECT user_id,provider_options,clip_id FROM social_posts WHERE id=:id FOR UPDATE"), {"id": post_id})).mappings().first()
        if not post:
            await db.rollback()
            return False
        cancelling = post["provider_options"].get("cancel_requested") or post["clip_id"] is None
        if cancelling and status == "scheduled":
            stage, status, next_at = "cancelling", "publishing", datetime.now(timezone.utc)
        review_id = post["provider_options"].get("review", {}).get("id")
        if publish_at and review_id:
            updated = await db.execute(text("""
                UPDATE social_publication_slots s SET publish_at=:at
                WHERE review_id=:review AND NOT EXISTS (
                    SELECT 1 FROM social_publication_slots other WHERE other.account_id=s.account_id
                      AND other.publish_at=:at AND other.cancelled_at IS NULL AND other.review_id<>s.review_id)
            """), {"at":publish_at,"review":review_id})
            if updated.rowcount != 1:
                await db.rollback()
                raise ValueError("YouTube's schedule conflicts with another reservation")
        row = (await db.execute(text("""
            UPDATE youtube_uploads SET stage=:stage,actual_visibility=:privacy,confirmed_publish_at=:at,
              desired_publish_at=COALESCE(:at,desired_publish_at),
              next_attempt_at=:next,reason_code=NULL,lease_token=NULL,lease_expires_at=NULL,updated_at=NOW()
            WHERE post_id=:id AND lease_token=:token AND lease_expires_at>NOW() RETURNING video_id
        """), {"id": post_id,"token":token,"stage":stage,"privacy":visibility,"at":publish_at,"next":next_at})).mappings().first()
        if not row:
            await db.rollback()
            return False
        await db.execute(text("""
            UPDATE social_posts SET status=:status,scheduled_for=COALESCE(:at,scheduled_for),
              published_at=CASE WHEN CAST(:status AS VARCHAR)='published' THEN COALESCE(published_at,NOW()) ELSE published_at END,
              error_message=NULL,updated_at=NOW() WHERE id=:id
        """), {"id":post_id,"status":status,"at":publish_at})
        if visibility == "private" and row["video_id"]:
            await db.execute(text("UPDATE social_accounts SET metadata=metadata || jsonb_build_object('youtube_private_test_completed_at',NOW()) WHERE id=:id"), {"id":account_id})
        review_id = post["provider_options"].get("review", {}).get("id")
        if status == "cancelled" and review_id:
            await db.execute(text("UPDATE social_publication_slots SET cancelled_at=NOW() WHERE review_id=:id"), {"id":review_id})
            await db.execute(text("UPDATE social_review_items SET status='cancelled' WHERE id=:id"), {"id":review_id})
        await db.commit()
        return True

    @staticmethod
    async def defer_until(db, post_id, until):
        await db.execute(text("UPDATE youtube_uploads SET next_attempt_at=:at WHERE post_id=:id AND (lease_expires_at IS NULL OR lease_expires_at<NOW())"), {"id":post_id,"at":until})
        await db.commit()
