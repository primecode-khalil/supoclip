"""Approval is explicit, immutable and transactional; rejecting retains media."""
import asyncio
from pathlib import Path

import pytest
from sqlalchemy import text

from tests.integration.test_social_publishing import social_setup  # noqa: F401
from tests.unit.test_social_publication_policy import short_file  # noqa: F401
from tests.integration.test_recording_publication_limit import capped_recording, load_window  # noqa: F401


@pytest.fixture
async def review_item(social_setup, short_file, client, auth_headers, db_session, app):
    _, payload = social_setup
    path = short_file()
    await db_session.execute(text("UPDATE generated_clips SET file_path=:path,duration=1,virality_score=90,updated_at=clock_timestamp() WHERE id=:id"),
        {"path": path, "id": payload["clip_id"]})
    await db_session.execute(text("UPDATE social_accounts SET scopes=:scope WHERE id=:id"),
        {"scope": "https://www.googleapis.com/auth/youtube.force-ssl", "id": payload["social_account_id"]})
    await db_session.commit()
    before = len(app.state.queue_adapter.enqueued_jobs)
    imported = await client.post("/social/review/import", headers=auth_headers,
        json={"account_id": payload["social_account_id"], "clip_ids": [payload["clip_id"]]})
    assert imported.status_code == 200, imported.text
    listed = await client.get(f"/social/review?account_id={payload['social_account_id']}", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    assert len(app.state.queue_adapter.enqueued_jobs) == before
    return listed.json()["items"][0], payload, Path(path), before


async def test_review_is_owner_only_and_reject_undo_keep_the_clip(review_item, client, auth_headers, db_session, app):
    item, payload, path, before = review_item
    assert (await client.post(f"/social/review/{item['id']}/reject")).status_code == 401
    response = await client.post(f"/social/review/{item['id']}/reject", headers=auth_headers, json={})
    assert response.status_code == 200
    assert response.json()["item"]["status"] == "rejected"
    assert path.exists()
    assert (await db_session.execute(text("SELECT count(*) FROM social_posts WHERE social_account_id=:id"), {"id": payload["social_account_id"]})).scalar_one() == 0
    assert len(app.state.queue_adapter.enqueued_jobs) == before
    undone = await client.post(f"/social/review/{item['id']}/undo", headers=auth_headers, json={})
    assert undone.status_code == 200 and undone.json()["item"]["status"] == "pending"


async def test_approve_reserves_a_native_publication_and_is_idempotent(review_item, client, auth_headers, db_session, app):
    item, payload, path, before = review_item
    body = {"expected_version": item["version"], "title": "Approved highlight", "caption": "A complete thought"}
    first = await client.post(f"/social/review/{item['id']}/approve", headers=auth_headers, json=body)
    assert first.status_code == 200, first.text
    data = first.json()
    assert data["item"]["status"] == "approved" and data["item"]["publish_at"]
    assert data["post"]["status"] == "queued"  # Upload privately now; publish on YouTube later.
    assert data["post"]["title"] == "Approved highlight"
    assert data["post"]["scheduled_for"] == data["item"]["publish_at"]
    again = await client.post(f"/social/review/{item['id']}/approve", headers=auth_headers, json=body)
    assert again.status_code == 200 and again.json()["post"]["id"] == data["post"]["id"]
    assert len(app.state.queue_adapter.enqueued_jobs) == before + 1
    assert (await db_session.execute(text("SELECT count(*) FROM social_publication_slots WHERE review_id=:id"), {"id": item["id"]})).scalar_one() == 1
    stored = (await db_session.execute(text("SELECT provider_options,source_file_path FROM social_posts WHERE id=:id"), {"id": data["post"]["id"]})).mappings().one()
    assert stored["provider_options"]["native_schedule"] is True
    assert stored["provider_options"]["review"]["version"] == item["version"]
    assert stored["source_file_path"] == str(path)
    assert (await client.post(f"/social/review/{item['id']}/reject", headers=auth_headers, json={})).status_code == 409


async def test_concurrent_approval_creates_one_post_and_one_reservation(review_item, client, auth_headers, db_session):
    item, _, _, _ = review_item
    responses = await asyncio.gather(*(client.post(f"/social/review/{item['id']}/approve", headers=auth_headers,
        json={"expected_version": item["version"]}) for _ in range(2)))
    assert all(response.status_code == 200 for response in responses), [r.text for r in responses]
    assert responses[0].json()["post"]["id"] == responses[1].json()["post"]["id"]
    assert (await db_session.execute(text("SELECT count(*) FROM social_publication_slots WHERE review_id=:id"), {"id": item["id"]})).scalar_one() == 1


async def test_changed_preview_cannot_be_approved_as_the_old_render(review_item, client, auth_headers, db_session, app):
    item, payload, path, before = review_item
    replacement = path.with_name("replacement.mp4")
    replacement.write_bytes(path.read_bytes())
    await db_session.execute(text("UPDATE generated_clips SET file_path=:path,updated_at=clock_timestamp() WHERE id=:id"), {"id": payload["clip_id"], "path": str(replacement)})
    await db_session.commit()
    response = await client.post(f"/social/review/{item['id']}/approve", headers=auth_headers, json={"expected_version": item["version"]})
    assert response.status_code == 409
    assert len(app.state.queue_adapter.enqueued_jobs) == before
    refreshed = (await client.get(f"/social/review?account_id={payload['social_account_id']}", headers=auth_headers)).json()["items"][0]
    assert refreshed["version"] != item["version"]


async def test_policy_pause_blocks_approval_without_losing_review(review_item, client, auth_headers):
    item, payload, _, _ = review_item
    result = await client.put(f"/social/accounts/{payload['social_account_id']}/automation", headers=auth_headers, json={"uploads_paused": True})
    assert result.status_code == 200
    response = await client.post(f"/social/review/{item['id']}/approve", headers=auth_headers, json={"expected_version": item["version"]})
    assert response.status_code == 409
    assert (await client.get(f"/social/review?account_id={payload['social_account_id']}", headers=auth_headers)).json()["items"][0]["id"] == item["id"]


async def test_another_owner_cannot_view_or_decide_the_review(review_item, client):
    from tests.integration.test_recording_automation import headers

    item, payload, _, _ = review_item
    other = headers("another-owner")
    assert (await client.get(f"/social/review?account_id={payload['social_account_id']}", headers=other)).status_code == 404
    for action in ["approve", "reject", "undo"]:
        response = await client.post(f"/social/review/{item['id']}/{action}", headers=other, json={"expected_version": item["version"]} if action == "approve" else {})
        assert response.status_code == 404


@pytest.mark.parametrize("admit_existing", [True, False])
async def test_live_windows_hand_off_to_review_without_uploading_or_blocking_capture(capped_recording, client, auth_headers, db_session, admit_existing):
    from src.workers.recording_supervisor import ChannelRunner, RuntimeSettings

    channel, token, window, pipeline, native, clips, source, queue = capped_recording
    account = channel.policy.social_account_ids[0]
    response = await client.put(f"/social/accounts/{account}/automation", headers=auth_headers, json={"mode": "review"})
    assert response.status_code == 200
    if admit_existing:
        await db_session.execute(text("UPDATE social_publication_policies SET enabled_at=NOW()-INTERVAL '1 hour' WHERE account_id=:id"), {"id": account})
        await db_session.commit()
    before = len([job for job in queue.jobs if job[0] == "publish_social_post"])
    await pipeline.step(channel, token, window)
    row = await load_window(channel.channel_id)
    assert row.status == "completed"
    assert len(row.details.get("review_ids", [])) == (2 if admit_existing else 0)
    assert len([job for job in queue.jobs if job[0] == "publish_social_post"]) == before
    assert row.details["policy"]["max_posts_per_day"] == 1  # The saved source policy was retained.
    assert source.exists()
    runner = ChannelRunner(channel, token, RuntimeSettings(source.parent, 0, 1, 24), pipeline)
    assert await runner._backlog() == 0


async def test_review_snapshot_is_retained_until_a_decision(review_item, client, auth_headers, db_session, app):
    from src.media_storage import MediaStorage
    from src.workers.media_cleanup import reference_index

    item, payload, old, _ = review_item
    replacement = old.with_name("new-render.mp4")
    replacement.write_bytes(old.read_bytes())
    await db_session.execute(text("UPDATE generated_clips SET file_path=:path,updated_at=clock_timestamp() WHERE id=:id"), {"id": payload["clip_id"], "path": str(replacement)})
    await db_session.commit()
    assert str(old) in (await reference_index(db_session, MediaStorage(app.state.config)))["clips"]
    await db_session.commit()
    await client.post(f"/social/review/{item['id']}/reject", headers=auth_headers, json={})
    assert str(old) not in (await reference_index(db_session, MediaStorage(app.state.config)))["clips"]
    assert old.exists() and replacement.exists()


async def test_approved_render_is_frozen_when_the_library_clip_is_edited(review_item, client, auth_headers, db_session, app):
    from datetime import datetime, timezone
    from src.media_storage import MediaStorage
    from src.repositories.social_repository import SocialRepository
    from src.workers.media_cleanup import reference_index

    item, payload, approved_path, _ = review_item
    response = await client.post(f"/social/review/{item['id']}/approve", headers=auth_headers, json={"expected_version": item["version"]})
    assert response.status_code == 200
    post_id = response.json()["post"]["id"]
    new_path = approved_path.with_name("edited-after-approval.mp4")
    new_path.write_bytes(approved_path.read_bytes())
    await db_session.execute(text("UPDATE generated_clips SET file_path=:path,updated_at=clock_timestamp() WHERE id=:id"), {"id": payload["clip_id"], "path": str(new_path)})
    await db_session.commit()
    assert str(approved_path) in (await reference_index(db_session, MediaStorage(app.state.config)))["clips"]
    await db_session.commit()
    claimed = await SocialRepository.claim_post(db_session, post_id, media_token_expires_at=datetime.now(timezone.utc))
    assert claimed["source_file_path"] == str(approved_path)

async def test_failed_approved_upload_retains_its_render_for_retry_after_library_edit(review_item, client, auth_headers, db_session, app):
    from src.media_storage import MediaStorage
    from src.workers.media_cleanup import reference_index, referenced
    item, payload, original, _ = review_item
    response = await client.post(f"/social/review/{item['id']}/approve",headers=auth_headers,json={"expected_version":item["version"]})
    post = response.json()["post"]
    edited = original.with_name("new-library-render.mp4")
    edited.write_bytes(original.read_bytes())
    await db_session.execute(text("UPDATE social_posts SET status='failed',error_message='Temporary upload interruption' WHERE id=:id"), {"id":post["id"]})
    await db_session.execute(text("UPDATE generated_clips SET file_path=:path WHERE id=:id"), {"id":payload["clip_id"],"path":str(edited)})
    await db_session.commit()
    storage = MediaStorage(app.state.config)
    assert str(original) in (await reference_index(db_session,storage))["clips"]
    assert await referenced(db_session,str(original),storage)
