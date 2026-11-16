"""Durable policy, fencing, and work recovery against PostgreSQL."""
import asyncio
import hashlib
import hmac
import time
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text

from src.database import AsyncSessionLocal
from src.models import RecordingChannel
from src.recording.automation_models import ChannelAutomation
from src.recording.automation_schema import AutomationPolicy
from src.recording.automation_store import AutomationStore, LostLeaseError
from src.recording.errors import RecordingError
from tests.fixtures.factories import create_user


def headers(user_id):
    ts = str(int(time.time()))
    digest = hmac.new(b"test-backend-auth-secret", f"{user_id}:{ts}".encode(), hashlib.sha256).hexdigest()
    return {"x-supoclip-user-id": user_id, "x-supoclip-ts": ts, "x-supoclip-signature": digest}


@pytest.fixture
async def automated(db_session):
    owner = await create_user(db_session)
    channel = RecordingChannel(user_id=owner["id"], platform="twitch", handle="ledger_demo", url="https://www.twitch.tv/ledger_demo", name="Demo")
    db_session.add(channel)
    await db_session.flush()
    db_session.add(ChannelAutomation(channel_id=channel.id, policy=AutomationPolicy(enabled=True).model_dump()))
    await db_session.commit()
    yield owner, channel
    await db_session.rollback()
    await db_session.execute(text("DELETE FROM users WHERE id=:id"), {"id": owner["id"]})
    await db_session.commit()


async def acquire(channel_id, holder):
    async with AsyncSessionLocal() as db:
        return await AutomationStore(db).acquire(channel_id, holder)


async def test_only_one_concurrent_supervisor_wins_and_same_holder_renews(automated):
    _, channel = automated
    results = await asyncio.gather(*(acquire(channel.id, f"holder-{i}") for i in range(8)))
    winners = [r for r in results if r is not None]
    assert len(winners) == 1
    token = winners[0]
    replay = await acquire(channel.id, token.holder)
    assert replay.fence == token.fence
    assert replay.expires_at >= token.expires_at


async def test_expired_holder_cannot_write_or_renew_after_takeover(automated, db_session):
    _, channel = automated
    old = await acquire(channel.id, "old")
    await db_session.execute(text("UPDATE recording_automation_leases SET expires_at=clock_timestamp()-interval '1 second' WHERE channel_id=:id"), {"id": channel.id})
    await db_session.commit()
    new = await acquire(channel.id, "new")
    assert new.fence == old.fence + 1
    async with AsyncSessionLocal() as db:
        store = AutomationStore(db)
        assert await store.renew(old) is None
        assert await store.release(old) is False
        with pytest.raises(LostLeaseError):
            await store.create_or_resume_session(old)
    async with AsyncSessionLocal() as db:
        assert await AutomationStore(db).release(new) is True


async def test_sessions_resume_and_finalized_windows_replay_without_mutation(automated):
    _, channel = automated
    token = await acquire(channel.id, "one")
    values = dict(epoch="epoch-1", sequence=0, source_path="channel/session/epoch-1/a.mkv", sha256="a"*64, size_bytes=1024, start_seconds=0.0, end_seconds=600.0, metadata={"policy": {"min_score": 75}})
    async with AsyncSessionLocal() as db:
        store = AutomationStore(db)
        session = await store.create_or_resume_session(token)
        first = await store.register_window(token, session.id, **values)
        first_id = first.id
        assert (await store.create_or_resume_session(token)).id == session.id
        changed = await store.update_window(token, first.id, status="submitting", attempts=1)
        replay = await store.register_window(token, session.id, **values)
        assert replay.id == first.id and replay.attempts == 1 and replay.status == "submitting"
        with pytest.raises(RecordingError, match="immutable"):
            await store.register_window(token, session.id, **{**values, "sha256": "b"*64})
    async with AsyncSessionLocal() as db:
        store = AutomationStore(db)
        pending = await store.list_pending(token)
        assert [w.id for w in pending] == [first_id]
        assert pending[0].details == {"policy": {"min_score": 75}}
        await store.update_window(token, first_id, status="processing", upload_ref="upload://test", task_id=None)
        await store.update_window(token, first_id, status="publishing")
        await store.update_window(token, first_id, status="completed")
        with pytest.raises(RecordingError):
            await store.update_window(token, first_id, status="pending")
    async with AsyncSessionLocal() as db:
        assert await AutomationStore(db).list_pending(token) == []


