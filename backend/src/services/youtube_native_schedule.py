"""Reconcile native YouTube publication using an existing, privately uploaded ID."""
from datetime import datetime, timedelta, timezone
from sqlalchemy import text

from ..repositories.youtube_upload_repository import YouTubeUploadRepository as Uploads
from ..repositories.social_publication_policy_repository import SocialPublicationPolicyRepository as Policies
from ..runtime_settings import decrypt_setting_value
from ..social.youtube_upload import YouTubeUploadError
from ..utils.async_helpers import run_in_thread


def native(post):
    return post.get("provider_options", {}).get("native_schedule") is True


def withdrawing(post):
    return bool(post.get("provider_options", {}).get("cancel_requested") or post.get("clip_id") is None)


def deleting_source(post):
    return native(post) and bool(post.get("provider_options",{}).get("delete_remote") or post.get("clip_id") is None)


def parse_time(value):
    if not value:
        return None
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return result.astimezone(timezone.utc) if result.tzinfo else None
    except (TypeError, ValueError):
        return None


def mutable_status(status, publish_at=None):
    result = {key: status[key] for key in ("license", "embeddable", "publicStatsViewable", "selfDeclaredMadeForKids", "containsSyntheticMedia") if key in status}
    result["privacyStatus"] = "private"
    if publish_at:
        result["publishAt"] = publish_at.isoformat().replace("+00:00", "Z")
    return result


