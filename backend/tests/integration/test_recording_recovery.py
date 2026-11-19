import hashlib

import httpx
import pytest

from src.recording.automation_store import AutomationStore
from src.recording.pipeline import NativeClient
from src.recording.runner import AutomationPipeline, store_call
from tests.integration.test_recording_automation import automated, headers  # noqa: F401


@pytest.fixture
async def work(automated, db_session, tmp_path):
    owner, channel = automated
    store = AutomationStore(db_session)
    token = await store.acquire(channel.id, "recovery-test")
    session = await store.create_or_resume_session(token)
    source = tmp_path / "window.mp4"
    source.write_bytes(b"original window")
    window = await store.register_window(token, session.id, "epoch", 0, source.name,
        hashlib.sha256(source.read_bytes()).hexdigest(), source.stat().st_size, 0.0, 600.0)
    native_channel = next(item for item in await store.list_enabled_channels() if item.channel_id == channel.id)
    return owner, native_channel, token, window, source


async def test_upload_failure_keeps_advanced_stage_retryable(work):
    owner, channel, token, window, source = work
    async with NativeClient("http://test", "secret", transport=httpx.MockTransport(lambda r: httpx.Response(503))) as native:
        await AutomationPipeline(source.parent, native).step(channel, token, window)
    result = (await store_call("list_windows", owner["id"], channel.channel_id))["windows"][0]
    assert result.status == "submitting" and result.attempts == 1
    assert result.next_attempt_at and source.exists()


async def test_deleted_task_is_not_automatically_recreated(work):
    owner, channel, token, window, source = work
    await store_call("update_window", token, window.id, status="submitting")
    window = await store_call("update_window", token, window.id, status="processing")
    requests = []

    def external(request):
        requests.append(request)
        return httpx.Response(500)

    async with NativeClient("http://test", "secret", transport=httpx.MockTransport(external)) as native:
        await AutomationPipeline(source.parent, native).step(channel, token, window)
    result = (await store_call("list_windows", owner["id"], channel.channel_id))["windows"][0]
    assert result.status == "blocked" and not requests


async def test_owner_can_retry_corrected_blocked_work_without_losing_receipts(work, client):
    owner, channel, token, window, source = work
    await store_call("update_window", token, window.id, status="submitting", upload_ref="upload://durable.mp4")
    await store_call("update_window", token, window.id, status="blocked", attempts=12, last_error="Configure provider")
    url = f"/recording/channels/{channel.channel_id}/windows/{window.id}/retry"
    assert (await client.post(url, headers=headers("other-owner"))).status_code == 404
    resumed = await client.post(url, headers=headers(owner["id"]))
    assert resumed.status_code == 200, resumed.text
    result = (await store_call("list_windows", owner["id"], channel.channel_id))["windows"][0]
    assert result.status == "submitting" and result.upload_ref == "upload://durable.mp4"
    assert result.attempts == 12 and result.details["retry_base"] == 12
    assert not result.last_error and source.exists()
