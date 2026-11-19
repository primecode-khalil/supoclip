"""Real checkpoint transactions fence workers and protect private session URLs."""
import asyncio

import pytest
from sqlalchemy import text

from src.database import AsyncSessionLocal
from src.runtime_settings import decrypt_setting_value, encrypt_setting_value
from src.services.social_service import SocialService
from src.repositories.youtube_upload_repository import YouTubeUploadRepository as Uploads
from tests.integration.test_social_publishing import social_setup  # noqa: F401


@pytest.fixture
async def upload_post(social_setup, client, auth_headers):
    _, payload = social_setup
    response = await client.post("/social/posts", headers=auth_headers, json=payload)
    assert response.status_code == 200
    return response.json()["post"]


async def test_private_checkpoint_and_lease_fence(upload_post, db_session, client, auth_headers):
    post_id = upload_post["id"]
    await Uploads.ensure(db_session, post_id, "user-1", "a" * 64, 10, {"status": {"privacyStatus": "private"}})
    first = await Uploads.claim(db_session, post_id)
    assert first and first["lease_token"]
    async with AsyncSessionLocal() as other:
        assert await Uploads.claim(other, post_id) is None
    uri = "https://www.googleapis.com/upload/youtube/v3/videos?upload_id=secret-session"
    assert await Uploads.update(db_session, post_id, first["lease_token"], session_url_encrypted=encrypt_setting_value(uri), stage="uploading")
    row = await Uploads.get(db_session, post_id)
    assert row["session_url_encrypted"] != uri
    assert decrypt_setting_value(row["session_url_encrypted"]) == uri
    public = await client.get(f"/social/posts/{post_id}", headers=auth_headers)
    assert "secret-session" not in public.text and "session_url_encrypted" not in public.text
    await db_session.execute(text("UPDATE youtube_uploads SET lease_expires_at=NOW()-INTERVAL '1 second' WHERE post_id=:id"), {"id": post_id})
    await db_session.commit()
    async with AsyncSessionLocal() as other:
        second = await Uploads.claim(other, post_id)
        assert second and second["lease_token"] != first["lease_token"]
        assert not await Uploads.update(db_session, post_id, first["lease_token"], confirmed_bytes=9)
        assert await Uploads.update(other, post_id, second["lease_token"], confirmed_bytes=4, release=True)
    assert (await Uploads.get(db_session, post_id))["confirmed_bytes"] == 4


async def test_concurrent_workers_get_one_transfer_lease(upload_post, db_session):
    await Uploads.ensure(db_session, upload_post["id"], "user-1", "a" * 64, 10, {})

    async def claim():
        async with AsyncSessionLocal() as other:
            return await Uploads.claim(other, upload_post["id"])

    outcomes = await asyncio.gather(claim(), claim())
    assert sum(value is not None for value in outcomes) == 1


async def test_existing_checkpoint_cannot_be_replaced_by_new_bytes(upload_post, db_session):
    await Uploads.ensure(db_session, upload_post["id"], "user-1", "a" * 64, 10, {"title": "original"})
    await Uploads.ensure(db_session, upload_post["id"], "user-1", "b" * 64, 12, {"title": "changed"})
    row = await Uploads.get(db_session, upload_post["id"])
    assert row["media_sha256"] == "a" * 64 and row["size_bytes"] == 10
    assert row["metadata_snapshot"] == {"title": "original"}


async def _uploader(db_session, post_id):
    from src.social.youtube import YouTubeProvider
    from src.social.youtube_upload import YouTubeUploadError, UploadProgress
    from src.services.youtube_publish_service import YouTubePublishService
    from tests.unit.test_social_providers import FakeResponse, FakeSession, _config

    uri = "https://www.googleapis.com/upload/youtube/v3/videos?upload_id=private-transfer"

    class LostReply(YouTubeProvider):
        send_calls = 0
        observations = []

        def send_upload(self, access_token, session_uri, file_path, offset):
            async def read():
                async with AsyncSessionLocal() as other:
                    return await Uploads.get(other, post_id)

            row = asyncio.run(read())
            self.observations.append((row["bytes_started"], decrypt_setting_value(row["session_url_encrypted"]), db_session.in_transaction()))
            self.send_calls += 1
            raise YouTubeUploadError("Lost response", "temporary", retryable=True)

        def probe_upload(self, access_token, session_uri, size_bytes):
            return UploadProgress(size_bytes, "recovered-video")

    http = FakeSession({("POST", "/upload/youtube/"): FakeResponse(200, headers={"Location": uri})})
    provider = LostReply(_config(), http)
    uploader = YouTubePublishService(SocialService(db_session), provider)
    return uploader, provider, http, uri


