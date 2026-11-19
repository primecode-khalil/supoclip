"""A review decision atomically binds one approved render, post and time slot."""
from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from ..media_storage import media_work, is_s3
from ..repositories.social_publication_policy_repository import SocialPublicationPolicyRepository as Policies
from ..repositories.social_review_repository import SocialReviewRepository as Reviews, render_version
from ..utils.async_helpers import run_in_thread
from .social_publication_policy import PublishingPolicy, SocialPublicationPolicyService, NATIVE_SCOPE, validate_youtube_short
from .social_service import SocialError, SocialNotFound, SocialValidationError
from .youtube_publish_service import _identity


class ReviewConflict(SocialError):
    status_code = 409


class ReviewImport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account_id: str = Field(min_length=1, max_length=36)
    clip_ids: list[str] = Field(default_factory=list, max_length=200)
    limit: int = Field(default=20, ge=1, le=200)


class ReviewCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account_id: str = Field(min_length=1, max_length=36)
    task_id: str = Field(min_length=1, max_length=36)
    clip_id: str = Field(min_length=1, max_length=36)


class ReviewApproval(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: str = Field(pattern=r"^[a-f0-9]{64}$")
    title: str | None = Field(default=None, max_length=100)
    caption: str | None = Field(default=None, max_length=2200)
    hashtags: list[str] | None = Field(default=None, max_length=30)
    custom_local: str | None = Field(default=None, max_length=32)


class SocialReviewService:
    def __init__(self, social_service):
        self.social = social_service
        self.db = social_service.db
        self.policies = SocialPublicationPolicyService(self.db)

    async def list(self, user_id: str, account_id: str, status="pending", limit=50) -> dict:
        await self.policies.account(user_id, account_id)
        rows = await Reviews.list(self.db, user_id, account_id, status, limit)
        return {"items": [Reviews.present(row) for row in rows], "settings": await self.policies.get(user_id, account_id)}

    async def import_clips(self, user_id: str, body: ReviewImport) -> dict:
        await self.policies.account(user_id, body.account_id)
        settings = await self.policies.get(user_id, body.account_id)
        if settings["legacy"]:
            # Import is an explicit adoption of the review workflow, never an upload.
            await self.policies.save(user_id, body.account_id, {})
        if body.clip_ids:
            rows = (await self.db.execute(text("""
                SELECT c.id,c.task_id FROM generated_clips c JOIN tasks t ON t.id=c.task_id
                WHERE t.user_id=:user AND c.id=ANY(CAST(:ids AS VARCHAR[]))
                ORDER BY c.created_at,c.id
            """), {"user": user_id, "ids": list(dict.fromkeys(body.clip_ids))})).mappings().all()
        else:
            rows = (await self.db.execute(text("""
                SELECT c.id,c.task_id FROM generated_clips c JOIN tasks t ON t.id=c.task_id
                WHERE t.user_id=:user AND t.status='completed'
                ORDER BY c.created_at DESC,c.id LIMIT :limit
            """), {"user": user_id, "limit": body.limit})).mappings().all()
        await self.db.commit()
        added = 0
        for row in rows:
            result = await self.candidate(user_id, body.account_id, row["task_id"], row["id"], manual=True)
            added += bool(result.get("added"))
        return {"added": added, **await self.list(user_id, body.account_id)}

    async def candidate(self, user_id: str, account_id: str, task_id: str, clip_id: str, *, manual=False) -> dict:
        account = await self.policies.account(user_id, account_id)
        task = await self.social.task_repo.get_task_by_id(self.db, task_id)
        clip = await self.social.clip_repo.get_clip_by_id(self.db, clip_id)
        if not task or task.get("user_id") != user_id or not clip or clip.get("task_id") != task_id:
            raise SocialNotFound("Clip not found")
        policy_row = await Policies.get(self.db, user_id, account_id)
        policy = PublishingPolicy.model_validate(policy_row["policy"] if policy_row else {})
        source_key = None
        if not manual:
            metadata = await self.social.task_repo.load_source_metadata(self.db, task_id)
            source_key = metadata.get("recording_window_id")
            if not source_key:
                return {"skipped": True, "reason": "not_a_recording"}
            window = (await self.db.execute(text("""
                SELECT w.metadata,a.policy FROM recording_windows w
                JOIN recording_channels c ON c.id=w.channel_id
                JOIN recording_automation a ON a.channel_id=c.id
                WHERE w.id=:id AND w.task_id=:task AND c.user_id=:user
            """), {"id": source_key, "task": task_id, "user": user_id})).mappings().first()
            if (not policy.enabled or not window or window["metadata"].get("history_cleared") is True
                    or not window["policy"].get("enabled") or account_id not in window["policy"].get("social_account_ids", [])):
                return {"skipped": True, "reason": "intake_disabled"}
            created = datetime.fromisoformat(clip["created_at"])
            if policy_row and policy_row["enabled_at"] and created < policy_row["enabled_at"]:
                return {"skipped": True, "reason": "before_intake_enabled"}
            if float(clip.get("virality_score") or 0) < max(policy.min_score, float(window["policy"].get("min_score", 75))):
                return {"skipped": True, "reason": "below_score"}
        await self.db.commit()
        async with self.db.begin():
            if not await Policies.lock_account(self.db, user_id, account_id):
                raise SocialNotFound("YouTube account was disconnected")
            previous = (await self.db.execute(text("SELECT id FROM social_review_items WHERE user_id=:user AND account_id=:account AND clip_id=:clip"),
                {"user": user_id, "account": account_id, "clip": clip_id})).scalar_one_or_none()
            if previous:
                return {"item": Reviews.present(await Reviews.get(self.db, user_id, previous)), "added": False}
            count = (await self.db.execute(text("SELECT count(*) FROM social_review_items WHERE user_id=:user AND account_id=:account AND status='pending' AND clip_id IS NOT NULL"),
                {"user": user_id, "account": account_id})).scalar_one()
            if count >= 200:
                return {"skipped": True, "reason": "review_queue_full"}
            updated = (await self.db.execute(text("SELECT updated_at FROM generated_clips WHERE id=:id"), {"id": clip_id})).scalar_one()
            version = render_version(clip_id, clip["file_path"], updated)
            row = await Reviews.add(self.db, user_id, account_id, task_id, clip_id, version, clip["file_path"], source_key=source_key, commit=False)
        if not manual and policy.mode == "automatic" and not policy.uploads_paused and account.get("status") == "active":
            pending = (await self.db.execute(text("SELECT count(*) FROM social_review_items r JOIN social_posts p ON p.id=r.post_id WHERE r.account_id=:account AND r.user_id=:user AND p.status IN ('queued','publishing','scheduled')"),
                {"account": account_id, "user": user_id})).scalar_one()
            await self.db.commit()
            if pending < 9:
                try:
                    return {"added": True, **await self.approve(user_id, row["id"], ReviewApproval(expected_version=version), automatic=True)}
                except SocialError:
                    pass  # Keep the candidate for review/reconnection; never lose the clip.
        return {"item": Reviews.present(row), "added": True}

    async def _response(self, user_id: str, identity: str) -> dict:
        row = await Reviews.get(self.db, user_id, identity)
        if not row:
            raise SocialNotFound("Review item not found")
        post = await self.social.repo.get_user_post(self.db, user_id, row["post_id"]) if row.get("post_id") else None
        return {"item": Reviews.present(row), "post": post, "settings": await self.policies.get(user_id, row["account_id"])}

    @media_work
    async def approve(self, user_id: str, identity: str, body: ReviewApproval, *, automatic=False) -> dict:
        row = await Reviews.get(self.db, user_id, identity)
        if not row:
            raise SocialNotFound("Review item not found")
        if row["status"] == "approved":
            return await self._response(user_id, identity)
        if row["status"] != "pending":
            raise ReviewConflict("Restore this rejected item to review before approving it.")
        account = await self.policies.account(user_id, row["account_id"])
        if NATIVE_SCOPE not in (account.get("scopes") or "").split():
            raise SocialValidationError("Reconnect YouTube to allow native schedule management.")
        settings = await self.policies.get(user_id, row["account_id"])
        policy = PublishingPolicy.model_validate(settings["policy"])
        if policy.uploads_paused:
            raise ReviewConflict("Uploads are paused. Your clip remains in review.")
        if automatic and (policy.mode != "automatic" or not policy.enabled or not settings["private_test_completed"]):
            raise ReviewConflict("Automatic approval is not enabled.")
        if not row.get("current_file_path") or not row.get("clip_id") or not row.get("task_id"):
            raise SocialNotFound("The reviewed clip was deleted or expired.")
        current_version = render_version(row["clip_id"], row["current_file_path"], row["clip_updated_at"])
        if current_version != body.expected_version:
            raise ReviewConflict("This video changed. Reload and review its current render.")
        reference = row["current_file_path"]
        await self.db.commit()
        local = str(await run_in_thread(self.social.storage.local_path, reference)) if is_s3(reference) else reference
        try:
            await run_in_thread(validate_youtube_short, local)
            digest, size = await run_in_thread(_identity, local)
        except (ValueError, OSError) as exc:
            raise SocialValidationError(str(exc) if isinstance(exc, ValueError) else "The reviewed video is unavailable.") from None
        async with self.db.begin():
            if not await Policies.lock_account(self.db, user_id, row["account_id"]):
                raise ReviewConflict("The destination was disconnected.")
            locked = await Reviews.lock(self.db, user_id, identity)
            if not locked:
                raise SocialNotFound("Review item not found")
            if locked["status"] == "approved":
                return await self._response(user_id, identity)
            if locked["status"] != "pending":
                raise ReviewConflict("This item was already rejected or removed.")
            fresh = await Reviews.get(self.db, user_id, identity)
            if render_version(fresh["clip_id"], fresh.get("current_file_path") or "", fresh.get("clip_updated_at")) != body.expected_version:
                raise ReviewConflict("This video changed while approval was being saved. Review it again.")
            latest = await self.policies.get(user_id, row["account_id"])
            policy = PublishingPolicy.model_validate(latest["policy"])
            if policy.uploads_paused or (automatic and (policy.mode != "automatic" or not policy.enabled)):
                raise ReviewConflict("Publishing settings changed; the clip remains in review.")
            if automatic:
                pending = (await self.db.execute(text("""
                    SELECT count(*) FROM social_review_items r JOIN social_posts p ON p.id=r.post_id
                    WHERE r.account_id=:account AND r.user_id=:user AND p.status IN ('queued','publishing','scheduled')
                """), {"account": row["account_id"], "user": user_id})).scalar_one()
                if pending >= 9 or not latest["private_test_completed"] or not latest["permissions_complete"]:
                    raise ReviewConflict("Automatic approval is waiting; this clip remains available for review.")
            now = (await self.db.execute(text("SELECT clock_timestamp()"))).scalar_one()
            try:
                slot = await Policies.reserve(self.db, identity, now, custom_local=body.custom_local, commit=False)
            except ValueError as exc:
                raise SocialValidationError(str(exc)) from None
            options = {"native_schedule": True, "category_id": policy.category_id,
                "made_for_kids": policy.made_for_kids, "contains_synthetic_media": policy.contains_synthetic_media,
                "approved_pattern": {"schedule": policy.schedule.model_dump(mode="json"), "timezone": policy.timezone},
                "review": {"id": identity, "origin_clip_id": row["clip_id"], "version": body.expected_version, "sha256": digest, "size_bytes": size, "automatic": automatic}}
            post = await self.social.create_post(user_id, task_id=row["task_id"], clip_id=row["clip_id"], social_account_id=row["account_id"],
                title=body.title, caption=body.caption, hashtags=body.hashtags, privacy_level="public", scheduled_for=slot.isoformat(),
                provider_options=options, transactional=True, verified_media=True,
                request_key=f"review:{identity}", request_hash=body.expected_version)
            await self.db.execute(text("""
                UPDATE social_review_items SET status='approved',post_id=:post,decided_at=NOW(),
                    render_version=:version,source_file_path=:reference,media_sha256=:digest WHERE id=:id AND user_id=:user
            """), {"id": identity, "user": user_id, "post": post["id"], "version": body.expected_version,
                "reference": reference, "digest": digest})
        await self.social._enqueue_or_fail(post["id"], 0)
        return await self._response(user_id, identity)

    async def decide(self, user_id: str, identity: str, *, undo=False) -> dict:
        row = await Reviews.get(self.db, user_id, identity)
        if not row:
            raise SocialNotFound("Review item not found")
        await self.db.commit()
        async with self.db.begin():
            if not await Policies.lock_account(self.db, user_id, row["account_id"]):
                raise SocialNotFound("Connected account not found")
            locked = await Reviews.lock(self.db, user_id, identity)
            if locked["status"] == "approved":
                raise ReviewConflict("This item is already approved. Cancel its schedule in the queue instead.")
            if undo and (locked["status"] != "rejected" or not locked.get("clip_id")):
                raise ReviewConflict("Only an existing rejected clip can return to review.")
            await self.db.execute(text("UPDATE social_review_items SET status=:status,decided_at=NOW() WHERE id=:id AND user_id=:user"),
                {"status": "pending" if undo else "rejected", "id": identity, "user": user_id})
        return {"item": Reviews.present(await Reviews.get(self.db, user_id, identity))}
