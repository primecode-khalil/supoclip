"""Recording API acceptance tests against disposable PostgreSQL."""
import asyncio
import hashlib
import hmac
import time
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from src.auth_headers import hash_api_key
from src.database import AsyncSessionLocal, init_db
from src.repositories.api_key_repository import ApiKeyRepository
from tests.fixtures.factories import create_user


def headers(user_id):
    ts = str(int(time.time()))
    signature = hmac.new(b"test-backend-auth-secret", f"{user_id}:{ts}".encode(), hashlib.sha256).hexdigest()
    return {"x-supoclip-user-id": user_id, "x-supoclip-ts": ts, "x-supoclip-signature": signature}


@pytest.fixture
async def owners(db_session):
    users = [await create_user(db_session) for _ in range(2)]
    yield users
    await db_session.rollback()
    for user in users:
        await db_session.execute(text("DELETE FROM users WHERE id=:id"), {"id": user["id"]})
    await db_session.commit()


async def channel(client, owner, **values):
    response = await client.post("/recording/channels", headers=headers(owner["id"]), json={"platform": "twitch", "handle": " Demo_Channel ", "name": "Demo", **values})
    assert response.status_code == 201, response.text
    return response.json()


async def register(client, owner, channel_id, external_id="broadcast-1"):
    return await client.post(f"/recording/channels/{channel_id}/sessions", headers=headers(owner["id"]), json={"external_id": external_id})


async def transition(client, owner, session_id, status):
    return await client.patch(f"/recording/sessions/{session_id}", headers=headers(owner["id"]), json={"status": status})


async def test_owned_channel_crud_and_canonical_identity(client, owners):
    owner, other = owners
    item = await channel(client, owner)
    assert item["handle"] == "demo_channel" and item["url"] == "https://www.twitch.tv/demo_channel"
    assert item["quality"] == "best" and item["enabled"] is True
    assert (await client.post("/recording/channels", headers=headers(owner["id"]), json={"platform": "twitch", "handle": "DEMO_CHANNEL", "name": "Duplicate"})).status_code == 409
    await channel(client, other)
    listing = (await client.get("/recording/channels?limit=1&offset=0", headers=headers(owner["id"]))).json()
    assert listing["total"] == 1 and [c["id"] for c in listing["channels"]] == [item["id"]]
    changed = await client.patch(f"/recording/channels/{item['id']}", headers=headers(owner["id"]), json={"name": "Updated", "enabled": False, "quality": "720p,best"})
    assert changed.status_code == 200 and changed.json()["enabled"] is False
    assert changed.json()["name"] == "Updated"
    assert (await client.get(f"/recording/channels/{item['id']}", headers=headers(owner["id"]))).json()["quality"] == "720p,best"
    for query in ("limit=0", "limit=101", "offset=-1"):
        assert (await client.get(f"/recording/channels?{query}", headers=headers(owner["id"]))).status_code == 422


async def test_owner_isolation_and_authentication(client, owners):
    owner, other = owners
    item = await channel(client, owner)
    session = (await register(client, owner, item["id"])).json()
    for foreign_id in (item["id"], str(uuid4())):
        for method, suffix, body in (("get", "", None), ("patch", "", {"name": "Hijack"}), ("get", "/sessions", None), ("post", "/sessions", {"external_id": "steal"})):
            response = await client.request(method, f"/recording/channels/{foreign_id}{suffix}", headers=headers(other["id"]), **({"json": body} if body else {}))
            assert response.status_code == 404
    for foreign_id in (session["id"], str(uuid4())):
        assert (await client.get(f"/recording/sessions/{foreign_id}", headers=headers(other["id"]))).status_code == 404
        assert (await transition(client, other, foreign_id, "failed")).status_code == 404
    assert (await client.get("/recording/channels")).status_code == 401
    assert (await client.post("/recording/channels", json={"platform": "kick", "handle": "demo", "name": "Demo"})).status_code == 401
    assert (await client.get(f"/recording/sessions/{session['id']}")).status_code == 401


