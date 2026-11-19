"""An accepted upload is not published until Google confirms its outcome."""
import requests
import pytest
from sqlalchemy import text

from src.services import social_service as module
from src.services.social_service import SocialService
from src.social.youtube import YouTubeProvider
from tests.integration.test_social_publishing import social_setup  # noqa: F401
from tests.unit.test_social_providers import FakeResponse, FakeSession


def video(*, visibility="private", processing="succeeded", uploaded="processed", channel="chan-1"):
    return {"items": [{"id": "video-1", "snippet": {"channelId": channel},
        "status": {"privacyStatus": visibility, "uploadStatus": uploaded},
        "processingDetails": {"processingStatus": processing}}]}


@pytest.fixture
async def lifecycle(social_setup, client, auth_headers, db_session, app, monkeypatch):
    _, payload = social_setup
    response = await client.post("/social/posts", headers=auth_headers, json=payload)
    post = response.json()["post"]
    app.state.config.youtube_oauth_client_id = "test-client"
    app.state.config.youtube_oauth_client_secret = "test-secret"
    http = FakeSession({
        ("POST", "/upload/youtube/"): FakeResponse(200, headers={"Location": "https://www.googleapis.com/upload/youtube/v3/videos?upload_id=secret-uri"}),
        ("PUT", "upload_id="): FakeResponse(201, {"id": "video-1"}),
        ("GET", "/youtube/v3/videos"): FakeResponse(200, video()),
        ("POST", "oauth2.googleapis.com/token"): FakeResponse(200, {"access_token": "fresh-access", "expires_in": 3600}),
    })
    provider = YouTubeProvider(app.state.config, http)
    monkeypatch.setattr(module, "get_provider", lambda *_args, **_kw: provider)
    return SocialService(db_session, app.state.config), post, http


async def due(db, post_id):
    await db.execute(text("UPDATE youtube_uploads SET next_attempt_at=NOW() WHERE post_id=:id"), {"id": post_id})
    await db.commit()


def inserts(http):
    return sum(method == "POST" and "/upload/youtube/" in url for method, url, _ in http.calls)


async def test_processing_is_polled_after_id_is_saved(lifecycle, db_session, client, auth_headers):
    service, post, http = lifecycle
    http.routes[("GET", "/youtube/v3/videos")] = [FakeResponse(200, video(processing="processing", uploaded="uploaded")), FakeResponse(200, video())]
    accepted = await service.publish_post(post["id"])
    assert accepted["status"] == "publishing" and accepted["stage"] == "processing"
    assert accepted["external_post_id"] == "video-1"
    await due(db_session, post["id"])
    assert await service.resolve_pending_posts() == 1
    assert (await service.get_post("user-1", post["id"]))["status"] == "publishing"
    await due(db_session, post["id"])
    await service.resolve_pending_posts()
    finished = await service.get_post("user-1", post["id"])
    assert finished["status"] == "published" and finished["stage"] == "ready"
    assert finished["actual_visibility"] == "private"
    assert inserts(http) == 1
    assert (await client.get("/social/youtube/setup", headers=auth_headers)).json()["private_test_completed"] is True


@pytest.mark.parametrize("response,reason", [(video(uploaded="rejected", processing="terminated"), "processing_rejected"),
    (video(visibility="public"), "visibility_mismatch"), (video(channel="other-channel"), "destination_mismatch")])
async def test_processing_rejection_or_changed_destination_never_reuploads(lifecycle, db_session, response, reason):
    service, post, http = lifecycle
    http.routes[("GET", "/youtube/v3/videos")] = FakeResponse(200, response)
    await service.publish_post(post["id"])
    await due(db_session, post["id"])
    await service.resolve_pending_posts()
    result = await service.get_post("user-1", post["id"])
    assert result["status"] == "failed" and result["reason_code"] == reason
    assert result["external_post_id"] == "video-1"
    await service.retry_post("user-1", post["id"])
    await service.publish_post(post["id"])
    assert inserts(http) == 1


