"""Real ledger + native API acceptance test, with provider/network jobs isolated."""
import hashlib

import httpx
from sqlalchemy import text

from src.recording.automation_schema import AutomationPolicy
from src.recording.automation_store import AutomationStore
from src.recording.pipeline import NativeClient
from src.recording.runner import AutomationPipeline, store_call
from tests.integration.test_social_publishing import social_setup  # noqa: F401
from tests.fixtures.factories import create_clip
from tests.unit.test_social_service import FakeQueue


async def test_restart_reuses_upload_task_and_publication(
    social_setup, client, app, auth_headers, db_session, tmp_path, monkeypatch,
):
    _, connected = social_setup
    channel = (await client.post("/recording/channels", headers=auth_headers, json={"platform": "twitch", "handle": "demo", "name": "Demo"})).json()
    policy = AutomationPolicy(enabled=True, social_account_ids=[connected["social_account_id"]])
    store = AutomationStore(db_session)
    await store.put_policy("user-1", channel["id"], policy)
    lease = await store.acquire(channel["id"], "test-worker")
    session = await store.create_or_resume_session(lease)
    channels = [item for item in await store.list_enabled_channels() if item.channel_id == channel["id"]]
    source = tmp_path / "recordings" / "window.mp4"
    source.parent.mkdir()
    source.write_bytes(b"test completed recording window")
    window = await store.register_window(lease, session.id, "epoch", 0, "window.mp4", hashlib.sha256(source.read_bytes()).hexdigest(), source.stat().st_size, 0.0, 600.0, metadata={"policy": policy.model_dump(), "segments": []})

    async def duration(*args):
        return 600.0

    monkeypatch.setattr("src.api.routes.tasks._preflight_upload_source", duration)
    monkeypatch.setattr("src.workers.job_queue.JobQueue.enqueue_job", FakeQueue().enqueue_job)
    app.state.config.temp_dir = str(tmp_path / "uploads")
    async with NativeClient("http://test", "test-backend-auth-secret", transport=httpx.ASGITransport(app=app)) as native:
        first_process = AutomationPipeline(source.parent, native)
        await first_process.step(channels[0], lease, window)
        window = (await store_call("list_windows", "user-1", channel["id"]))["windows"][0]
        assert window.task_id and window.upload_ref and window.status == "processing"
        task_id = window.task_id
        await first_process.step(channels[0], lease, window)
        assert (await store_call("list_windows", "user-1", channel["id"]))["windows"][0].task_id == task_id
        clip = await create_clip(db_session, task_id=task_id)
        media = tmp_path / "polished.mp4"
        media.write_bytes(b"rendered fixture")
        await db_session.execute(text("UPDATE generated_clips SET file_path=:file,virality_score=95,start_time='01:00',end_time='01:40' WHERE id=:id"), {"file": str(media), "id": clip["id"]})
        await db_session.execute(text("UPDATE tasks SET status='completed',completed_at=NOW() WHERE id=:id"), {"id": task_id})
        await db_session.commit()
        # A fresh Python object uses the persisted receipts, not memory state.
        restarted = AutomationPipeline(source.parent, native)
        await restarted.step(channels[0], lease, window)
        window = (await store_call("list_windows", "user-1", channel["id"]))["windows"][0]
        assert window.status == "publishing", window.last_error
        posts = (await db_session.execute(text("SELECT id FROM social_posts WHERE task_id=:id"), {"id": task_id})).scalars().all()
        assert len(posts) == 1
        await restarted.step(channels[0], lease, window)
        assert (await db_session.execute(text("SELECT count(*) FROM social_posts WHERE task_id=:id"), {"id": task_id})).scalar_one() == 1
        await db_session.execute(text("UPDATE social_posts SET status='published',published_at=NOW() WHERE id=:id"), {"id": posts[0]})
        await db_session.commit()
        await restarted.step(channels[0], lease, window)
        assert await store_call("list_pending", lease) == []
