"""Durable YouTube uploads. Database checkpoints never span a network call."""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..repositories.youtube_upload_repository import YouTubeUploadRepository as Uploads
from ..runtime_settings import decrypt_setting_value, encrypt_setting_value
from ..media_storage import media_work
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

    @media_work
    async def advance(self, post_id: str) -> dict:
        post = await self._post(post_id)
        if not post or post.get("provider") != "youtube":
            return post
        if post["status"] not in {"queued", "publishing"}:
            return post
        state = await Uploads.get(self.db, post_id)
        if post["status"] == "publishing" and not state and post.get("pending_handle") != f"youtube:{post_id}":
            # An older worker may have uploaded without any recoverable session.
            # Never turn that unknown outcome into a new upload automatically.
            return post
        if state and state["stage"] in {"ready", "needs_attention", "reconnect_required"} and post["status"] != "queued":
            return post
        if post["status"] == "queued":
            post = await self.social.repo.claim_post(self.db, post_id,
                media_token_expires_at=datetime.now(timezone.utc) + timedelta(hours=3), upload_handle=f"youtube:{post_id}")
            if not post:
                return await self._post(post_id)
        account = await self.social.repo.get_account_with_tokens(self.db, post.get("social_account_id"))
        if not account or account.get("user_id") != post["user_id"] or account.get("revoked_at"):
            if state:
                lease = await Uploads.claim(self.db, post_id)
                if not lease:
                    return await self._post(post_id)
                if not await Uploads.update(self.db, post_id, lease["lease_token"], release=True,
                        stage="reconnect_required", reason_code="account_removed", next_attempt_at=None):
                    return await self._post(post_id)
            await self.social.repo.update_post(self.db, post_id, status="failed", error_message="Reconnect the destination YouTube account.")
            return await self._post(post_id)

        # An accepted video never requires the original file for reconciliation.
        if state and state.get("video_id"):
            await self.db.commit()
            await self._processing(post, account)
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
            if "youtube" not in self.social.config.social_publishing_providers or not self.provider.is_configured:
                raise YouTubeUploadError("YouTube publishing is not configured or has been disabled.", "publishing_disabled")
            await self.social._ensure_not_paused("youtube", post["user_id"], any_platform=True)
            access_token = await self.social._get_valid_access_token(account)
            await self.db.commit()
            uri = decrypt_setting_value(lease["session_url_encrypted"]) if lease.get("session_url_encrypted") else None
            if lease["bytes_started"] and not uri:
                raise YouTubeUploadError("This upload lost its session. Check YouTube before creating another post.", "missing_session", outcome_unknown=True)
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
        if exc.reauth and account.get("refresh_token_encrypted") and lease.get("reason_code") != "refresh_retry":
            # Fence before touching credentials: a stale worker cannot revoke or
            # refresh a connection already being used by its replacement.
            if not await Uploads.update(self.db, post["id"], lease["lease_token"], reason_code="refresh_retry"):
                return
            try:
                await self.db.commit()
                await self.social._get_valid_access_token({**account,
                    "token_expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)})
            except SocialProviderError as refresh_error:
                exc = refresh_error
            else:
                stage = "processing" if lease.get("video_id") else "uploading"
                if await Uploads.update(self.db, post["id"], lease["lease_token"], release=True,
                        stage=stage, reason_code="refresh_retry", next_attempt_at=datetime.now(timezone.utc)):
                    await self.social.repo.update_post(self.db, post["id"], status="publishing", error_message="YouTube access refreshed; resuming the saved upload.")
                return
        reason = getattr(exc, "reason_code", "temporary" if exc.retryable else "rejected")
        stage, status, next_at = "needs_attention", "failed", None
        if exc.reauth:
            stage = "reconnect_required"
        elif exc.retryable and not exc.outcome_unknown:
            stage = "waiting_for_quota" if reason in {"project_quota", "channel_quota"} else "processing" if lease.get("video_id") else "uploading"
            status = "publishing"
            delay = 3600 if stage == "waiting_for_quota" else min(300, 30 * 2 ** min(lease["attempts"], 3))
            next_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
        if await Uploads.update(self.db, post["id"], lease["lease_token"], stage=stage,
                reason_code=reason, next_attempt_at=next_at, release=True):
            if exc.reauth:
                await self.social.repo.set_account_status(self.db, account["id"], "reauth_required", "Reconnect YouTube to restore access.")
            await self.social.repo.update_post(self.db, post["id"], status=status, error_message=str(exc))

    async def _processing(self, post: dict, account: dict) -> None:
        lease = await Uploads.claim(self.db, post["id"])
        if not lease:
            return
        token = lease["lease_token"]
        try:
            started = lease.get("processing_started_at") or lease["created_at"]
            if datetime.now(timezone.utc) - started > timedelta(hours=6):
                raise YouTubeUploadError("YouTube processing could not be confirmed within six hours. Retry to check the same video again.", "processing_timeout", outcome_unknown=True)
            access_token = await self.social._get_valid_access_token(account)
            await self.db.commit()
            video = await run_in_thread(self.provider.fetch_video_status, access_token, lease["video_id"])
            status = video.get("status") or {}
            processing = video.get("processingDetails") or {}
            if status.get("uploadStatus") in {"failed", "rejected", "deleted"} or processing.get("processingStatus") in {"failed", "terminated"}:
                raise YouTubeUploadError("YouTube could not process this video. The accepted upload has been retained for review.", "processing_rejected", rejected=True)
            if status.get("uploadStatus") != "processed" or processing.get("processingStatus") == "processing":
                await Uploads.update(self.db, post["id"], token, release=True, stage="processing",
                    reason_code=None, next_attempt_at=datetime.now(timezone.utc) + timedelta(seconds=30))
                return
            if (video.get("snippet") or {}).get("channelId") != account["external_account_id"]:
                raise YouTubeUploadError("The uploaded video's destination could not be confirmed. Check the connected channel.", "destination_mismatch", outcome_unknown=True)
            visibility = status.get("privacyStatus")
            if visibility != lease["metadata_snapshot"]["status"]["privacyStatus"]:
                await Uploads.update(self.db, post["id"], token, actual_visibility=visibility)
                raise YouTubeUploadError("YouTube's visibility differs from the requested setting. Review the existing video before retrying.", "visibility_mismatch", outcome_unknown=True)
            if await Uploads.finish(self.db, post["id"], token, account["id"], visibility):
                from ..analytics import capture_event
                capture_event("social_post_published", post["user_id"], {"post_id": post["id"], "provider": "youtube"})
        except SocialProviderError as exc:
            await self._failure(post, account, lease, exc)
        except Exception:
            await self._failure(post, account, lease, YouTubeUploadError("The video's saved processing status needs attention.", "checkpoint_error", outcome_unknown=True))
