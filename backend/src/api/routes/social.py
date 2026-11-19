"""
Social publishing routes.

Connecting and disconnecting accounts requires the frontend's signed session
headers (an API key must not be able to attach new social accounts). Posting
and reading performance data accept either an API key or session headers so
programmatic clients (MCP, scripts) can publish too.
"""

from __future__ import annotations

import logging
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ...auth_headers import get_authenticated_user_id, resolve_authenticated_user_id
from ...feature_flags import client_platform
from ...config import get_config
from ...database import get_db
from ...media_storage import is_s3
from ...services.social_service import SocialError, SocialService
from ...repositories.social_repository import SocialRepository
from ...source_identity import source_admission_lock
from ...services.social_publication_policy import PublishingPolicy, SocialPublicationPolicyService
from ...services.social_source_deletion import SourceDeletionSelection
from ...services.social_review_service import SocialReviewService, ReviewImport, ReviewCandidate, ReviewApproval
from typing import Literal
from ...utils.async_helpers import run_in_thread

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/social", tags=["social"])


def _service(request: Request, db: AsyncSession) -> SocialService:
    queue_adapter = getattr(request.app.state, "queue_adapter", None)
    return SocialService(
        db, get_config(), queue_adapter=queue_adapter, platform=client_platform(request)
    )


async def _user_id(request: Request, db: AsyncSession) -> str:
    return await resolve_authenticated_user_id(request, db, get_config())


def _session_user_id(request: Request) -> str:
    """Resolve the user from signed session headers only (never an API key)."""
    return get_authenticated_user_id(request, get_config())


async def _allowed_user_id(
    request: Request, db: AsyncSession, *, session_only: bool = False
) -> str:
    """Resolve the user and enforce the social publishing rollout setting."""
    user_id = _session_user_id(request) if session_only else await _user_id(request, db)
    if not await _service(request, db).has_access(user_id):
        raise HTTPException(
            status_code=403, detail="Social publishing isn't available on your account yet."
        )
    return user_id


def _http_error(exc: SocialError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=str(exc))


async def _json_body(request: Request) -> Dict[str, Any]:
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001 - empty or invalid body
        return {}
    return payload if isinstance(payload, dict) else {}


# ----------------------------------------------------------------------
# Providers & connections
# ----------------------------------------------------------------------
@router.get("/providers")
async def list_providers(request: Request, db: AsyncSession = Depends(get_db)):
    """
    Which platforms this server can publish to (based on configured OAuth apps).

    Users outside the rollout get ``enabled: false`` and every platform reported
    as unconfigured, so clients that predate the flag simply hide publishing.
    """
    user_id = await _user_id(request, db)
    service = _service(request, db)
    providers = service.list_providers()
    enabled = await service.has_access(user_id)
    if not enabled:
        providers = [{**provider, "configured": False} for provider in providers]
    else:
        # A paused platform reads as unconfigured, so older clients (iOS) hide it;
        # `paused` lets the web explain why.
        providers = [
            {**provider, "configured": False, "paused": True}
            if provider["configured"] and await service.provider_paused(provider["provider"], user_id)
            else provider
            for provider in providers
        ]
    can_schedule = enabled and await service.can_schedule(user_id)
    return {"enabled": enabled, "can_schedule": can_schedule, "providers": providers}


@router.get("/connections")
async def list_connections(request: Request, db: AsyncSession = Depends(get_db)):
    user_id = await _allowed_user_id(request, db)
    connections = await _service(request, db).list_connections(user_id)
    return {"connections": connections, "total": len(connections)}


@router.get("/youtube/setup")
async def youtube_setup(request: Request, db: AsyncSession = Depends(get_db)):
    user_id = await _allowed_user_id(request, db, session_only=True)
    return await _service(request, db).youtube_setup(user_id)