async def test_missing_status_waits_but_is_bounded(lifecycle, db_session):
    service, post, http = lifecycle
    http.routes[("GET", "/youtube/v3/videos")] = FakeResponse(200, {"items": []})
    await service.publish_post(post["id"])
    await due(db_session, post["id"])
    await service.resolve_pending_posts()
    assert (await service.get_post("user-1", post["id"]))["status"] == "publishing"
    await db_session.execute(text("UPDATE youtube_uploads SET processing_started_at=NOW()-INTERVAL '7 hours',next_attempt_at=NOW() WHERE post_id=:id"), {"id": post["id"]})
    await db_session.commit()
    await service.resolve_pending_posts()
    assert (await service.get_post("user-1", post["id"]))["reason_code"] == "processing_timeout"
    assert inserts(http) == 1


async def test_accepted_upload_reconciles_after_library_deletion(lifecycle, db_session, client, auth_headers):
    service, post, http = lifecycle
    await service.publish_post(post["id"])
    deleted = await client.delete(f"/tasks/{post['task_id']}", headers=auth_headers)
    assert deleted.status_code == 200
    await due(db_session, post["id"])
    await service.resolve_pending_posts()
    result = await service.get_post("user-1", post["id"])
    assert result["status"] == "published" and result["clip_id"] is None
    assert inserts(http) == 1


async def test_401_refreshes_once_and_resumes_the_same_session(lifecycle, db_session):
    service, post, http = lifecycle
    http.routes[("PUT", "upload_id=")] = [FakeResponse(401, {"error": {"errors": [{"reason": "authError"}]}}),
        FakeResponse(308), FakeResponse(201, {"id": "video-1"})]
    result = await service.publish_post(post["id"])
    assert result["status"] == "publishing"
    await due(db_session, post["id"])
    await service.resolve_pending_posts()
    assert (await service.get_post("user-1", post["id"]))["external_post_id"] == "video-1"
    assert inserts(http) == 1
    assert sum("oauth2.googleapis.com/token" in url for _, url, _ in http.calls) == 1


async def test_unmarked_legacy_upload_is_not_automatically_restarted(lifecycle, db_session):
    service, post, http = lifecycle
    await db_session.execute(text("UPDATE social_posts SET status='publishing',claimed_at=NOW()-INTERVAL '10 minutes' WHERE id=:id"), {"id": post["id"]})
    await db_session.commit()
    result = await service.publish_post(post["id"])
    assert result["status"] == "publishing" and http.calls == []


async def test_disabled_publishing_sends_no_upload_bytes(lifecycle):
    service, post, http = lifecycle
    service.config.social_publishing_access = "off"
    result = await service.publish_post(post["id"])
    assert result["status"] == "failed" and http.calls == []


async def test_disconnect_after_acceptance_explains_reconnection_without_reupload(lifecycle, db_session):
    service, post, http = lifecycle
    http.routes[("POST", "oauth2.googleapis.com/revoke")] = FakeResponse(200, {})
    await service.publish_post(post["id"])
    assert await service.disconnect("user-1", post["social_account_id"])
    await due(db_session, post["id"])
    await service.resolve_pending_posts()
    result = await service.get_post("user-1", post["id"])
    assert result["stage"] == "reconnect_required" and result["external_post_id"] == "video-1"
    assert inserts(http) == 1


async def test_processing_network_error_waits_without_losing_the_video(lifecycle, db_session, monkeypatch, caplog):
    service, post, http = lifecycle
    await service.publish_post(post["id"])
    original = http.get

    def interrupted(*args, **kwargs):
        raise requests.Timeout("https://www.googleapis.com/private?upload_id=secret-uri")

    monkeypatch.setattr(http, "get", interrupted)
    await due(db_session, post["id"])
    await service.resolve_pending_posts()
    result = await service.get_post("user-1", post["id"])
    assert result["status"] == "publishing" and result["stage"] == "processing"
    assert result["external_post_id"] == "video-1"
    assert "secret-uri" not in str(result) and "secret-uri" not in caplog.text
    monkeypatch.setattr(http, "get", original)
    await due(db_session, post["id"])
    await service.resolve_pending_posts()
    assert (await service.get_post("user-1", post["id"]))["status"] == "published"
    assert inserts(http) == 1
