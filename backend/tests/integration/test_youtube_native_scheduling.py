"""Native publication survives lost replies, deletion and an offline VPS."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest
import uuid
import requests
from sqlalchemy import text

from src.services import social_service as module
from src.services.social_service import SocialService
from src.social.youtube import YouTubeProvider
from tests.integration.test_social_review import review_item, social_setup, short_file  # noqa: F401
from tests.integration.test_youtube_publication_lifecycle import due, inserts, video
from tests.unit.test_social_providers import FakeResponse, FakeSession


class Google(FakeSession):
    def __init__(self):
        super().__init__({
            ("POST", "/upload/youtube/"): FakeResponse(200, headers={"Location": "https://www.googleapis.com/upload/youtube/v3/videos?upload_id=private"}),
            ("PUT", "upload_id="): FakeResponse(201, {"id": "video-1"}),
            ("POST", "oauth2.googleapis.com/token"): FakeResponse(200, {"access_token": "fresh", "expires_in": 3600}),
        })
        self.resource = video()["items"][0]
        self.resource["status"].update(license="creativeCommon", embeddable=False, publicStatsViewable=False, selfDeclaredMadeForKids=False)
        self.lose_update = False
        self.reject_update = False

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return FakeResponse(200, {"items": [deepcopy(self.resource)]})

    def put(self, url, **kwargs):
        if "upload_id=" in url:
            return super().put(url, **kwargs)
        self.calls.append(("PUT", url, kwargs))
        if self.reject_update:
            return FakeResponse(503, {})
        self.resource["status"] = {"uploadStatus": "processed", **kwargs["json"]["status"]}
        if self.lose_update:
            self.lose_update = False
            raise requests.Timeout("private-request")
        return FakeResponse(200, deepcopy(self.resource))

    def delete(self,url,**kwargs):
        self.calls.append(("DELETE",url,kwargs))
        self.resource = {}
        return FakeResponse(204,{})


@pytest.fixture
async def native(review_item, client, auth_headers, app, db_session, monkeypatch):
    item, payload, path, _ = review_item
    approved = await client.post(f"/social/review/{item['id']}/approve", headers=auth_headers, json={"expected_version": item["version"]})
    assert approved.status_code == 200, approved.text
    post = approved.json()["post"]
    app.state.config.youtube_oauth_client_id = f"native-test-{uuid.uuid4()}"
    app.state.config.youtube_oauth_client_secret = "native-secret"
    http = Google()
    provider = YouTubeProvider(app.state.config, http)
    monkeypatch.setattr(module, "get_provider", lambda *_a, **_kw: provider)
    return SocialService(db_session, app.state.config, queue_adapter=app.state.queue_adapter), post, http, path


def updates(http):
    return [kw["json"]["status"] for method, url, kw in http.calls if method == "PUT" and "upload_id=" not in url]


async def scheduled(native, db_session):
    service, post, http, _ = native
    await service.publish_post(post["id"])
    await due(db_session, post["id"])
    await service.resolve_pending_post(await service.repo.get_post(db_session, post["id"]))
    return await service.get_post("user-1", post["id"])


async def test_private_processed_upload_precedes_verified_native_schedule(native, db_session):
    service, post, http, _ = native
    first = await service.publish_post(post["id"])
    assert first["stage"] == "processing" and not updates(http)
    initial = next(kw["json"] for method, url, kw in http.calls if method == "POST" and "/upload/youtube/" in url)
    assert initial["status"]["privacyStatus"] == "private" and "publishAt" not in initial["status"]
    await due(db_session, post["id"])
    await service.resolve_pending_post(first)
    result = await service.get_post("user-1", post["id"])
    assert result["status"] == "scheduled" and result["stage"] == "youtube_scheduled"
    status = updates(http)[0]
    assert datetime.fromisoformat(status["publishAt"].replace("Z", "+00:00")) == datetime.fromisoformat(result["scheduled_for"])
    assert status["privacyStatus"] == "private" and status["license"] == "creativeCommon" and status["embeddable"] is False
    assert inserts(http) == 1


async def test_lost_schedule_reply_checks_same_video_before_another_update(native, db_session):
    service, post, http, _ = native
    http.lose_update = True
    await scheduled(native, db_session)
    await due(db_session, post["id"])
    await service.resolve_pending_post(await service.repo.get_post(db_session, post["id"]))
    result = await service.get_post("user-1", post["id"])
    assert result["stage"] == "youtube_scheduled" and inserts(http) == 1 and len(updates(http)) == 1


async def test_late_processing_moves_to_future_pattern_instead_of_past_publish_at(native, db_session):
    service, post, http, _ = native
    await db_session.execute(text("UPDATE social_publication_slots SET publish_at=NOW()-INTERVAL '1 hour' WHERE review_id=:id"), {"id": post["provider_options"]["review"]["id"]})
    await db_session.execute(text("UPDATE social_posts SET scheduled_for=NOW()-INTERVAL '1 hour' WHERE id=:id"), {"id": post["id"]})
    await db_session.commit()
    result = await scheduled(native, db_session)
    assert datetime.fromisoformat(result["scheduled_for"]) >= datetime.now(timezone.utc) + timedelta(minutes=14)
    assert datetime.fromisoformat(updates(http)[0]["publishAt"].replace("Z", "+00:00")) >= datetime.now(timezone.utc) + timedelta(minutes=14)


async def test_google_published_while_vps_offline_reconciles_without_reupload(native, db_session):
    service, post, http, _ = native
    await scheduled(native, db_session)
    http.resource["status"] = {"privacyStatus": "public", "uploadStatus": "processed"}
    await due(db_session, post["id"])
    await service.resolve_pending_post(await service.repo.get_post(db_session, post["id"]))
    result = await service.get_post("user-1", post["id"])
    assert result["status"] == "published" and inserts(http) == 1


async def test_cancel_waits_for_google_confirmation_and_keeps_video_private(native, db_session):
    service, post, http, _ = native
    await scheduled(native, db_session)
    http.reject_update = True
    result = await service.cancel_post("user-1", post["id"])
    assert result["status"] != "cancelled"
    await service.publish_post(post["id"])
    result = await service.get_post("user-1", post["id"])
    assert result["status"] != "cancelled" and "publishAt" in http.resource["status"]
    http.reject_update = False
    await due(db_session, post["id"])
    await service.publish_post(post["id"])
    result = await service.get_post("user-1", post["id"])
    assert result["status"] == "cancelled" and "publishAt" not in http.resource["status"]
    assert http.resource["status"]["privacyStatus"] == "private" and inserts(http) == 1


async def test_library_deletion_requires_warning_acknowledgement(native, db_session, client, auth_headers):
    service, post, http, path = native
    await scheduled(native, db_session)
    response = await client.delete(f"/tasks/{post['task_id']}", headers=auth_headers)
    assert response.status_code == 409
    result = await service.get_post("user-1", post["id"])
    assert result["clip_id"] is not None and result["status"] == "scheduled" and path.exists()
    assert "publishAt" in http.resource["status"] and inserts(http) == 1


async def test_cancel_racing_already_public_is_truthful(native, db_session):
    service, post, http, _ = native
    await scheduled(native, db_session)
    http.resource["status"] = {"privacyStatus": "public", "uploadStatus": "processed"}
    await service.cancel_post("user-1", post["id"])
    await service.publish_post(post["id"])
    result = await service.get_post("user-1", post["id"])
    assert result["status"] == "published" and http.resource["status"]["privacyStatus"] == "public"


async def test_approved_bytes_changed_before_upload_are_rejected(native):
    service, post, http, path = native
    path.write_bytes(b"changed after review")
    result = await service.publish_post(post["id"])
    assert result["status"] == "failed" and result["reason_code"] == "media_changed" and http.calls == []


async def test_upload_pause_blocks_bytes_but_cancellation_still_works(native, db_session, client, auth_headers):
    service, post, http, _ = native
    await client.put(f"/social/accounts/{post['social_account_id']}/automation", headers=auth_headers, json={"uploads_paused": True})
    result = await service.publish_post(post["id"])
    assert result["stage"] == "paused" and http.calls == []
    await service.cancel_post("user-1", post["id"])
    await service.publish_post(post["id"])
    assert (await service.get_post("user-1", post["id"]))["status"] == "cancelled"


async def test_native_recovery_uses_network_worker_queue(native, db_session, app):
    service, post, http, _ = native
    app.state.queue_adapter.enqueued_jobs.clear()
    await service.resolve_pending_posts()
    jobs = app.state.queue_adapter.enqueued_jobs
    assert len(jobs) == 1 and jobs[0]["kwargs"]["_queue_name"] == "supoclip_cron"
    assert http.calls == []

async def test_custom_reschedule_updates_same_video_and_rejects_past_time(native, db_session, client, auth_headers):
    service, post, http, _ = native
    result = await scheduled(native, db_session)
    future = (datetime.fromisoformat(result["scheduled_for"]) + timedelta(days=1)).replace(tzinfo=None, second=0, microsecond=0).isoformat(timespec="minutes")
    endpoint = f"/social/posts/{post['id']}/reschedule"
    assert (await client.post(endpoint, json={"custom_local": future})).status_code == 401
    assert (await client.post(endpoint, headers=auth_headers, json={"custom_local": "2020-01-01T12:00"})).status_code == 400
    response = await client.post(endpoint, headers=auth_headers, json={"custom_local": future})
    assert response.status_code == 200, response.text
    assert response.json()["post"]["status"] == "publishing"  # awaiting Google confirmation
    await service.publish_post(post["id"])
    result = await service.get_post("user-1", post["id"])
    assert result["stage"] == "youtube_scheduled" and result["scheduled_for"].startswith(future)
    assert inserts(http) == 1 and len(updates(http)) == 2


async def test_shared_project_quota_defers_another_upload(native, db_session):
    service, post, http, path = native
    http.routes[("POST", "/upload/youtube/")] = FakeResponse(403, {"error": {"errors": [{"reason": "quotaExceeded"}]}})
    first = await service.publish_post(post["id"])
    assert first["stage"] == "waiting_for_quota"
    # A separate approved post sharing this Google project's dedicated upload bucket.
    import uuid
    second = str(uuid.uuid4())
    await db_session.execute(text("""
        INSERT INTO social_posts(id,user_id,task_id,clip_id,social_account_id,provider,status,title,caption,hashtags,privacy_level,source_file_path,provider_options)
        SELECT :new,user_id,task_id,clip_id,social_account_id,provider,'queued',title,caption,hashtags,privacy_level,source_file_path,provider_options
        FROM social_posts WHERE id=:id
    """), {"new":second,"id":post["id"]})
    await db_session.commit()
    calls = len(http.calls)
    result = await service.publish_post(second)
    assert result["stage"] == "waiting_for_quota" and len(http.calls) == calls


async def test_unfinished_cancel_does_not_count_as_private_processing_proof(native, db_session):
    service, post, http, _ = native
    await service.cancel_post("user-1", post["id"])
    await service.publish_post(post["id"])
    metadata = (await db_session.execute(text("SELECT metadata FROM social_accounts WHERE id=:id"), {"id":post["social_account_id"]})).scalar_one()
    assert not metadata.get("youtube_private_test_completed_at") and not http.calls

async def test_overdue_native_schedule_is_flagged_instead_of_waiting_forever(native, db_session):
    service, post, http, _ = native
    await scheduled(native, db_session)
    past = datetime.now(timezone.utc)-timedelta(hours=1)
    http.resource["status"]["publishAt"] = past.isoformat()
    await db_session.execute(text("UPDATE youtube_uploads SET desired_publish_at=:at,confirmed_publish_at=:at,next_attempt_at=NOW() WHERE post_id=:id"), {"id":post["id"],"at":past})
    await db_session.commit()
    await service.publish_post(post["id"])
    result = await service.get_post("user-1", post["id"])
    assert result["status"] == "failed" and result["reason_code"] == "publication_delayed" and inserts(http) == 1


async def test_revoked_native_account_retains_id_and_cancel_intent_for_reconnection(native, db_session):
    service, post, http, _ = native
    await scheduled(native, db_session)
    await service.cancel_post("user-1", post["id"])
    await db_session.execute(text("UPDATE social_accounts SET revoked_at=NOW() WHERE id=:id"), {"id":post["social_account_id"]})
    await db_session.commit()
    result = await service.publish_post(post["id"])
    assert result["stage"] == "reconnect_required" and result["provider_options"]["cancel_requested"] is True
    assert result["external_post_id"] == "video-1" and "publishAt" in http.resource["status"]
    await db_session.execute(text("UPDATE social_accounts SET revoked_at=NULL,status='active' WHERE id=:id"), {"id":post["social_account_id"]})
    await db_session.commit()
    await service.retry_post("user-1", post["id"])
    await service.publish_post(post["id"])
    assert (await service.get_post("user-1", post["id"]))["status"] == "cancelled" and inserts(http) == 1


async def test_native_schedule_edited_in_studio_updates_reservation(native, db_session):
    service, post, http, _ = native
    result = await scheduled(native, db_session)
    moved = datetime.fromisoformat(result["scheduled_for"]) + timedelta(days=1)
    http.resource["status"]["publishAt"] = moved.isoformat()
    await due(db_session, post["id"])
    await service.publish_post(post["id"])
    result = await service.get_post("user-1", post["id"])
    reservation = (await db_session.execute(text("SELECT publish_at FROM social_publication_slots WHERE review_id=:id"), {"id":post["provider_options"]["review"]["id"]})).scalar_one()
    assert datetime.fromisoformat(result["scheduled_for"]) == moved == reservation

async def test_disconnect_and_account_deletion_wait_for_native_cancellation(native, db_session, client, auth_headers):
    service, post, http, _ = native
    await scheduled(native, db_session)
    http.routes[("POST", "oauth2.googleapis.com/revoke")] = FakeResponse(200, {})
    for endpoint in [f"/social/connections/{post['social_account_id']}", "/social/connections"]:
        response = await client.delete(endpoint, headers=auth_headers)
        assert response.status_code == 409, response.text
        account = await service.repo.get_account_with_tokens(db_session, post["social_account_id"])
        assert account["access_token_encrypted"] and account["revoked_at"] is None
        result = await service.get_post("user-1", post["id"])
        assert result["status"] != "cancelled" and "publishAt" in http.resource["status"]
    await service.publish_post(post["id"])
    assert (await service.get_post("user-1", post["id"]))["status"] == "cancelled"
    response = await client.delete(f"/social/connections/{post['social_account_id']}", headers=auth_headers)
    assert response.status_code == 200


async def test_failed_native_history_cannot_erase_unconfirmed_remote_schedule(native, db_session, client, auth_headers):
    service, post, http, _ = native
    await scheduled(native, db_session)
    await db_session.execute(text("UPDATE social_posts SET status='failed' WHERE id=:id"), {"id":post["id"]})
    await db_session.commit()
    response = await client.delete(f"/social/posts/{post['id']}", headers=auth_headers)
    assert response.status_code == 400
    assert (await service.get_post("user-1", post["id"]))["external_post_id"] == "video-1"


async def test_missing_scheduled_video_stops_polling_after_a_bound(native, db_session, monkeypatch):
    service, post, http, _ = native
    await scheduled(native, db_session)
    http.resource = {}
    await db_session.execute(text("UPDATE youtube_uploads SET processing_started_at=NOW()-INTERVAL '7 hours',schedule_requested_at=NOW()-INTERVAL '7 hours',next_attempt_at=NOW() WHERE post_id=:id"), {"id":post["id"]})
    await db_session.commit()
    await service.publish_post(post["id"])
    result = await service.get_post("user-1", post["id"])
    assert result["status"] == "failed" and result["reason_code"] == "video_unavailable"


async def test_second_reconciliation_preserves_adopted_studio_time(native, db_session):
    service, post, http, _ = native
    result = await scheduled(native, db_session)
    moved = datetime.fromisoformat(result["scheduled_for"]) + timedelta(days=1)
    http.resource["status"]["publishAt"] = moved.isoformat()
    for _ in range(2):
        await due(db_session, post["id"])
        await service.publish_post(post["id"])
    result = await service.get_post("user-1", post["id"])
    assert datetime.fromisoformat(result["scheduled_for"]) == moved and len(updates(http)) == 1


async def test_native_publication_intent_checks_metered_scheduling_access(review_item, client, auth_headers, app, monkeypatch):
    item, _, _, _ = review_item
    monkeypatch.setattr(SocialService, "can_schedule", lambda *_a: _false())
    response = await client.post(f"/social/review/{item['id']}/approve", headers=auth_headers, json={"expected_version":item["version"]})
    assert response.status_code == 402

async def _false():
    return False


async def test_native_backlog_does_not_starve_other_provider_polling(native, db_session):
    service, post, http, _ = native
    await service.publish_post(post["id"])
    await db_session.execute(text("UPDATE social_posts SET updated_at=NOW()-INTERVAL '1 day' WHERE id=:id"), {"id":post["id"]})
    second = str(uuid.uuid4())
    await db_session.execute(text("""
      INSERT INTO social_posts(id,user_id,task_id,clip_id,social_account_id,provider,status,pending_handle)
      SELECT :new,user_id,task_id,clip_id,social_account_id,'tiktok','publishing','accepted-tiktok' FROM social_posts WHERE id=:id
    """), {"new":second,"id":post["id"]})
    await db_session.commit()
    rows = await service.repo.list_pending_publishes(db_session, limit=1)
    assert [row["id"] for row in rows] == [second]


async def test_destination_active_query_cannot_hide_a_schedule_behind_history(native, db_session, client, auth_headers):
    service, post, http, _ = native
    await scheduled(native, db_session)
    await db_session.execute(text("""
      INSERT INTO social_posts(id,user_id,task_id,clip_id,social_account_id,provider,status,title,created_at)
      SELECT 'history-' || n,user_id,task_id,clip_id,social_account_id,'youtube','published','Newer history',NOW()+INTERVAL '1 day'
      FROM social_posts CROSS JOIN generate_series(1,201) n WHERE id=:id
    """), {"id":post["id"]})
    await db_session.commit()
    response = await client.get(f"/social/posts?account_id={post['social_account_id']}&status_group=active&limit=100", headers=auth_headers)
    assert response.status_code == 200
    assert [p["id"] for p in response.json()["posts"]] == [post["id"]]