@router.get("/accounts/{account_id}/automation")
async def get_publication_policy(account_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    user_id = await _allowed_user_id(request, db)
    try:
        return await SocialPublicationPolicyService(db).get(user_id, account_id)
    except SocialError as exc:
        raise _http_error(exc)


@router.put("/accounts/{account_id}/automation")
async def save_publication_policy(account_id: str, body: PublishingPolicy, request: Request, db: AsyncSession = Depends(get_db)):
    user_id = await _allowed_user_id(request, db, session_only=True)
    try:
        return await SocialPublicationPolicyService(db).save(user_id, account_id, body.model_dump(mode="json", exclude_unset=True))
    except SocialError as exc:
        raise _http_error(exc)


@router.post("/deletion-impact")
async def source_deletion_impact(body: SourceDeletionSelection, request: Request, db: AsyncSession = Depends(get_db)):
    # Deletion recovery stays available even when publishing intake is disabled.
    user_id = _session_user_id(request)
    return await SocialRepository.deletion_impact(db,user_id,body.task_ids,clip_id=body.clip_id)


@router.get("/review")
async def list_review(request: Request, account_id: str, status: Literal["pending", "approved", "rejected", "cancelled"] = "pending",
                      limit: int = 50, db: AsyncSession = Depends(get_db)):
    user_id = await _allowed_user_id(request, db)
    try:
        return await SocialReviewService(_service(request, db)).list(user_id, account_id, status, max(1, min(200, limit)))
    except SocialError as exc:
        raise _http_error(exc)


@router.post("/review/import")
async def import_review(body: ReviewImport, request: Request, db: AsyncSession = Depends(get_db)):
    user_id = await _allowed_user_id(request, db, session_only=True)
    try:
        return await SocialReviewService(_service(request, db)).import_clips(user_id, body)
    except SocialError as exc:
        raise _http_error(exc)


@router.post("/review/candidates")
async def add_review_candidate(body: ReviewCandidate, request: Request, db: AsyncSession = Depends(get_db)):
    user_id = await _allowed_user_id(request, db)
    try:
        return await SocialReviewService(_service(request, db)).candidate(user_id, body.account_id, body.task_id, body.clip_id)
    except SocialError as exc:
        raise _http_error(exc)


@router.post("/review/{identity}/approve")
async def approve_review(identity: str, body: ReviewApproval, request: Request, db: AsyncSession = Depends(get_db)):
    user_id = await _allowed_user_id(request, db, session_only=True)
    try:
        return await SocialReviewService(_service(request, db)).approve(user_id, identity, body)
    except SocialError as exc:
        raise _http_error(exc)


@router.post("/review/{identity}/reject")
async def reject_review(identity: str, request: Request, db: AsyncSession = Depends(get_db)):
    user_id = await _allowed_user_id(request, db, session_only=True)
    try:
        return await SocialReviewService(_service(request, db)).decide(user_id, identity)
    except SocialError as exc:
        raise _http_error(exc)


@router.post("/review/{identity}/undo")
async def undo_review(identity: str, request: Request, db: AsyncSession = Depends(get_db)):
    user_id = await _allowed_user_id(request, db, session_only=True)
    try:
        return await SocialReviewService(_service(request, db)).decide(user_id, identity, undo=True)
    except SocialError as exc:
        raise _http_error(exc)


@router.get("/connections/{account_id}/publishing-options")
async def publishing_options(account_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    user_id = await _allowed_user_id(request, db)
    try:
        return await _service(request, db).publishing_options(user_id, account_id)
    except SocialError as exc:
        raise _http_error(exc)


@router.post("/connections/{provider}/authorize")
async def start_connection(
    provider: str, request: Request, db: AsyncSession = Depends(get_db)
):
    """
    Begin the OAuth handshake; the caller redirects the browser to ``authorize_url``.

    ``{"client": "ios"}`` marks the state as mobile: the web callback then hands
    the code back to the app, which completes the handshake with its own session.
    """
    user_id = await _allowed_user_id(request, db, session_only=True)
    body = await _json_body(request)
    client = body.get("client") if isinstance(body.get("client"), str) else None
    try:
        return await _service(request, db).start_connection(user_id, provider, client=client)
    except SocialError as exc:
        raise _http_error(exc)


@router.post("/connections/{provider}/callback")
async def complete_connection(
    provider: str, request: Request, db: AsyncSession = Depends(get_db)
):
    """Finish the OAuth handshake with the ``code`` and ``state`` the platform returned."""
    user_id = await _allowed_user_id(request, db, session_only=True)
    body = await _json_body(request)
    try:
        connection = await _service(request, db).complete_connection(
            user_id,
            provider,
            code=str(body.get("code") or ""),
            state=str(body.get("state") or ""),
        )
    except SocialError as exc:
        raise _http_error(exc)
    return {"connection": connection}


@router.delete("/connections")
async def disconnect_all_accounts(request: Request, db: AsyncSession = Depends(get_db)):
    """Disconnect (and revoke at the platform) every account; used on account deletion."""
    user_id = _session_user_id(request)
    try:
        removed = await _service(request, db).disconnect_all(user_id)
    except SocialError as exc:
        raise _http_error(exc)
    return {"message": "Accounts disconnected", "removed": removed}


@router.delete("/connections/{account_id}")
async def disconnect_account(
    account_id: str, request: Request, db: AsyncSession = Depends(get_db)
):
    user_id = _session_user_id(request)
    try:
        removed = await _service(request, db).disconnect(user_id, account_id)
    except SocialError as exc:
        raise _http_error(exc)
    if not removed:
        raise HTTPException(status_code=404, detail="Connected account not found")
    return {"message": "Account disconnected"}


# ----------------------------------------------------------------------
# Posts
# ----------------------------------------------------------------------
@router.get("/posts")
async def list_posts(
    request: Request,
    db: AsyncSession = Depends(get_db),
    task_id: Optional[str] = None,
    clip_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
    account_id: Optional[str] = None,
    status_group: Optional[Literal["active", "history"]] = None,
    offset: int = 0,
):
    user_id = await _allowed_user_id(request, db)
    posts = await _service(request, db).list_posts(
        user_id, task_id=task_id, clip_id=clip_id, status=status, limit=limit, account_id=account_id, status_group=status_group, offset=offset
    )
    return {"posts": posts, "total": len(posts), "next_offset": max(0, offset)+len(posts) if len(posts)==max(1,min(limit,500)) else None}


@router.post("/captions")
async def generate_caption(request: Request, db: AsyncSession = Depends(get_db)):
    """Draft a social caption without publishing or scheduling anything."""
    user_id = await _allowed_user_id(request, db)
    body = await _json_body(request)
    for field in ("task_id", "clip_id", "provider"):
        if not isinstance(body.get(field), str) or not body[field].strip():
            raise HTTPException(status_code=422, detail=f"{field} is required")
    try:
        return await _service(request, db).generate_caption(
            user_id, task_id=body["task_id"], clip_id=body["clip_id"], provider=body["provider"]
        )
    except SocialError as exc:
        raise _http_error(exc)


@router.post("/posts")
async def create_post(request: Request, db: AsyncSession = Depends(get_db)):
    """Publish (or schedule) a clip to a connected account."""
    user_id = await _allowed_user_id(request, db)
    body = await _json_body(request)
    key = request.headers.get("idempotency-key", "").strip()
    if key and not re.fullmatch(r"[A-Za-z0-9._:-]{8,200}", key):
        raise HTTPException(status_code=400, detail="Invalid idempotency key")
    if not key:
        return await _create_post(request, db, user_id, body)
    request_hash = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    async with source_admission_lock(db, user_id, f"social-post:{key}"):
        receipt = await SocialRepository.get_post_request(db, user_id, key)
        if receipt:
            if receipt.request_hash != request_hash:
                raise HTTPException(status_code=409, detail="Idempotency key already used for a different publication")
            if receipt.post_id is None:
                raise HTTPException(status_code=410, detail="Publication history was deleted; this request will not create another upload")
            return {"post": await SocialRepository.get_user_post(db, user_id, receipt.post_id)}
        return await _create_post(request, db, user_id, body, key, request_hash)


async def _create_post(request, db, user_id, body, request_key=None, request_hash=None):
    for field in ("task_id", "clip_id", "social_account_id"):
        if not body.get(field):
            raise HTTPException(status_code=422, detail=f"{field} is required")
    hashtags = body.get("hashtags")
    if isinstance(hashtags, str):
        hashtags = [hashtags]
    try:
        post = await _service(request, db).create_post(
            user_id,
            task_id=str(body["task_id"]),
            clip_id=str(body["clip_id"]),
            social_account_id=str(body["social_account_id"]),
            title=body.get("title"),
            caption=body.get("caption"),
            hashtags=hashtags,
            privacy_level=body.get("privacy_level"),
            scheduled_for=body.get("scheduled_for"),
            **({"request_key": request_key, "request_hash": request_hash} if request_key else {}),
        )
    except SocialError as exc:
        raise _http_error(exc)
    return {"post": post}


@router.get("/performance")
async def get_performance(request: Request, db: AsyncSession = Depends(get_db)):
    """Aggregate audience performance, grouped the same way the AI uses it."""
    user_id = await _allowed_user_id(request, db)
    return await _service(request, db).get_performance_summary(user_id)


@router.get("/performance/timeseries")
async def get_views_timeseries(
    request: Request, db: AsyncSession = Depends(get_db), days: int = 30
):
    """Daily new views across the user's published posts, for the analytics chart."""
    user_id = await _allowed_user_id(request, db)
    return await _service(request, db).get_views_timeseries(user_id, days=days)


@router.get("/posts/{post_id}")
async def get_post(post_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    user_id = await _allowed_user_id(request, db)
    try:
        return {"post": await _service(request, db).get_post(user_id, post_id)}
    except SocialError as exc:
        raise _http_error(exc)


@router.post("/posts/{post_id}/cancel")
async def cancel_post(post_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    user_id = await _allowed_user_id(request, db)
    try:
        return {"post": await _service(request, db).cancel_post(user_id, post_id)}
    except SocialError as exc:
        raise _http_error(exc)


@router.post("/posts/{post_id}/reschedule")
async def reschedule_post(post_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    user_id = await _allowed_user_id(request, db, session_only=True)
    body = await _json_body(request)
    custom = body.get("custom_local")
    if not isinstance(custom, str) or not 1 <= len(custom) <= 32:
        raise HTTPException(status_code=400, detail="Choose a future local publication time.")
    try:
        return {"post": await _service(request, db).reschedule_post(user_id, post_id, custom)}
    except SocialError as exc:
        raise _http_error(exc)


@router.post("/posts/{post_id}/retry")
async def retry_post(post_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    user_id = await _allowed_user_id(request, db)
    try:
        return {"post": await _service(request, db).retry_post(user_id, post_id)}
    except SocialError as exc:
        raise _http_error(exc)


@router.post("/posts/{post_id}/refresh-metrics")
async def refresh_post_metrics(
    post_id: str, request: Request, db: AsyncSession = Depends(get_db)
):
    user_id = await _allowed_user_id(request, db)
    service = _service(request, db)
    try:
        post = await service.get_post(user_id, post_id)
        refreshed = await service.refresh_post_metrics(post, user_id=user_id)
    except SocialError as exc:
        raise _http_error(exc)
    return {"post": refreshed}


@router.delete("/posts/{post_id}")
async def delete_post(post_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    user_id = await _allowed_user_id(request, db)
    try:
        deleted = await _service(request, db).delete_post(user_id, post_id)
    except SocialError as exc:
        raise _http_error(exc)
    if not deleted:
        raise HTTPException(status_code=404, detail="Post not found")
    return {"message": "Post deleted"}


# ----------------------------------------------------------------------
# Public media (Instagram fetches the video from a URL)
# ----------------------------------------------------------------------
@router.get("/media/{media_token}")
async def get_public_media(
    media_token: str, request: Request, db: AsyncSession = Depends(get_db, scope="function")
):
    """Serve a clip to a platform using a short-lived, unguessable token."""
    service = _service(request, db)
    reference = await service.get_public_media_reference(media_token)
    if reference is None:
        raise HTTPException(status_code=404, detail="Media not found")
    # Release the session before streaming (see get_clip_file in tasks.py).
    await db.close()
    if is_s3(reference):
        url = await run_in_thread(service.public_media_redirect_url, reference)
        return RedirectResponse(url, status_code=307, headers={"Cache-Control": "private, no-store"})
    path = Path(reference)
    return FileResponse(
        path=str(path),
        media_type="video/mp4",
        filename=path.name,
        content_disposition_type="inline",
        headers={"Cache-Control": "private, no-store"},
    )
