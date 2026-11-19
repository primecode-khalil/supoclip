"""Library deletion removes linked future uploads, with explicit warning and durable proof."""
import pytest
import requests
from sqlalchemy import text

from tests.integration.test_youtube_native_scheduling import native, review_item, social_setup, short_file, scheduled, inserts  # noqa: F401
from tests.integration.test_youtube_publication_lifecycle import due
from tests.unit.test_social_providers import FakeResponse


@pytest.fixture
async def deletion(native, monkeypatch):
    service, post, http, path = native
    http.lose_delete = False
    http.reject_delete = False

    def remove(url, **kwargs):
        http.calls.append(("DELETE", url, kwargs))
        if http.reject_delete:
            return FakeResponse(503, {})
        http.resource = {}
        if http.lose_delete:
            http.lose_delete = False
            raise requests.Timeout("lost delete reply")
        return FakeResponse(204, {})

    monkeypatch.setattr(http, "delete", remove, raising=False)
    return native


async def delete_source(client, headers, post, *, clip=False):
    endpoint = f"/tasks/{post['task_id']}" + (f"/clips/{post['clip_id']}" if clip else "")
    return await client.delete(endpoint+"?confirm_social_delete=true", headers=headers)


async def test_delete_requires_warning_ack_and_previews_only_owned_affected_uploads(deletion, db_session, client, auth_headers):
    service, post, http, path = deletion
    await scheduled(deletion, db_session)
    response = await client.post("/social/deletion-impact", headers=auth_headers, json={"task_ids":[post["task_id"]]})
    assert response.status_code == 200, response.text
    assert [p["id"] for p in response.json()["affected"]] == [post["id"]]
    from tests.integration.test_recording_automation import headers
    other = await client.post("/social/deletion-impact", headers=headers("another-owner"), json={"task_ids":[post["task_id"]]})
    assert other.status_code == 200 and other.json()["affected"] == []
    response = await client.delete(f"/tasks/{post['task_id']}", headers=auth_headers)
    assert response.status_code == 409 and path.exists()
    assert (await service.get_post("user-1",post["id"]))["status"] == "scheduled"


@pytest.mark.parametrize("clip", [False,True])
async def test_confirmed_library_deletion_removes_youtube_copy_and_keeps_receipt(deletion, db_session, client, auth_headers, clip):
    service, post, http, path = deletion
    await scheduled(deletion, db_session)
    response = await delete_source(client, auth_headers, post, clip=clip)
    assert response.status_code == 200, response.text
    pending = await service.get_post("user-1",post["id"])
    assert pending["status"] != "cancelled" and pending["provider_options"]["delete_remote"] is True
    await service.publish_post(post["id"])
    result = await service.get_post("user-1",post["id"])
    assert result["status"] == "cancelled" and result["stage"] == "deleted"
    assert result["external_post_id"] == "video-1" and result["clip_id"] is None
    assert http.resource == {} and inserts(http) == 1
    assert sum(method == "DELETE" for method,_,_ in http.calls) == 1


async def test_lost_delete_response_recovers_absence_without_reupload(deletion, db_session, client, auth_headers):
    service, post, http, _ = deletion
    await scheduled(deletion, db_session)
    await delete_source(client, auth_headers, post)
    http.lose_delete = True
    await service.publish_post(post["id"])
    assert (await service.get_post("user-1",post["id"]))["stage"] != "deleted"
    await due(db_session, post["id"])
    await service.publish_post(post["id"])
    assert (await service.get_post("user-1",post["id"]))["stage"] == "deleted"
    assert inserts(http) == 1 and sum(m == "DELETE" for m,_,_ in http.calls) == 1


async def test_remote_error_leaves_deletion_pending_with_id_and_retry(deletion, db_session, client, auth_headers):
    service, post, http, _ = deletion
    await scheduled(deletion, db_session)
    await delete_source(client, auth_headers, post)
    http.reject_delete = True
    await service.publish_post(post["id"])
    result = await service.get_post("user-1",post["id"])
    assert result["status"] != "cancelled" and result["provider_options"]["delete_remote"] is True
    assert result["external_post_id"] == "video-1" and http.resource
    http.reject_delete = False
    await due(db_session, post["id"])
    await service.publish_post(post["id"])
    assert (await service.get_post("user-1",post["id"]))["stage"] == "deleted"