async def test_replay_preserves_terminal_lifecycle_and_immutable_snapshot(client, owners):
    owner = owners[0]
    item = await channel(client, owner)
    response = await register(client, owner, item["id"])
    assert response.status_code == 201
    original = response.json()
    assert original["status"] == "created" and original["started_at"] is None and original["ended_at"] is None
    assert original["settings_snapshot"] == {"platform": "twitch", "handle": "demo_channel", "url": "https://www.twitch.tv/demo_channel", "name": "Demo", "quality": "best", "enabled": True}
    await client.patch(f"/recording/channels/{item['id']}", headers=headers(owner["id"]), json={"quality": "worst"})
    first_start = (await transition(client, owner, original["id"], "recording")).json()
    assert first_start["started_at"] is not None and first_start["ended_at"] is None
    assert (await transition(client, owner, original["id"], "recording")).json() == first_start
    assert (await transition(client, owner, original["id"], "interrupted")).status_code == 200
    assert (await transition(client, owner, original["id"], "recording")).json()["started_at"] == first_start["started_at"]
    completed = (await transition(client, owner, original["id"], "completed")).json()
    assert completed["ended_at"] >= completed["started_at"]
    replay = await register(client, owner, item["id"])
    assert replay.status_code == 200 and replay.json() == completed
    assert completed["settings_snapshot"] == original["settings_snapshot"]
    assert (await transition(client, owner, original["id"], "completed")).json() == completed
    assert (await transition(client, owner, original["id"], "recording")).status_code == 409
    next_session = (await register(client, owner, item["id"], "broadcast-2")).json()
    assert next_session["settings_snapshot"]["quality"] == "worst"
    listing = (await client.get(f"/recording/channels/{item['id']}/sessions?limit=1", headers=headers(owner["id"]))).json()
    assert listing["total"] == 2 and listing["sessions"][0]["id"] == next_session["id"]
    assert (await client.get(f"/recording/sessions/{original['id']}", headers=headers(owner["id"]))).json() == completed


@pytest.mark.parametrize(("initial", "target", "allowed"), [("created", "completed", False), ("created", "failed", True), ("created", "cancelled", True), ("recording", "created", False), ("interrupted", "completed", False), ("interrupted", "failed", True), ("interrupted", "cancelled", True), ("failed", "recording", False), ("cancelled", "recording", False)])
async def test_transition_rules(client, owners, initial, target, allowed):
    owner = owners[0]
    item = await channel(client, owner)
    session = (await register(client, owner, item["id"])).json()
    if initial in {"recording", "interrupted"}:
        await transition(client, owner, session["id"], "recording")
    if initial != "created":
        await transition(client, owner, session["id"], initial)
    response = await transition(client, owner, session["id"], target)
    assert response.status_code == (200 if allowed else 409)
    if allowed:
        assert response.json()["ended_at"] is not None
        assert (response.json()["started_at"] is None) == (initial == "created")


async def test_concurrent_registration_and_active_session_uniqueness(client, owners):
    owner = owners[0]
    item = await channel(client, owner)
    results = await asyncio.gather(*(register(client, owner, item["id"]) for _ in range(6)))
    assert sorted(r.status_code for r in results) == [200] * 5 + [201]
    ids = {r.json()["id"] for r in results}
    assert len(ids) == 1
    assert (await register(client, owner, item["id"], "other")).status_code == 409
    await transition(client, owner, next(iter(ids)), "cancelled")
    results = await asyncio.gather(*(register(client, owner, item["id"], f"new-{n}") for n in range(6)))
    assert sorted(r.status_code for r in results) == [201] + [409] * 5


