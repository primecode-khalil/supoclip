"""Posting caps must not turn a healthy recorder into a permanent backlog."""
import hashlib
from dataclasses import replace
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import text

from src.database import AsyncSessionLocal
from src.recording.automation_schema import AutomationPolicy
from src.recording.automation_store import AutomationStore, LostLeaseError
from src.recording.errors import RecordingError
from src.recording.pipeline import NativeClient
from src.recording.runner import AutomationPipeline, store_call
from src.workers.recording_supervisor import ChannelRunner, RuntimeSettings
from tests.fixtures.factories import create_clip
from tests.integration.test_social_publishing import social_setup  # noqa: F401
from tests.unit.test_social_service import FakeQueue


@pytest.fixture
async def capped_recording(social_setup, client, app, auth_headers, db_session, tmp_path, monkeypatch):
    _, account = social_setup
    response = await client.post("/recording/channels", headers=auth_headers, json={"platform": "twitch", "handle": "cap_demo", "name": "Daily cap demo"})
    assert response.status_code == 201
    channel_id = response.json()["id"]
    policy = AutomationPolicy(enabled=True, max_posts_per_day=1, social_account_ids=[account["social_account_id"]])
    store = AutomationStore(db_session)
    await store.put_policy("user-1", channel_id, policy)
    lease = await store.acquire(channel_id, "cap-worker")
    session = await store.create_or_resume_session(lease)
    channel = next(item for item in await store.list_enabled_channels() if item.channel_id == channel_id)
    root = tmp_path / "recordings"
    root.mkdir()
    source = root / "window.mp4"
    source.write_bytes(b"closed recording fixture")
    window = await store.register_window(lease, session.id, "epoch", 0, source.name,
        hashlib.sha256(source.read_bytes()).hexdigest(), source.stat().st_size, 0.0, 600.0,
        metadata={"policy": policy.model_dump(), "segments": [], "provenance": {"retained": True}})

    async def duration(*args):
        return 600.0

    queue = FakeQueue()
    monkeypatch.setattr("src.api.routes.tasks._preflight_upload_source", duration)
    monkeypatch.setattr("src.workers.job_queue.JobQueue.enqueue_job", queue.enqueue_job)
    app.state.config.temp_dir = str(tmp_path / "uploads")
    async with NativeClient("http://test", "test-backend-auth-secret", transport=httpx.ASGITransport(app=app)) as native:
        pipeline = AutomationPipeline(root, native)
        await pipeline.step(channel, lease, window)
        window = (await store_call("list_windows", "user-1", channel_id))["windows"][0]
        assert window.status == "processing", window.last_error
        task_id = window.task_id
        clips = []
        for index, start in enumerate(("01:00", "03:00"), 1):
            clip = await create_clip(db_session, task_id=task_id, text_value=f"Polished highlight {index}")
            media = tmp_path / f"polished-{index}.mp4"
            media.write_bytes(f"rendered fixture {index}".encode())
            await db_session.execute(text("UPDATE generated_clips SET file_path=:file,start_time=:start,end_time=:end,virality_score=:score,clip_order=:order WHERE id=:id"),
                {"file": str(media), "start": start, "end": f"{int(start[:2]):02d}:40", "score": 96-index, "order": index+1, "id": clip["id"]})
            clips.append(clip["id"])
        await db_session.execute(text("UPDATE tasks SET status='completed',completed_at=NOW(),generated_clips_ids=:clips WHERE id=:id"), {"clips": clips, "id": task_id})
        await db_session.commit()
        try:
            yield channel, lease, window, pipeline, native, clips, source, queue
        finally:
            await db_session.rollback()
            await db_session.execute(text("DELETE FROM recording_channels WHERE id=:id"), {"id": channel_id})
            await db_session.commit()


async def load_window(channel_id):
    return (await store_call("list_windows", "user-1", channel_id))["windows"][0]


