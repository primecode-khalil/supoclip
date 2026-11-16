"""Restartable work stages using the existing upload, render and social APIs."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re

from sqlalchemy import text

from ..database import AsyncSessionLocal
from ..source_identity import source_admission_lock
from .automation_schema import AutomationPolicy
from .automation_store import AutomationStore, LostLeaseError
from .capture import _terminate
from .pipeline import NativeClient, PipelineBlocked, PipelineRetry, choose_clips, contained_path, retry_delay, overlaps_reserved, _seconds


class PublicationLimitReached(Exception):
    """Stop automatic selection; existing receipts still need monitoring."""


async def store_call(method: str, *args, **kwargs):
    async with AsyncSessionLocal() as db:
        return await getattr(AutomationStore(db), method)(*args, **kwargs)


def _digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


class AutomationPipeline:
    def __init__(self, root: Path, native: NativeClient, *, archive_remote: str = ""):
        self.root, self.native, self.archive_remote = root.resolve(), native, archive_remote

    async def _live(self, token):
        if await store_call("renew", token) is None:
            raise LostLeaseError()

    async def _update(self, token, window, **values):
        return await store_call("update_window", token, window.id, **values)

    async def _archive(self, token, window, details: dict):
        if details.get("archived"):
            return
        if not re.fullmatch(r"[A-Za-z0-9_-]+:[A-Za-z0-9_./-]*", self.archive_remote) or ".." in self.archive_remote.split("/"):
            raise PipelineBlocked("Configure a server-owned RECORDING_ARCHIVE_REMOTE before enabling archives")
        references = [window.source_path]
        sidecar = contained_path(self.root, window.source_path + ".json")
        if sidecar.exists():
            references.append(window.source_path + ".json")
        references += [segment["path"] for segment in details.get("segments", [])]
        for segment in details.get("segments", []):
            original = contained_path(self.root, segment["path"])
            if not original.is_file() or original.stat().st_size != segment["size_bytes"] or await asyncio.to_thread(_digest, original) != segment["sha256"]:
                raise PipelineBlocked("An original segment changed; restore its recorded checksum before archiving")
        for reference in dict.fromkeys(references):
            await self._live(token)
            path = contained_path(self.root, reference)
            destination = self.archive_remote.rstrip("/") + "/" + reference
            process = await asyncio.create_subprocess_exec(
                "rclone", "copyto", str(path), destination, "--immutable", "--checksum",
                "--retries", "2", "--low-level-retries", "3",
                stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL, start_new_session=True,
            )
            try:
                if await asyncio.wait_for(process.wait(), timeout=1800) != 0:
                    raise PipelineRetry("Original archive copy failed; local media retained")
            except TimeoutError:
                raise PipelineRetry("Original archive copy timed out; local media retained") from None
            finally:
                await asyncio.shield(_terminate(process))
        details["archived"] = True
        await self._update(token, window, details=details)

    async def _post(self, channel, token, window, clip, account_id, provider, policy, details):
        current = (await store_call("get_policy", channel.user_id, channel.channel_id))["policy"]
        await self._live(token)
        if account_id not in current.social_account_ids:
            return None
        visibility = {"private": 0, "unlisted": 1, "public": 2}
        policy = policy.model_copy(update={
            "publish_privacy": min((policy.publish_privacy, current.publish_privacy), key=visibility.__getitem__),
            "max_posts_per_day": min(policy.max_posts_per_day, current.max_posts_per_day),
        })
        if provider == "instagram" and policy.publish_privacy != "public":
            raise PipelineBlocked("Instagram publication is public; explicitly select public visibility before enabling it")
        key = "recording:" + hashlib.sha256(f"{window.id}:{clip['id']}:{account_id}".encode()).hexdigest()
        async with AsyncSessionLocal() as db:
            # The owner's daily allowance is shared across channels and manual
            # posts. A dedicated advisory connection survives native commits.
            async with source_admission_lock(db, channel.user_id, "recording-publication-budget"):
                existing = (await db.execute(text("""
                    SELECT post_id FROM social_post_requests WHERE user_id=:user AND request_key=:key
                """), {"user": channel.user_id, "key": key})).scalar_one_or_none()
                if existing:
                    return existing
                others = (await db.execute(text("""
                    SELECT metadata FROM recording_windows WHERE channel_id=:channel
                    AND session_id=:session AND epoch=:epoch AND id<>:window
                """), {"channel": window.channel_id, "session": window.session_id, "epoch": window.epoch, "window": window.id})).scalars().all()
                reservations = [entry for other in others for entry in other.get("post_reservations", [])]
                start, end = window.start_seconds + _seconds(clip["start_time"]), window.start_seconds + _seconds(clip["end_time"])
                if overlaps_reserved(start, end, account_id, reservations):
                    return None
                count = (await db.execute(text("""
                    SELECT count(*) FROM social_posts WHERE user_id=:user
                      AND created_at >= date_trunc('day', clock_timestamp() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'
                      AND status <> 'cancelled'
                """), {"user": channel.user_id})).scalar_one()
                if count >= policy.max_posts_per_day:
                    raise PublicationLimitReached("Daily publication limit reached; remaining clips stay in the library")
                await db.commit()
                await self._live(token)
                reservation = {"account_id": account_id, "clip_id": clip["id"], "start": start, "end": end}
                reserved = details.setdefault("post_reservations", [])
                if reservation not in reserved:
                    reserved.append(reservation)
                    await self._update(token, window, details=details)
                response = await self.native.request(channel.user_id, "POST", "/social/posts", key=key, json={
                    "task_id": window.task_id, "clip_id": clip["id"], "social_account_id": account_id,
                    "privacy_level": policy.publish_privacy,
                })
                return response["post"]["id"]

    async def step(self, channel, token, window):
        """Advance work without waiting for a render or remote post to finish."""
        try:
            await self._step(channel, token, window)
        except LostLeaseError:
            raise
        except PipelineBlocked as exc:
            await self._update(token, window, status="blocked", last_error=str(exc), next_attempt_at=None)
        except PublicationLimitReached:
            await store_call("mark_publication_capped", token, window.id)
        except (PipelineRetry, OSError, ValueError, KeyError) as exc:
            attempts = window.attempts + 1
            exhausted = attempts - window.details.get("retry_base", 0) >= 12
            message = str(exc) if isinstance(exc, (PipelineRetry, PipelineBlocked)) else f"Automation stage failed ({type(exc).__name__}); inspect server diagnostics"
            await self._update(token, window, attempts=attempts, **({"status": "blocked"} if exhausted else {}),
                next_attempt_at=None if exhausted else datetime.now(timezone.utc) + timedelta(seconds=retry_delay(attempts - window.details.get("retry_base", 0) - 1)), last_error=message)

    async def _step(self, channel, token, window):
        await self._live(token)
        if window.status in {"completed", "blocked"}:
            return
        if not window.task_id and window.status in {"processing", "publishing"}:
            raise PipelineBlocked("The bound task was deleted; automatic recreation is disabled")
        policy = AutomationPolicy.model_validate(window.details.get("policy", channel.policy.model_dump()))
        details = json.loads(json.dumps(window.details))
        path = contained_path(self.root, window.source_path)
        if not path.is_file() or path.stat().st_size != window.size_bytes or (not window.upload_ref and await asyncio.to_thread(_digest, path) != window.sha256):
            raise PipelineBlocked("Recorded media is missing or changed; restore it before retrying")
        if policy.archive:
            await self._archive(token, window, details)
        if not window.upload_ref:
            window = await self._update(token, window, status="submitting")
            await self._live(token)
            with path.open("rb") as stream:
                result = await self.native.request(channel.user_id, "POST", "/upload", key=f"recording:{window.id}:upload",
                    files={"video": (path.name, stream, "video/mp4")})
            window = await self._update(token, window, upload_ref=result["video_path"])
        if not window.task_id:
            await self._live(token)
            result = await self.native.request(channel.user_id, "POST", "/tasks/", key=f"recording:{window.id}:task", json={
                "source": {"url": window.upload_ref}, "processing_mode": policy.processing_mode,
                "caption_template": policy.caption_template, "clip_length": policy.clip_length,
                "output_format": "vertical", "add_subtitles": True,
            })
            window = await self._update(token, window, task_id=result["task_id"], status="processing", last_error=None)
        task = await self.native.request(channel.user_id, "GET", f"/tasks/{window.task_id}")
        status = task.get("status")
        if status in {"error", "cancelled"}:
            retries = details.get("render_retries", 0)
            if status == "cancelled" or retries >= 3:
                raise PipelineBlocked("Rendering was cancelled or exhausted automatic retries; inspect the task")
            details["render_retries"] = retries + 1
            await self._update(token, window, details=details)
            await self._live(token)
            await self.native.request(channel.user_id, "POST", f"/tasks/{window.task_id}/resume")
            return
        if status != "completed":
            await self._update(token, window, next_attempt_at=datetime.now(timezone.utc) + timedelta(seconds=30))
            return
        if "selected_clip_ids" not in details:
            selected = choose_clips(task.get("clips", []), overlap=window.overlap_seconds,
                min_score=policy.min_score, limit=policy.max_clips_per_window)
            details["selected_clip_ids"] = [clip["id"] for clip in selected]
            await self._update(token, window, details=details)
        current_clips = {clip["id"]: clip for clip in task.get("clips", [])}
        if any(identity not in current_clips for identity in details["selected_clip_ids"]):
            raise PipelineBlocked("A selected clip was removed; review this window before publication")
        clips = [current_clips[identity] for identity in details["selected_clip_ids"]]
        post_ids = list(details.get("post_ids", []))
        # Current policy can revoke a destination; an old window cannot grant it.
        accounts = [account for account in policy.social_account_ids if account in channel.policy.social_account_ids]
        if (not accounts or not clips) and not post_ids:
            await self._update(token, window, status="completed", last_error=None, next_attempt_at=None)
            return
        window = await self._update(token, window, status="publishing")
        # Explicit deletion of a known post must not resurrect its publication.
        for post_id in post_ids:
            await self.native.request(channel.user_id, "GET", f"/social/posts/{post_id}")
        if accounts and clips and not details.get("publication_capped"):
            connections = await self.native.request(channel.user_id, "GET", "/social/connections")
            providers = {account["id"]: account["provider"] for account in connections.get("connections", []) if account.get("status") == "active"}
            for account_id in accounts:
                provider = providers.get(account_id)
                if provider not in {"youtube", "instagram"}:
                    raise PipelineBlocked("Autonomous publication supports connected YouTube and Instagram accounts; review other destinations in Social settings")
                for clip in clips:
                    post_id = await self._post(channel, token, window, clip, account_id, provider, policy, details)
                    if post_id and post_id not in post_ids:
                        post_ids.append(post_id)
                        details["post_ids"] = post_ids
                        await self._update(token, window, details=details)
        published = True
        for post_id in post_ids:
            result = await self.native.request(channel.user_id, "GET", f"/social/posts/{post_id}")
            post = result["post"]
            if post["status"] in {"failed", "cancelled"}:
                safe_retries = details.get("post_queue_retries", 0)
                if post["status"] == "failed" and not post.get("attempts") and not post.get("pending_handle") and not post.get("external_post_id") and safe_retries < 3:
                    details["post_queue_retries"] = safe_retries + 1
                    await self._update(token, window, details=details)
                    await self._live(token)
                    await self.native.request(channel.user_id, "POST", f"/social/posts/{post_id}/retry")
                    published = False
                    continue
                raise PipelineBlocked("Publication needs review in Social settings; no duplicate upload was submitted")
            if post["status"] == "queued":
                # Repair a crash after committing a post but before enqueueing.
                # Native publisher atomically claims each post, so repeated queue
                # delivery cannot cause a second upload.
                from ..workers.job_queue import DuplicateJobError, JobQueue
                try:
                    await JobQueue.enqueue_job("publish_social_post", post_id, _job_id=f"social:{post_id}:{int(post.get('attempts') or 0)}")
                except DuplicateJobError:
                    pass
                except Exception:
                    raise PipelineRetry("Could not requeue the existing publication; its receipt was retained") from None
            published &= post["status"] == "published"
        await self._update(token, window, status="completed" if published else "publishing", last_error=None,
            next_attempt_at=None if published else datetime.now(timezone.utc) + timedelta(seconds=30))
