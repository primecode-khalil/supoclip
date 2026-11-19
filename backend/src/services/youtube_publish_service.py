"""Durable YouTube uploads. Database checkpoints never span a network call."""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..repositories.youtube_upload_repository import YouTubeUploadRepository as Uploads
from ..runtime_settings import decrypt_setting_value, encrypt_setting_value
from ..social.base import PublishRequest, SocialProviderError
from ..social.youtube_metadata import build_youtube_metadata
from ..social.youtube_upload import YouTubeUploadError, UploadProgress
from ..utils.async_helpers import run_in_thread


def _identity(path: str) -> tuple[str, int]:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest(), Path(path).stat().st_size


class YouTubePublishService:
    def __init__(self, social_service, provider):
        self.social = social_service
        self.db = social_service.db
        self.provider = provider

    async def _post(self, identity: str) -> dict:
        return await self.social.repo.get_post(self.db, identity) or {}

    async def advance(self, post_id: str) -> dict:
        post = await self._post(post_id)
        if not post or post.get("provider") != "youtube":
            return post
        if post["status"] not in {"queued", "publishing"}:
            return post
        state = await Uploads.get(self.db, post_id)
        if state and state["stage"] in {"ready", "needs_attention", "reconnect_required"} and post["status"] != "queued":
            return post
        if post["status"] == "queued":
            post = await self.social.repo.claim_post(self.db, post_id,
                media_token_expires_at=datetime.now(timezone.utc) + timedelta(hours=3))
            if not post:
                return await self._post(post_id)
        # Opaque identity keeps ordinary stale-upload recovery from resubmitting.
        await self.social.repo.update_post(self.db, post_id, pending_handle=f"youtube:{post_id}")
        account = await self.social.repo.get_account_with_tokens(self.db, post.get("social_account_id"))
        if not account or account.get("user_id") != post["user_id"] or account.get("revoked_at"):
            await self.social.repo.update_post(self.db, post_id, status="failed", error_message="Reconnect the destination YouTube account.")
            return await self._post(post_id)

        # An accepted video never requires the original file for reconciliation.
        if state and state.get("video_id"):
            await self.db.commit()
            return await self._post(post_id)
        try:
            await self.db.commit()
            file_path, _ = await self.social._resolve_publish_media(post, self.provider)
            digest, size = await run_in_thread(_identity, file_path)
            metadata = build_youtube_metadata(PublishRequest(
                file_path=file_path, title=post.get("title") or "", caption=post.get("caption") or "",
                hashtags=list(post.get("hashtags") or []), privacy_level=post.get("privacy_level") or "private",
                provider_options=post.get("provider_options") or {},
            ))
            await Uploads.ensure(self.db, post_id, post["user_id"], digest, size, metadata)
        except (SocialProviderError, OSError) as exc:
            await self.social.repo.update_post(self.db, post_id, status="failed", error_message=str(exc) if isinstance(exc, SocialProviderError) else "The clip file is unavailable.")
            return await self._post(post_id)
        lease = await Uploads.claim(self.db, post_id)
        if not lease:
            return await self._post(post_id)
        token = lease["lease_token"]
        try:
            if digest != lease["media_sha256"] or size != lease["size_bytes"]:
                raise YouTubeUploadError("The clip changed after upload began. The original session has been retained.", "media_changed", outcome_unknown=True)
            if not await self.social.has_access(post["user_id"]):
                raise YouTubeUploadError("Publishing is disabled for this account.", "publishing_disabled")
            await self.social._ensure_not_paused("youtube", post["user_id"], any_platform=True)
            access_token = await self.social._get_valid_access_token(account)
            await self.db.commit()
            uri = decrypt_setting_value(lease["session_url_encrypted"]) if lease.get("session_url_encrypted") else None
            if not uri:
                uri = await run_in_thread(self.provider.start_upload, access_token, lease["metadata_snapshot"], size)
                if not await Uploads.update(self.db, post_id, token, session_url_encrypted=encrypt_setting_value(uri), stage="uploading"):
                    return await self._post(post_id)
            offset = 0
            if lease["bytes_started"]:
                progress = await run_in_thread(self.provider.probe_upload, access_token, uri, size)
                if progress.video_id:
                    await self._accepted(post_id, token, progress)
                    return await self._post(post_id)
                offset = progress.confirmed_bytes
                if not await Uploads.update(self.db, post_id, token, confirmed_bytes=offset, stage="uploading"):
                    return await self._post(post_id)
            # Commit before bytes: even a lost response must resume this session.
            if not await Uploads.update(self.db, post_id, token, bytes_started=True, stage="uploading"):
                return await self._post(post_id)
            progress = await run_in_thread(self.provider.send_upload, access_token, uri, file_path, offset)
            await self._accepted(post_id, token, progress)
        except SocialProviderError as exc:
            await self._failure(post, account, lease, exc)
        except Exception:
            # Encryption/configuration/storage errors must not include private URI data.
            await self._failure(post, account, lease, YouTubeUploadError("The saved upload needs attention. Its checkpoint has been retained.", "checkpoint_error", outcome_unknown=True))
        return await self._post(post_id)

    async def _accepted(self, post_id: str, token: str, progress: UploadProgress) -> None:
        fields = {"confirmed_bytes": progress.confirmed_bytes, "reason_code": None,
            "stage": "processing" if progress.video_id else "uploading",
            "next_attempt_at": datetime.now(timezone.utc) + timedelta(seconds=30)}
        if progress.video_id:
            fields.update(video_id=progress.video_id, processing_started_at=datetime.now(timezone.utc))
        if await Uploads.update(self.db, post_id, token, release=True, **fields) and progress.video_id:
            await self.social.repo.update_post(self.db, post_id, external_post_id=progress.video_id,
                external_url=f"https://www.youtube.com/shorts/{progress.video_id}", status="publishing", error_message=None)

    async def _failure(self, post: dict, account: dict, lease: dict, exc: SocialProviderError) -> None:
        reason = getattr(exc, "reason_code", "temporary" if exc.retryable else "rejected")
        stage, status, next_at = "needs_attention", "failed", None
        if exc.reauth:
            stage = "reconnect_required"
        elif exc.retryable and not exc.outcome_unknown:
            stage = "waiting_for_quota" if reason in {"project_quota", "channel_quota"} else "uploading"
            status = "publishing"
            delay = 3600 if stage == "waiting_for_quota" else min(300, 30 * 2 ** min(lease["attempts"], 3))
            next_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
        if await Uploads.update(self.db, post["id"], lease["lease_token"], stage=stage,
                reason_code=reason, next_attempt_at=next_at, release=True):
            if exc.reauth:
                await self.social.repo.set_account_status(self.db, account["id"], "reauth_required", "Reconnect YouTube to restore access.")
            await self.social.repo.update_post(self.db, post["id"], status=status, error_message=str(exc))