async def test_cap_retains_extra_clips_without_deferring_receipts_or_stopping_capture(capped_recording, db_session):
    channel, lease, window, pipeline, native, clips, source, queue = capped_recording
    await pipeline.step(channel, lease, window)
    capped = await load_window(channel.channel_id)
    assert capped.details.get("publication_capped") is True
    assert capped.status == "publishing" and capped.next_attempt_at is None
    assert capped.last_error is None and capped.attempts == window.attempts
    assert capped.details["selected_clip_ids"] == clips
    assert capped.details["policy"] == window.details["policy"]
    assert capped.details["provenance"] == {"retained": True}
    listed = await native.request(channel.user_id, "GET", f"/recording/channels/{channel.channel_id}/windows")
    assert listed["windows"][0]["publication_capped"] is True
    receipts = capped.details["post_ids"]
    assert len(receipts) == 1
    assert (await db_session.execute(text("SELECT count(*) FROM social_posts WHERE task_id=:task"), {"task": capped.task_id})).scalar_one() == 1
    runner = ChannelRunner(channel, lease, RuntimeSettings(source.parent, 0, 1, 24), pipeline)
    assert await runner._backlog() == 1  # Its queued receipt is still unfinished.

    # A restarted recorder honors the durable cap, even after the policy budget
    # changes. It repairs delivery of the first receipt rather than posting #2.
    changed_policy = channel.policy.model_copy(update={"max_posts_per_day": 100})
    await store_call("put_policy", channel.user_id, channel.channel_id, changed_policy)
    await db_session.execute(text("UPDATE social_posts SET created_at=clock_timestamp()-interval '2 days' WHERE id=:id"), {"id": receipts[0]})
    await db_session.commit()
    restarted = AutomationPipeline(source.parent, native)
    await restarted.step(replace(channel, policy=changed_policy), lease, capped)
    capped = await load_window(channel.channel_id)
    assert capped.status == "publishing"
    assert capped.details["post_ids"] == receipts
    assert capped.details["publication_capped"] is True
    assert any(job[0] == "publish_social_post" and job[1] == (receipts[0],) for job in queue.jobs)
    assert (await db_session.execute(text("SELECT count(*) FROM social_posts WHERE task_id=:task"), {"task": capped.task_id})).scalar_one() == 1

    await db_session.execute(text("UPDATE social_posts SET status='published',published_at=NOW() WHERE id=:id"), {"id": receipts[0]})
    await db_session.commit()
    await restarted.step(channel, lease, capped)
    completed = await load_window(channel.channel_id)
    assert completed.status == "completed" and completed.next_attempt_at is None
    assert completed.details["post_ids"] == receipts and completed.details["selected_clip_ids"] == clips
    assert completed.task_id == window.task_id and completed.upload_ref == window.upload_ref
    assert await store_call("list_pending", lease) == []
    assert await runner._backlog() == 0
    result = await native.request(channel.user_id, "GET", f"/tasks/{completed.task_id}/clips")
    assert {item["id"] for item in result["clips"]} == set(clips)
    assert source.is_file() and source.read_bytes() == b"closed recording fixture"


async def test_capped_window_without_receipts_completes_with_both_clips_in_library(capped_recording, db_session):
    channel, lease, window, pipeline, native, clips, source, _ = capped_recording
    # A separate manual publication consumed the owner's daily allowance.
    # Its receipt is not part of this automatic recording window.
    response = await native.request(channel.user_id, "POST", "/social/posts", json={
        "task_id": window.task_id, "clip_id": clips[0],
        "social_account_id": channel.policy.social_account_ids[0], "privacy_level": "private",
    })
    assert response["post"]["id"]
    await pipeline.step(channel, lease, window)
    capped = await load_window(channel.channel_id)
    assert capped.details.get("publication_capped") is True
    assert not capped.details.get("post_ids")
    await AutomationPipeline(source.parent, native).step(channel, lease, capped)
    completed = await load_window(channel.channel_id)
    assert completed.status == "completed"
    assert await ChannelRunner(channel, lease, RuntimeSettings(source.parent, 0, 1, 24), pipeline)._backlog() == 0
    assert (await native.request(channel.user_id, "GET", f"/tasks/{window.task_id}/clips"))["total_clips"] == 2


async def test_atomic_cap_mark_preserves_latest_progress_and_rejects_stale_fence(capped_recording):
    channel, lease, window, _, _, _, _, _ = capped_recording
    window = await store_call("update_window", lease, window.id, status="publishing", attempts=4,
        next_attempt_at=lease.expires_at + timedelta(hours=1), last_error="old retry")
    details = {**window.details, "post_ids": ["persisted-receipt"], "selected_clip_ids": ["candidate"], "post_queue_retries": 1}
    await store_call("update_window", lease, window.id, details=details)
    result = await store_call("mark_publication_capped", lease, window.id)
    assert result.status == "publishing" and result.attempts == 4
    assert result.details == {**details, "publication_capped": True}
    assert result.next_attempt_at is None and result.last_error is None
    with pytest.raises(LostLeaseError):
        await store_call("mark_publication_capped", replace(lease, fence=lease.fence + 1), window.id)
    with pytest.raises(RecordingError):
        await store_call("mark_publication_capped", lease, "missing-window")
    async with AsyncSessionLocal() as db:
        reloaded = await AutomationStore(db).list_windows(channel.user_id, channel.channel_id)
        assert reloaded["windows"][0].details == {**details, "publication_capped": True}