async def test_policy_is_owner_scoped_and_disabling_stops_renewal(automated):
    owner, channel = automated
    token = await acquire(channel.id, "one")
    async with AsyncSessionLocal() as db:
        store = AutomationStore(db)
        with pytest.raises(RecordingError) as exc:
            await store.get_policy(str(uuid4()), channel.id)
        assert exc.value.status_code == 404
        response = await store.get_policy(owner["id"], channel.id)
        assert response["runtime"]["leased"] is True
        assert "holder" not in response["runtime"]
        await store.put_policy(owner["id"], channel.id, AutomationPolicy(enabled=False))
        assert await store.renew(token) is None
        assert await store.list_enabled_channels() == []


async def test_automation_routes_require_owner_and_hide_host_paths(client, app, automated):
    from src.api.routes.recording_automation import router
    if not any(route.path == "/recording/channels/{channel_id}/automation" for route in app.routes):
        app.include_router(router)
    owner, channel = automated
    url = f"/recording/channels/{channel.id}/automation"
    assert (await client.get(url)).status_code == 401
    assert (await client.get(url, headers=headers(str(uuid4())))).status_code == 404
    assert (await client.put(url, headers=headers(owner["id"]), json={"enabled": True, "segment_seconds": 10})).status_code == 422
    response = await client.put(url, headers=headers(owner["id"]), json={"enabled": True, "publish_privacy": "public"})
    assert response.status_code == 200 and response.json()["policy"]["publish_privacy"] == "public"
    token = await acquire(channel.id, "one")
    async with AsyncSessionLocal() as db:
        store = AutomationStore(db)
        session = await store.create_or_resume_session(token)
        window = await store.register_window(token, session.id, "epoch", 0, "private/disk/segment.mkv", "a"*64, 100, 0.0, 600.0, metadata={"secret": "internal"})
        identity = window.id
    response = await client.get(f"/recording/channels/{channel.id}/windows", headers=headers(owner["id"]))
    assert response.status_code == 200
    record = response.json()["windows"][0]
    assert record["id"] == identity and "source_path" not in record and "details" not in record and "metadata" not in record
    assert (await client.get(f"/recording/channels/{channel.id}/windows", headers=headers(str(uuid4())))).status_code == 404
    assert (await client.get(f"/recording/channels/{channel.id}/windows?limit=101", headers=headers(owner["id"]))).status_code == 422


async def test_foreign_or_revoked_social_destinations_rejected(automated, db_session):
    from src.repositories.social_repository import SocialRepository
    owner, channel = automated
    other = await create_user(db_session)
    try:
        foreign = await SocialRepository.upsert_account(db_session, user_id=other["id"], provider="youtube", external_account_id="demo", display_name=None, username=None, avatar_url=None, access_token_encrypted="test-only-not-a-real-token", refresh_token_encrypted=None, token_expires_at=None, scopes=None, metadata={})
        async with AsyncSessionLocal() as db:
            store = AutomationStore(db)
            for account_id in (foreign["id"], str(uuid4())):
                with pytest.raises(RecordingError) as exc:
                    await store.put_policy(owner["id"], channel.id, AutomationPolicy(enabled=True, social_account_ids=[account_id]))
                assert exc.value.status_code == 409
        own = await SocialRepository.upsert_account(db_session, user_id=owner["id"], provider="youtube", external_account_id="demo", display_name=None, username=None, avatar_url=None, access_token_encrypted="test-only-not-a-real-token", refresh_token_encrypted=None, token_expires_at=None, scopes=None, metadata={})
        async with AsyncSessionLocal() as db:
            store = AutomationStore(db)
            response = await store.put_policy(owner["id"], channel.id, AutomationPolicy(enabled=True, social_account_ids=[own["id"]]))
            assert response["policy"].social_account_ids == [own["id"]]
            await db.execute(text("UPDATE social_accounts SET status='revoked' WHERE id=:id"), {"id": own["id"]})
            await db.commit()
            with pytest.raises(RecordingError):
                await store.put_policy(owner["id"], channel.id, AutomationPolicy(enabled=True, social_account_ids=[own["id"]]))
    finally:
        await db_session.execute(text("DELETE FROM users WHERE id=:id"), {"id": other["id"]})
        await db_session.commit()