async def test_lost_final_response_recovers_same_session_and_video(upload_post, db_session, client, auth_headers):
    uploader, provider, http, uri = await _uploader(db_session, upload_post["id"])
    await uploader.advance(upload_post["id"])
    assert provider.observations == [(True, uri, False)]
    first = await Uploads.get(db_session, upload_post["id"])
    assert first["lease_token"] is None and first["session_url_encrypted"]
    await db_session.execute(text("UPDATE youtube_uploads SET next_attempt_at=NOW() WHERE post_id=:id"), {"id": upload_post["id"]})
    await db_session.commit()
    await uploader.advance(upload_post["id"])
    resumed = await Uploads.get(db_session, upload_post["id"])
    assert resumed["video_id"] == "recovered-video"
    assert provider.send_calls == 1
    assert len(http.calls) == 1
    public = await client.get(f"/social/posts/{upload_post['id']}", headers=auth_headers)
    assert "private-transfer" not in public.text


async def test_changed_bytes_do_not_resume_or_create_another_video(upload_post, db_session):
    from pathlib import Path

    uploader, provider, http, _ = await _uploader(db_session, upload_post["id"])
    await uploader.advance(upload_post["id"])
    path = (await db_session.execute(text("SELECT source_file_path FROM social_posts WHERE id=:id"), {"id": upload_post["id"]})).scalar_one()
    Path(path).write_bytes(b"replacement video with different bytes")
    await db_session.execute(text("UPDATE youtube_uploads SET next_attempt_at=NOW() WHERE post_id=:id"), {"id": upload_post["id"]})
    await db_session.commit()
    await uploader.advance(upload_post["id"])
    row = await Uploads.get(db_session, upload_post["id"])
    assert row["stage"] == "needs_attention" and row["reason_code"] == "media_changed"
    assert provider.send_calls == 1 and len(http.calls) == 1


async def test_lost_empty_session_can_restart_without_ever_sending_bytes(upload_post, db_session):
    uploader, provider, http, _ = await _uploader(db_session, upload_post["id"])
    # A worker claimed the post but died before receiving a session URI.
    original = provider.start_upload

    def crash(*args, **kwargs):
        raise asyncio.CancelledError()

    provider.start_upload = crash
    with pytest.raises(asyncio.CancelledError):
        await uploader.advance(upload_post["id"])
    row = await Uploads.get(db_session, upload_post["id"])
    assert row["bytes_started"] is False and row["session_url_encrypted"] is None
    await db_session.execute(text("UPDATE youtube_uploads SET lease_expires_at=NOW()-INTERVAL '1 second', next_attempt_at=NOW() WHERE post_id=:id"), {"id": upload_post["id"]})
    await db_session.commit()
    provider.start_upload = original
    await uploader.advance(upload_post["id"])
    assert provider.send_calls == 1 and len(http.calls) == 1


async def test_stale_worker_cannot_revoke_a_new_workers_connection(upload_post, db_session):
    from src.social.youtube_upload import YouTubeUploadError

    post_id = upload_post["id"]
    uploader, _, _, _ = await _uploader(db_session, post_id)
    await Uploads.ensure(db_session, post_id, "user-1", "a" * 64, 10, {})
    first = await Uploads.claim(db_session, post_id)
    await db_session.execute(text("UPDATE youtube_uploads SET lease_expires_at=NOW()-INTERVAL '1 second' WHERE post_id=:id"), {"id": post_id})
    await db_session.commit()
    assert await Uploads.claim(db_session, post_id)
    account = await uploader.social.repo.get_account_with_tokens(db_session, upload_post["social_account_id"])
    await uploader._failure(upload_post, account, first, YouTubeUploadError("Expired access", "reconnect_required", reauth=True))
    assert (await uploader.social.repo.get_account_with_tokens(db_session, account["id"]))["status"] == "active"