async def test_concurrent_terminal_updates_cannot_overwrite_winner(client, owners):
    owner = owners[0]
    item = await channel(client, owner)
    session = (await register(client, owner, item["id"])).json()
    results = await asyncio.gather(*(transition(client, owner, session["id"], state) for state in ("failed", "cancelled")))
    assert sorted(r.status_code for r in results) == [200, 409]
    winner = next(r.json() for r in results if r.status_code == 200)
    assert (await client.get(f"/recording/sessions/{session['id']}", headers=headers(owner["id"]))).json() == winner


async def test_database_constraints_idempotent_migration_and_cascade(client, owners, db_session):
    owner = owners[0]
    item = await channel(client, owner)
    session = (await register(client, owner, item["id"])).json()
    for statement in (
        "INSERT INTO recording_channels (id,user_id,platform,handle,name,url) VALUES (:new,:owner,'twitch','demo_channel','Duplicate','https://www.twitch.tv/demo_channel')",
        "INSERT INTO recording_sessions (id,channel_id,external_id,settings_snapshot) VALUES (:new,:channel,'second','{}')",
        "INSERT INTO recording_sessions (id,channel_id,external_id,settings_snapshot,status,ended_at) VALUES (:new,:channel,'broadcast-1','{}','failed',NOW())",
        "UPDATE recording_sessions SET status='unknown' WHERE id=:session",
        "UPDATE recording_sessions SET status='completed' WHERE id=:session",
    ):
        async with AsyncSessionLocal() as db:
            with pytest.raises(IntegrityError):
                await db.execute(text(statement), {"new": str(uuid4()), "owner": owner["id"], "channel": item["id"], "session": session["id"]})
                await db.commit()
    await init_db()
    await db_session.execute(text("DELETE FROM users WHERE id=:id"), {"id": owner["id"]})
    await db_session.commit()
    for table, identity in (("recording_channels", item["id"]), ("recording_sessions", session["id"])):
        assert (await db_session.execute(text(f"SELECT count(*) FROM {table} WHERE id=:id"), {"id": identity})).scalar() == 0


async def test_api_key_auth_uses_same_ownership(client, owners, db_session):
    owner, other = owners
    item = await channel(client, owner)
    key = f"sk_{uuid4().hex}"
    await ApiKeyRepository.create_api_key(db_session, owner["id"], "Recording test", hash_api_key(key), key[:10])
    assert (await client.get(f"/recording/channels/{item['id']}", headers={"Authorization": f"Bearer {key}"})).status_code == 200
    other_item = await channel(client, other)
    assert (await client.get(f"/recording/channels/{other_item['id']}", headers={"x-api-key": key})).status_code == 404
    assert (await client.get("/recording/channels", headers={"x-api-key": "sk_invalid"})).status_code == 401


@pytest.mark.parametrize("body", [{"platform": "twitch", "handle": "https://twitch.tv/demo", "name": "Demo"}, {"platform": "kick", "handle": "demo", "name": "Demo", "user_id": "injected"}, {"platform": "kick", "handle": "demo", "name": "Demo", "quality": "--output=/etc/passwd"}, {"platform": "kick", "handle": "demo", "name": "  "}])
async def test_invalid_bodies_return_serializable_errors(client, owners, body):
    response = await client.post("/recording/channels", headers=headers(owners[0]["id"]), json=body)
    assert response.status_code == 422 and response.json()["detail"]


async def test_strict_updates_and_session_bodies(client, owners):
    owner = owners[0]
    item = await channel(client, owner)
    for body in ({"platform": "youtube"}, {"handle": "new"}, {"name": None}, {"enabled": "yes"}, {}):
        assert (await client.patch(f"/recording/channels/{item['id']}", headers=headers(owner["id"]), json=body)).status_code == 422
    for body in ({}, {"external_id": ""}, {"external_id": "x\ny"}, {"external_id": "a", "file_path": "/tmp/recording"}):
        assert (await client.post(f"/recording/channels/{item['id']}/sessions", headers=headers(owner["id"]), json=body)).status_code == 422
    session = (await register(client, owner, item["id"])).json()
    for body in ({"status": "unknown"}, {"status": "recording", "started_at": "2020-01-01"}, {"external_id": "reset"}):
        assert (await client.patch(f"/recording/sessions/{session['id']}", headers=headers(owner["id"]), json=body)).status_code == 422


