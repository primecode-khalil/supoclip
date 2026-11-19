"""History cleanup keeps recovery identities, original recordings, and ownership."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import select

from src.database import AsyncSessionLocal
from src.recording.automation_models import RecordingWindow
from src.recording.automation_store import AutomationStore
from src.recording.errors import RecordingError
from src.recording.pipeline import NativeClient
from src.recording.runner import AutomationPipeline
from src.repositories.task_repository import TaskRepository
from src.workers.recording_supervisor import ChannelRunner, RuntimeSettings
from tests.fixtures.factories import create_source, create_task
from tests.integration.test_recording_automation import automated, headers  # noqa: F401
from tests.integration.test_recording_publication_limit import capped_recording  # noqa: F401
from tests.integration.test_social_publishing import social_setup  # noqa: F401


@pytest.fixture
async def history(automated, db_session, tmp_path):
    owner, channel = automated
    store = AutomationStore(db_session)
    token = await store.acquire(channel.id, "history-test", ttl=3600)
    session = await store.create_or_resume_session(token)
    rows = []
    for index in range(3):
        path = tmp_path / f"original-{index}.mkv"
        path.write_bytes(b"captured original")
        window = await store.register_window(token, session.id, "epoch", index, path.name,
            "a" * 64, path.stat().st_size, index * 600, (index + 1) * 600,
            metadata={"policy": {"min_score": 75}, "post_ids": ["retained-receipt"]})
        rows.append(window)
    await store.update_window(token, rows[0].id, status="submitting", upload_ref="upload://retained.mp4")
    await store.update_window(token, rows[0].id, status="blocked", last_error="Provider quota")
    await store.update_window(token, rows[1].id, status="submitting")
    await store.update_window(token, rows[1].id, status="processing")
    await store.update_window(token, rows[1].id, status="completed")
    return owner, channel, token, session, rows, tmp_path


async def test_clear_failed_hides_only_failed_work_and_preserves_recovery(history, client):
    owner, channel, token, session, rows, root = history
    url = f"/recording/channels/{channel.id}/windows"
    auth = headers(owner["id"])
    assert (await client.delete(url + "?scope=failed")).status_code == 401
    assert (await client.delete(url + "?scope=failed", headers=headers("other"))).status_code == 404
    assert (await client.delete(url + "?scope=everything", headers=auth)).status_code == 422
    response = await client.delete(url + "?scope=failed", headers=auth)
    assert response.status_code == 200, response.text
    assert response.json() == {"cleared": 1}
    visible = (await client.get(url + "?limit=1", headers=auth)).json()
    assert visible["total"] == 2 and len(visible["windows"]) == 1
    assert (await client.delete(url + "?scope=failed", headers=auth)).json() == {"cleared": 0}
    async with AsyncSessionLocal() as db:
        store = AutomationStore(db)
        replay = await store.register_window(token, session.id, "epoch", 0, rows[0].source_path,
            "a" * 64, rows[0].size_bytes, 0, 600, metadata={"policy": {"min_score": 75}, "post_ids": ["retained-receipt"]})
        assert replay.id == rows[0].id and replay.upload_ref == "upload://retained.mp4"
        assert replay.details["post_ids"] == ["retained-receipt"]
        assert [w.id for w in await store.list_pending(token, include_blocked=True)] == [rows[2].id]
    assert (await client.post(url + f"/{rows[0].id}/retry", headers=auth)).status_code == 409
    runner = ChannelRunner(SimpleNamespace(channel_id=channel.id), token, RuntimeSettings(root, 0, 1, 24), None)
    assert await runner._backlog() == 1
    assert all((root / row.source_path).read_bytes() == b"captured original" for row in rows)


async def test_clear_finished_keeps_active_work_and_recordings(history, client):
    owner, channel, token, session, rows, root = history
    url = f"/recording/channels/{channel.id}/windows"
    response = await client.delete(url + "?scope=finished", headers=headers(owner["id"]))
    assert response.status_code == 200, response.text
    assert response.json() == {"cleared": 2}
    visible = (await client.get(url, headers=headers(owner["id"]))).json()
    assert visible["total"] == 1 and visible["windows"][0]["id"] == rows[2].id
    async with AsyncSessionLocal() as db:
        retained = (await db.execute(select(RecordingWindow).where(RecordingWindow.channel_id == channel.id))).scalars().all()
        assert len(retained) == 3
        assert all(w.details["post_ids"] == ["retained-receipt"] for w in retained)
    assert len(list(root.glob("*.mkv"))) == 3


async def bind_task(history, db_session):
    owner, channel, token, session, rows, root = history
    source = await create_source(db_session)
    task = await create_task(db_session, user_id=owner["id"], source_id=source["id"])
    await AutomationStore(db_session).update_window(token, rows[2].id, status="submitting")
    await AutomationStore(db_session).update_window(token, rows[2].id, status="processing", task_id=task["id"])
    return task


async def test_library_deletion_clears_attached_work_atomically(history, client, db_session):
    owner, channel, token, session, rows, root = history
    task = await bind_task(history, db_session)
    response = await client.delete(f"/tasks/{task['id']}", headers=headers(owner["id"]))
    assert response.status_code == 200, response.text
    async with AsyncSessionLocal() as db:
        store = AutomationStore(db)
        visible = await store.list_windows(owner["id"], channel.id)
        assert visible["total"] == 2 and rows[2].id not in {w.id for w in visible["windows"]}
        retained = await db.get(RecordingWindow, rows[2].id)
        assert retained.task_id is None and retained.details["history_cleared"] is True
        assert retained.details["post_ids"] == ["retained-receipt"]
        assert await store.list_pending(token) == []
    assert (root / rows[2].source_path).exists()


async def test_failed_library_deletion_rolls_back_history_cleanup(history, client, db_session, monkeypatch):
    owner, channel, token, session, rows, root = history
    task = await bind_task(history, db_session)
    monkeypatch.setattr(TaskRepository, "delete_task", AsyncMock(side_effect=RuntimeError("test deletion failure")))
    response = await client.delete(f"/tasks/{task['id']}", headers=headers(owner["id"]))
    assert response.status_code == 500
    async with AsyncSessionLocal() as db:
        retained = await db.get(RecordingWindow, rows[2].id)
        assert retained.task_id == task["id"] and not retained.details.get("history_cleared")


async def test_stale_worker_cannot_restore_cleared_history(history, client):
    owner, channel, token, session, rows, root = history
    response = await client.delete(f"/recording/channels/{channel.id}/windows?scope=failed", headers=headers(owner["id"]))
    assert response.status_code == 200
    async with AsyncSessionLocal() as db:
        with pytest.raises(RecordingError, match="cleared"):
            await AutomationStore(db).update_window(token, rows[0].id, details={"policy": {"min_score": 75}})
    stale = SimpleNamespace(id=rows[0].id, status="processing", task_id=None)
    requests = []
    async with NativeClient("http://test", "secret", transport=httpx.MockTransport(lambda r: requests.append(r) or httpx.Response(500))) as native:
        await AutomationPipeline(root, native).step(SimpleNamespace(), token, stale)
    assert requests == []


@pytest.mark.parametrize("age_days,archived,removed", [(0.5, True, False), (2, True, True), (2, False, False)])
async def test_cleared_history_obeys_recording_retention(automated, db_session, tmp_path, age_days, archived, removed):
    import json
    import os
    import time
    from src.recording.automation_schema import AutomationPolicy
    from src.recording.capture import ClosedSegment

    owner, registered_channel = automated
    store = AutomationStore(db_session)
    token = await store.acquire(registered_channel.id, "retention-history", ttl=3600)
    session = await store.create_or_resume_session(token)
    policy = AutomationPolicy(enabled=True, retain_days=1, archive=True)
    epoch = tmp_path / registered_channel.id / session.id / "retention-epoch"
    segments = epoch / "segments"
    segments.mkdir(parents=True)
    original = segments / "chunk_000000.mkv"
    original.write_bytes(b"retained capture")
    (epoch / "epoch.json").write_text(json.dumps({"session_id": session.id, "epoch": epoch.name, "policy": policy.model_dump()}))
    (epoch / "ended.json").write_text("{}")
    window = await store.register_window(token, session.id, epoch.name, 0, original.relative_to(tmp_path).as_posix(),
        "a" * 64, original.stat().st_size, 0, 600, metadata={"policy": policy.model_dump(), "archived": archived})
    await store.update_window(token, window.id, status="blocked")
    await store.clear_history(owner["id"], registered_channel.id, "failed")
    assert original.exists()  # Clearing itself never removes media.
    timestamp = time.time() - age_days * 86400
    os.utime(epoch, (timestamp, timestamp))
    runner = ChannelRunner(SimpleNamespace(channel_id=registered_channel.id, policy=policy), token,
        RuntimeSettings(tmp_path, 0, 1, 24), SimpleNamespace(_live=AsyncMock()))
    runner.readers[epoch] = object()
    runner.segments[epoch] = {0: ClosedSegment(original, 0, 0, 600, "a" * 64, original.stat().st_size)}
    await runner._retention()
    assert original.exists() is not removed


async def test_library_deletion_clears_window_even_before_task_binding(capped_recording, client, db_session):
    from sqlalchemy import text
    from tests.integration.test_recording_automation import headers

    channel, token, window, pipeline, native, clips, source, queue = capped_recording
    task_id = window.task_id
    # Simulate a recorder dying between successful task creation and binding.
    await db_session.execute(text("UPDATE recording_windows SET task_id=NULL,status='submitting' WHERE id=:id"), {"id": window.id})
    await db_session.commit()
    response = await client.delete(f"/tasks/{task_id}", headers=headers(channel.user_id))
    assert response.status_code == 200, response.text
    async with AsyncSessionLocal() as db:
        row = await db.get(RecordingWindow, window.id)
        assert row.details.get("history_cleared") is True
        assert (await AutomationStore(db).list_windows(channel.user_id, channel.channel_id))["total"] == 0
    assert source.exists()
    retry = await client.post("/tasks/", headers={**headers(channel.user_id), "Idempotency-Key": f"recording:{window.id}:task"},
        json={"source": {"url": window.upload_ref}, "output_format": "vertical", "add_subtitles": True})
    assert retry.status_code == 409, retry.text


async def test_task_provenance_cannot_clear_another_owners_history(history, client, db_session):
    from sqlalchemy import text
    from tests.fixtures.factories import create_user

    owner, channel, token, session, rows, root = history
    other = await create_user(db_session)
    source = await create_source(db_session)
    task = await create_task(db_session, user_id=other["id"], source_id=source["id"])
    response = await client.post("/tasks/", headers={**headers(other["id"]), "Idempotency-Key": f"recording:{rows[0].id}:task"},
        json={"source": {"url": "upload://retained.mp4"}})
    assert response.status_code == 404
    await db_session.execute(text("UPDATE tasks SET source_metadata=jsonb_build_object('recording_window_id', CAST(:window AS text)) WHERE id=:id"),
        {"window": rows[0].id, "id": task["id"]})
    await db_session.commit()
    assert (await client.delete(f"/tasks/{task['id']}", headers=headers(other["id"]))).status_code == 200
    async with AsyncSessionLocal() as db:
        assert (await AutomationStore(db).list_windows(owner["id"], channel.id))["total"] == 3
    assert (root / rows[0].source_path).exists()
