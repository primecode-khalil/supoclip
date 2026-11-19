"""Recorder retries must survive completion, failure and API process death."""
import pytest
from sqlalchemy import text

from src.repositories.task_repository import TaskRepository
from tests.fixtures.factories import create_user
from tests.integration.test_upload_idempotency import _upload


@pytest.mark.parametrize("status", ["completed", "error", "cancelled"])
async def test_explicit_upload_request_reuses_terminal_task_after_restart(
    client, app, auth_headers, db_session, tmp_path, monkeypatch, status,
):
    await create_user(db_session, user_id="user-1")
    app.state.config.temp_dir = str(tmp_path)

    async def duration(*args):
        return 60.0

    monkeypatch.setattr("src.api.routes.tasks._preflight_upload_source", duration)
    uploaded = await _upload(client, auth_headers, b"recorded-window")
    body = {"source": {"url": uploaded.json()["video_path"]}, "add_subtitles": True}
    headers = {**auth_headers, "Idempotency-Key": "recording:immutable-window-0001"}
    first = await client.post("/tasks/", headers=headers, json=body)
    assert first.status_code == 200, first.text
    task_id = first.json()["task_id"]
    await db_session.execute(text("""
        UPDATE tasks SET status=:status, completed_at=NOW()-INTERVAL '1 day',
            created_at=NOW()-INTERVAL '1 day' WHERE id=:id
    """), {"status": status, "id": task_id})
    await db_session.commit()
    repeated = await client.post("/tasks/", headers=headers, json=body)
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["task_id"] == task_id


async def test_task_identity_metadata_is_committed_with_task(db_session):
    from tests.fixtures.factories import create_source
    user = await create_user(db_session)
    source = await create_source(db_session, source_type="video_url", url="upload://window.mp4")
    metadata = {"upload_request_key": "stable", "durable_upload_request": True}
    task_id = await TaskRepository.create_task(
        db_session, user["id"], source["id"], source_duration_seconds=60,
        source_metadata=metadata,
    )
    assert await TaskRepository.load_source_metadata(db_session, task_id) == metadata