async def test_same_holder_after_release_gets_new_fence_and_terminal_session_not_reopened(automated):
    _, channel = automated
    token = await acquire(channel.id, "same")
    async with AsyncSessionLocal() as db:
        store = AutomationStore(db)
        original = await store.create_or_resume_session(token)
        original_id = original.id
        ended = await store.finish_session(token, original_id, "completed")
        ended_at = ended.ended_at
        assert (await store.finish_session(token, original_id, "completed")).ended_at == ended_at
        with pytest.raises(RecordingError):
            await store.finish_session(token, original_id, "interrupted")
        replacement = await store.create_or_resume_session(token)
        assert replacement.id != original_id
        assert await store.release(token) is True
        renewed = await store.acquire(channel.id, "same")
        assert renewed.fence == token.fence + 1
        assert await store.renew(token) is None


async def test_window_policy_task_and_retry_progress_cannot_be_rewritten(automated, db_session):
    from tests.fixtures.factories import create_source, create_task
    owner, channel = automated
    other = await create_user(db_session)
    source = await create_source(db_session)
    own_task = await create_task(db_session, user_id=owner["id"], source_id=source["id"])
    foreign_task = await create_task(db_session, user_id=other["id"], source_id=source["id"])
    try:
        token = await acquire(channel.id, "same")
        async with AsyncSessionLocal() as db:
            store = AutomationStore(db)
            session = await store.create_or_resume_session(token)
            window = await store.register_window(token, session.id, "epoch", 0, "a.mkv", "a"*64, 100, 0.0, 600.0, metadata={"policy": {"min_score": 75}, "segments": ["a.mkv"]})
            window_id = window.id
            for values in ({"task_id": foreign_task["id"]}, {"details": {"policy": {"min_score": 0}}}, {"source_path": "changed.mkv"}):
                with pytest.raises((RecordingError, ValueError)):
                    await store.update_window(token, window_id, **values)
            await store.update_window(token, window_id, status="submitting", attempts=2, task_id=own_task["id"], upload_ref="upload://one")
            for values in ({"attempts": 1}, {"task_id": None}, {"upload_ref": "upload://two"}, {"status": "pending"}):
                with pytest.raises(RecordingError):
                    await store.update_window(token, window_id, **values)
            await store.update_window(token, window_id, status="blocked", last_error="Needs attention")
            assert await store.list_pending(token) == []
            assert [w.id for w in await store.list_pending(token, include_blocked=True)] == [window_id]
    finally:
        await db_session.execute(text("DELETE FROM users WHERE id=:id"), {"id": other["id"]})
        await db_session.execute(text("DELETE FROM sources WHERE id=:id"), {"id": source["id"]})
        await db_session.commit()


async def test_new_automation_migration_is_additive_and_repeatable(db_session):
    schema = f"automation_migration_{uuid4().hex}"
    await db_session.execute(text(f'CREATE SCHEMA "{schema}"'))
    try:
        await db_session.execute(text(f'SET LOCAL search_path TO "{schema}"'))
        await db_session.execute(text("CREATE TABLE users (id VARCHAR(36) PRIMARY KEY)"))
        await db_session.execute(text("CREATE TABLE tasks (id VARCHAR(36) PRIMARY KEY)"))
        migrations = Path(__file__).resolve().parents[2] / "src/migrations/sql"
        for _ in range(2):
            for filename in ("20261116_0001_recording_foundation.sql", "20261116_0002_recording_automation.sql"):
                for statement in (migrations / filename).read_text().split(";"):
                    if statement.strip():
                        await db_session.execute(text(statement))
        tables = (await db_session.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema=:schema ORDER BY table_name"), {"schema": schema})).scalars().all()
        assert set(tables) == {"users", "tasks", "recording_channels", "recording_sessions", "recording_automation", "recording_automation_leases", "recording_windows"}
    finally:
        await db_session.rollback()