async def test_additive_recording_migration_runs_twice_on_legacy_schema(db_session):
    from pathlib import Path
    schema = f"recording_migration_{uuid4().hex}"
    await db_session.execute(text(f'CREATE SCHEMA "{schema}"'))
    try:
        await db_session.execute(text(f'SET LOCAL search_path TO "{schema}"'))
        await db_session.execute(text("CREATE TABLE users (id VARCHAR(36) PRIMARY KEY)"))
        migrations = Path(__file__).resolve().parents[2] / "src/migrations/sql"
        for _ in range(2):
            for migration in sorted(migrations.glob("20261116_*recording*.sql")):
                for statement in migration.read_text().split(";"):
                    if statement.strip():
                        await db_session.execute(text(statement))
        tables = (await db_session.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema=:schema ORDER BY table_name"), {"schema": schema})).scalars().all()
        assert tables == ["recording_channels", "recording_sessions", "users"]
        await db_session.execute(text("INSERT INTO users VALUES ('owner')"))
        await db_session.execute(text("INSERT INTO recording_channels(id,user_id,platform,handle,url,name) VALUES ('c','owner','twitch','demo','https://www.twitch.tv/demo','Demo')"))
        await db_session.execute(text("INSERT INTO recording_sessions(id,channel_id,external_id,settings_snapshot) VALUES ('s','c','event','{}')"))
        with pytest.raises(IntegrityError):
            async with db_session.begin_nested():
                await db_session.execute(text("INSERT INTO recording_sessions(id,channel_id,external_id,settings_snapshot) VALUES ('s2','c','event2','{}')"))
        await db_session.execute(text("DELETE FROM users WHERE id='owner'"))
        assert (await db_session.execute(text("SELECT count(*) FROM recording_sessions"))).scalar() == 0
    finally:
        await db_session.rollback()  # Transactional DDL drops the isolated schema too.


@pytest.mark.parametrize("state", ["recording", "interrupted"])
async def test_active_session_remains_exclusive_after_start_or_interruption(client, owners, state):
    owner = owners[0]
    item = await channel(client, owner)
    session = (await register(client, owner, item["id"])).json()
    assert (await transition(client, owner, session["id"], "recording")).status_code == 200
    assert (await transition(client, owner, session["id"], state)).status_code == 200
    assert (await register(client, owner, item["id"], "another-event")).status_code == 409
    assert (await register(client, owner, item["id"])).json()["id"] == session["id"]


@pytest.mark.parametrize("reported_state", ["recording", "cancelled"])
async def test_lifecycle_uses_database_time_when_api_clock_is_skewed(
    client, owners, db_session, monkeypatch, reported_state
):
    from datetime import datetime, timezone
    from types import SimpleNamespace

    from src.services import recording_service

    owner = owners[0]
    item = await channel(client, owner)
    session = (await register(client, owner, item["id"])).json()
    database_before = (
        await db_session.execute(text("SELECT clock_timestamp()"))
    ).scalar_one()
    # Host clocks can differ between API replicas and the database server.
    monkeypatch.setattr(
        recording_service,
        "datetime",
        SimpleNamespace(now=lambda *_: datetime(2000, 1, 1, tzinfo=timezone.utc)),
        raising=False,
    )

    response = await transition(client, owner, session["id"], reported_state)

    assert response.status_code == 200, response.text
    result = response.json()
    field = "started_at" if reported_state == "recording" else "ended_at"
    actual = datetime.fromisoformat(result[field].replace("Z", "+00:00"))
    database_after = (
        await db_session.execute(text("SELECT clock_timestamp()"))
    ).scalar_one()
    assert database_before <= actual <= database_after