class YouTubeNativeSchedule:
    async def _paused(self, post):
        row = await Policies.get(self.db, post["user_id"], post["social_account_id"])
        await self.db.commit()
        return bool(row and row["policy"].get("uploads_paused"))

    async def _cancel_transfer(self, post, account, state):
        if not state:
            await self.social.repo.finish_unstarted_native_cancel(self.db, post["id"])
            return
        lease = await Uploads.claim(self.db, post["id"])
        if not lease:
            return
        try:
            if lease["bytes_started"]:
                token = await self.social._get_valid_access_token(account)
                await self.db.commit()
                uri = decrypt_setting_value(lease.get("session_url_encrypted"))
                if not uri:
                    raise YouTubeUploadError("The upload outcome needs review in YouTube Studio.", "missing_session", outcome_unknown=True)
                progress = await run_in_thread(self.provider.probe_upload, token, uri, lease["size_bytes"])
                if progress.video_id:
                    await self._accepted(post["id"], lease["lease_token"], progress)
                    await Uploads.defer_until(self.db, post["id"], datetime.now(timezone.utc))
                    return  # Next pass checks and cancels this same private video.
                if progress.confirmed_bytes == lease["size_bytes"]:
                    raise YouTubeUploadError("All bytes were accepted but the video ID is still unknown. Check YouTube before treating removal as complete.", "unknown_outcome", outcome_unknown=True)
            # An incomplete session cannot publish: initial upload never contains publishAt.
            await Uploads.native_finish(self.db, post["id"], lease["lease_token"], account["id"], stage="cancelled", status="cancelled", visibility="private")
        except Exception as exc:
            from ..social.base import SocialProviderError
            safe = exc if isinstance(exc, SocialProviderError) else YouTubeUploadError("Cancellation needs attention; check YouTube Studio.", "cancel_unknown", outcome_unknown=True)
            await self._failure(post, account, lease, safe)

    async def _delete_native_copy(self, post, account, lease, access_token, video):
        token = lease["lease_token"]
        if video:
            if (video.get("snippet") or {}).get("channelId") != account["external_account_id"]:
                raise YouTubeUploadError("The linked video's owner could not be confirmed. Check YouTube Studio.", "destination_mismatch", outcome_unknown=True)
            if not await Uploads.update(self.db,post["id"],token,stage="deleting"):
                return
            await run_in_thread(self.provider.delete_video,access_token,lease["video_id"])
            remaining = await run_in_thread(self.provider.fetch_video_status,access_token,lease["video_id"])
            if remaining:
                raise YouTubeUploadError("YouTube deletion is not confirmed. The linked video will be checked again.", "delete_unconfirmed", retryable=True)
        await Uploads.native_finish(self.db,post["id"],token,account["id"],stage="deleted",status="cancelled",visibility=None)

    async def _native_status(self, post, account, lease, access_token, video):
        token, identity = lease["lease_token"], post["id"]
        status = video.get("status") or {}
        visibility = status.get("privacyStatus")
        current = parse_time(status.get("publishAt"))
        now = datetime.now(timezone.utc)
        # Cancellation is read again after network I/O, including a concurrent library deletion.
        post = await self._post(identity)
        await self.db.commit()
        cancel = withdrawing(post)
        if visibility == "public":
            if not lease.get("schedule_requested_at") and not cancel:
                raise YouTubeUploadError("This video is already public. Review it in YouTube Studio.", "visibility_mismatch", outcome_unknown=True)
            await Uploads.native_finish(self.db, identity, token, account["id"], stage="ready", status="published", visibility="public")
            return
        if visibility != "private":
            raise YouTubeUploadError("YouTube visibility changed. Review the existing video in Studio.", "visibility_mismatch", outcome_unknown=True)
        if cancel:
            if current:
                if not await Uploads.update(self.db, identity, token, stage="cancelling"):
                    return
                await run_in_thread(self.provider.update_video_status, access_token, lease["video_id"], mutable_status(status))
                checked = await run_in_thread(self.provider.fetch_video_status, access_token, lease["video_id"])
                checked_status = checked.get("status") or {}
                if checked_status.get("privacyStatus") == "public":
                    await Uploads.native_finish(self.db, identity, token, account["id"], stage="ready", status="published", visibility="public")
                    return
                if checked_status.get("privacyStatus") != "private" or checked_status.get("publishAt"):
                    raise YouTubeUploadError("Cancellation is not confirmed. The YouTube schedule may still be active; check Studio.", "cancel_unconfirmed", retryable=True)
            await Uploads.native_finish(self.db, identity, token, account["id"], stage="cancelled", status="cancelled", visibility="private")
            return
        desired = lease.get("desired_publish_at")
        confirmed = lease.get("confirmed_publish_at")
        if current and current < now-timedelta(minutes=20):
            raise YouTubeUploadError("YouTube has not published this overdue video. Check its schedule and restrictions in Studio.", "publication_delayed", outcome_unknown=True)
        if current and (current == desired or (confirmed and desired == confirmed)):
            # Respect a later schedule edited directly in Studio; never overwrite it blindly.
            await Uploads.native_finish(self.db, identity, token, account["id"], stage="youtube_scheduled", status="scheduled", visibility="private",
                publish_at=current, next_at=max(now + timedelta(minutes=2), current + timedelta(seconds=60)))
            return
        if confirmed and not current:
            raise YouTubeUploadError("The confirmed YouTube schedule was removed. Review this private video in Studio.", "schedule_removed", outcome_unknown=True)
        if await self._paused(post):
            await Uploads.update(self.db, identity, token, release=True, stage="paused", next_attempt_at=now+timedelta(minutes=1))
            return
        from .social_publication_policy import NATIVE_SCOPE, PUBLICATION_LEAD
        if NATIVE_SCOPE not in (account.get("scopes") or "").split():
            raise YouTubeUploadError("Reconnect YouTube to allow schedule management.", "reconnect_required", reauth=True)
        if desired is None or desired < now + PUBLICATION_LEAD:
            review = post.get("provider_options", {}).get("review", {}).get("id")
            if not review:
                raise YouTubeUploadError("This schedule has no approval receipt.", "missing_approval", outcome_unknown=True)
            desired = await Policies.reserve(self.db, review, now, move_if_late=True,
                approved_pattern=post["provider_options"].get("approved_pattern"))
            await self.social.repo.update_post(self.db, identity, scheduled_for=desired)
        if not await Uploads.update(self.db, identity, token, desired_publish_at=desired, schedule_requested_at=now, stage="scheduling"):
            return
        # Recheck withdrawal immediately before setting a future public schedule.
        latest = await self._post(identity)
        await self.db.commit()
        if withdrawing(latest):
            await Uploads.update(self.db, identity, token, release=True, stage="cancelling", next_attempt_at=now)
            return
        await run_in_thread(self.provider.update_video_status, access_token, lease["video_id"], mutable_status(status, desired))
        checked = await run_in_thread(self.provider.fetch_video_status, access_token, lease["video_id"])
        actual = checked.get("status") or {}
        if actual.get("privacyStatus") != "private" or parse_time(actual.get("publishAt")) != desired:
            raise YouTubeUploadError("YouTube has not confirmed this publication time. The existing video will be checked again.", "schedule_unconfirmed", retryable=True)
        await Uploads.native_finish(self.db, identity, token, account["id"], stage="youtube_scheduled", status="scheduled", visibility="private",
            publish_at=desired, next_at=desired+timedelta(seconds=60))