async def test_orphaned_approval_from_deletion_race_is_removed_remotely(deletion, db_session):
    service, post, http, _ = deletion
    await scheduled(deletion, db_session)
    await db_session.execute(text("UPDATE social_posts SET clip_id=NULL WHERE id=:id"), {"id":post["id"]})
    await db_session.commit()
    await due(db_session,post["id"])
    await service.publish_post(post["id"])
    assert (await service.get_post("user-1",post["id"]))["stage"] == "deleted" and http.resource == {}


async def test_selected_scheduled_copy_that_publishes_during_removal_is_still_deleted(deletion, db_session, client, auth_headers):
    service, post, http, _ = deletion
    await scheduled(deletion, db_session)
    await delete_source(client, auth_headers, post)
    http.resource["status"] = {"privacyStatus":"public","uploadStatus":"processed"}
    await service.publish_post(post["id"])
    result = await service.get_post("user-1",post["id"])
    assert result["stage"] == "deleted" and http.resource == {}


async def test_unstarted_work_cancels_without_creating_a_youtube_video(deletion, client, auth_headers):
    service, post, http, _ = deletion
    assert (await delete_source(client,auth_headers,post)).status_code == 200
    result = await service.publish_post(post["id"])
    assert result["status"] == "cancelled" and http.calls == []

async def test_deleting_a_cancelled_private_copy_removes_it_from_youtube(deletion, db_session, client, auth_headers):
    service, post, http, _ = deletion
    await scheduled(deletion,db_session)
    await service.cancel_post("user-1",post["id"])
    await service.publish_post(post["id"])
    assert (await service.get_post("user-1",post["id"]))["status"] == "cancelled" and http.resource
    impact = await client.post("/social/deletion-impact",headers=auth_headers,json={"task_ids":[post["task_id"]]})
    assert len(impact.json()["affected"]) == 1
    await delete_source(client,auth_headers,post)
    await service.publish_post(post["id"])
    assert (await service.get_post("user-1",post["id"]))["stage"] == "deleted" and http.resource == {}


async def test_source_deletion_recovers_attention_checkpoint_and_bypasses_processing_timeout(deletion, db_session, client, auth_headers):
    service, post, http, _ = deletion
    await service.publish_post(post["id"])
    await db_session.execute(text("UPDATE youtube_uploads SET stage='needs_attention',reason_code='processing_timeout',processing_started_at=NOW()-INTERVAL '7 hours',next_attempt_at=NULL WHERE post_id=:id"), {"id":post["id"]})
    await db_session.execute(text("UPDATE social_posts SET status='failed' WHERE id=:id"), {"id":post["id"]})
    await db_session.commit()
    await delete_source(client,auth_headers,post)
    assert post["id"] in [p["id"] for p in await service.repo.native_jobs_due(db_session)]
    await service.publish_post(post["id"])
    assert (await service.get_post("user-1",post["id"]))["stage"] == "deleted" and http.resource == {}

async def test_account_deletion_requests_remote_removal_before_revoking_access(deletion, db_session, client, auth_headers):
    service, post, http, _ = deletion
    await scheduled(deletion,db_session)
    http.routes[("POST","oauth2.googleapis.com/revoke")] = FakeResponse(200,{})
    response = await client.delete("/social/connections",headers=auth_headers)
    assert response.status_code == 409
    assert (await service.get_post("user-1",post["id"]))["provider_options"]["delete_remote"] is True
    await service.publish_post(post["id"])
    assert http.resource == {} and (await service.get_post("user-1",post["id"]))["stage"] == "deleted"
    assert (await client.delete("/social/connections",headers=auth_headers)).status_code == 200

async def test_all_bytes_accepted_without_an_id_never_claims_remote_deletion_complete(deletion, db_session, client, auth_headers):
    service, post, http, path = deletion
    http.routes[("PUT","upload_id=")] = FakeResponse(308,headers={"Range":f"bytes=0-{path.stat().st_size-1}"})
    await service.publish_post(post["id"])
    await delete_source(client,auth_headers,post)
    result = await service.publish_post(post["id"])
    assert result["status"] != "cancelled" and result["stage"] == "needs_attention"
    assert result["reason_code"] == "unknown_outcome" and inserts(http) == 1


async def test_unstarted_orphan_can_finish_without_a_destination_connection(deletion, db_session, client, auth_headers):
    service, post, http, _ = deletion
    await db_session.execute(text("UPDATE social_posts SET social_account_id=NULL WHERE id=:id"), {"id":post["id"]})
    await db_session.commit()
    await delete_source(client,auth_headers,post)
    result = await service.publish_post(post["id"])
    assert result["status"] == "cancelled" and not http.calls
