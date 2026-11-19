"""Owner-scoped review receipts remain after the library video is removed."""
from __future__ import annotations

import hashlib
from uuid import uuid4

from sqlalchemy import text
from ..publishing_tags import ground_youtube_tags, normalize_youtube_tags

_SELECT = """
    SELECT r.*,c.file_path AS current_file_path,c.updated_at AS clip_updated_at,
        c.created_at AS clip_created_at,c.hook_title,c.text AS caption,c.virality_score,
        c.duration,c.workflow_meta,s.title AS source_title,p.status AS post_status,p.scheduled_for,
        p.provider_options AS post_options,
        p.external_url,slot.publish_at
    FROM social_review_items r
    LEFT JOIN generated_clips c ON c.id=r.clip_id
    LEFT JOIN tasks t ON t.id=c.task_id AND t.user_id=r.user_id
    LEFT JOIN sources s ON s.id=t.source_id
    LEFT JOIN social_posts p ON p.id=r.post_id
    LEFT JOIN social_publication_slots slot ON slot.review_id=r.id
"""


def render_version(clip_id: str, reference: str, updated_at) -> str:
    return hashlib.sha256(f"{clip_id}\n{reference}\n{updated_at}".encode()).hexdigest()


class SocialReviewRepository:
    @staticmethod
    async def add(db, user_id: str, account_id: str, task_id: str, clip_id: str,
                  version: str, reference: str, *, source_key: str | None = None, commit: bool = True) -> dict | None:
        result = await db.execute(text("""
            INSERT INTO social_review_items(id,user_id,account_id,task_id,clip_id,render_version,source_file_path,source_key)
            SELECT :id,t.user_id,a.id,t.id,c.id,:version,:reference,:source
            FROM generated_clips c JOIN tasks t ON t.id=c.task_id
            JOIN social_accounts a ON a.id=:account AND a.user_id=t.user_id AND a.provider='youtube'
            WHERE c.id=:clip AND t.id=:task AND t.user_id=:user
            ON CONFLICT(user_id,account_id,clip_id) DO NOTHING
            RETURNING id
        """), {"id": str(uuid4()), "user": user_id, "account": account_id, "task": task_id,
               "clip": clip_id, "version": version, "reference": reference, "source": source_key})
        identity = result.scalar_one_or_none()
        if identity is None:
            identity = (await db.execute(text("SELECT id FROM social_review_items WHERE user_id=:user AND account_id=:account AND clip_id=:clip"),
                {"user": user_id, "account": account_id, "clip": clip_id})).scalar_one_or_none()
        if commit:
            await db.commit()
        return await SocialReviewRepository.get(db, user_id, identity) if identity else None

    @staticmethod
    async def get(db, user_id: str, identity: str) -> dict | None:
        row = (await db.execute(text(_SELECT + " WHERE r.id=:id AND r.user_id=:user"), {"id": identity, "user": user_id})).mappings().first()
        return dict(row) if row else None

    @staticmethod
    async def lock(db, user_id: str, identity: str) -> dict | None:
        row = (await db.execute(text("SELECT * FROM social_review_items WHERE id=:id AND user_id=:user FOR UPDATE"),
            {"id": identity, "user": user_id})).mappings().first()
        return dict(row) if row else None

    @staticmethod
    async def list(db, user_id: str, account_id: str, status: str = "pending", limit: int = 50) -> list[dict]:
        rows = (await db.execute(text(_SELECT + """
            WHERE r.user_id=:user AND r.account_id=:account AND r.status=:status
              AND (:status <> 'pending' OR (r.clip_id IS NOT NULL AND t.id IS NOT NULL))
            ORDER BY r.created_at,r.id LIMIT :limit
        """), {"user": user_id, "account": account_id, "status": status, "limit": limit})).mappings().all()
        return [dict(row) for row in rows]

    @staticmethod
    def present(row: dict) -> dict:
        current = row.get("current_file_path")
        version = render_version(row["clip_id"], current, row.get("clip_updated_at")) if current and row.get("clip_id") else row["render_version"]
        options = row.get("post_options") or {}
        tags = normalize_youtube_tags(options["youtube_tags"]) if "youtube_tags" in options else ground_youtube_tags(
            (row.get("workflow_meta") or {}).get("youtube_tags"), row.get("caption") or "")
        return {
            "id": row["id"], "account_id": row["account_id"], "task_id": row.get("task_id"), "clip_id": row.get("clip_id"),
            "status": row["status"], "post_id": row.get("post_id"), "post_status": row.get("post_status"),
            "version": version, "title": row.get("hook_title") or row.get("source_title") or "Untitled clip",
            "caption": row.get("caption") or "", "youtube_tags": tags, "score": row.get("virality_score"), "duration": row.get("duration"),
            "source_title": row.get("source_title"), "external_url": row.get("external_url"),
            "publish_at": row["publish_at"].isoformat() if row.get("publish_at") else None,
            "video_url": f"/api/tasks/{row['task_id']}/clips/{row['clip_id']}/file?v={version}" if current and row.get("task_id") else None,
            "created_at": row["created_at"].isoformat(),
        }
