"""Pairing credentials, revocation and races against disposable PostgreSQL."""
import asyncio
import hashlib
import hmac
import shlex
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.database import AsyncSessionLocal
from tests.fixtures.factories import create_user

KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIJvTNd7zvW4TP3Hobf2N+KtOUaQKa1Ywm/bhl7Uy7xua"
SECOND_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIBvTNd7zvW4TP3Hobf2N+KtOUaQKa1Ywm/bhl7Uy7xua"
BASE = "/recording/home-proxy"


def signed_headers(user_id):
    stamp = str(int(time.time()))
    signature = hmac.new(b"test-backend-auth-secret", f"{user_id}:{stamp}".encode(), hashlib.sha256).hexdigest()
    return {"x-supoclip-user-id": user_id, "x-supoclip-ts": stamp, "x-supoclip-signature": signature}


@pytest.fixture
async def admin(db_session):
    user = await create_user(db_session, is_admin=True)
    try:
        yield signed_headers(user["id"])
    finally:
        await db_session.execute(text("DELETE FROM users WHERE id=:id"), {"id": user["id"]})
        await db_session.commit()


async def test_home_proxy_reports_unavailable_when_no_relay_is_configured(client, admin, monkeypatch):
    monkeypatch.delenv("HOME_PROXY_SSH_HOST", raising=False)
    response = await client.get(BASE, headers=admin)
    assert response.status_code == 200
    assert response.json() == {"available": False, "paired": False, "connected": False, "device_name": None, "paired_at": None}
    assert (await client.post(BASE + "/setup", headers=admin)).status_code == 503


@pytest.fixture
async def relay(monkeypatch, initialized_database):
    values = {
        "HOME_PROXY_SSH_HOST": "relay.example.com",
        "HOME_PROXY_SSH_HOST_KEY": KEY,
        "HOME_PROXY_REMOTE_BIND": "172.19.0.1",
        "HOME_PROXY_URL": "http://172.19.0.1:18888",
        "HOME_PROXY_APP_ORIGIN": "https://app.example.com",
    }
    for key in ("HOME_PROXY_SSH_PORT", "HOME_PROXY_SSH_USER", "HOME_PROXY_REMOTE_PORT"):
        monkeypatch.delenv(key, raising=False)
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    async with AsyncSessionLocal() as db:
        await db.execute(text("TRUNCATE home_proxy_devices, home_proxy_pairings, home_proxy_pair_attempts"))
        await db.commit()
    from src.home_proxy import clear_active_proxy
    clear_active_proxy()
    try:
        yield values
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(text("TRUNCATE home_proxy_devices, home_proxy_pairings, home_proxy_pair_attempts"))
            await db.commit()
        clear_active_proxy()


async def issue(client, admin, name="My Mac"):
    response = await client.post(BASE + "/setup", headers=admin, json={"device_name": name})
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    data = response.json()
    parts = shlex.split(data["setup_command"])
    assert parts[0:2] == ["/bin/bash", "-c"]
    assert "mktemp" in parts[2] and "trap" in parts[2]
    assert parts[-2] == "https://app.example.com"
    assert datetime.now(timezone.utc) < datetime.fromisoformat(data["expires_at"]) < datetime.now(timezone.utc).replace(microsecond=0) + timedelta(minutes=11)
    return parts[-1]


async def redeem(client, token, key=KEY):
    return await client.post(BASE + "/pair", json={"token": token, "public_key": key})


async def test_pairing_returns_only_pinned_descriptor_and_stores_only_hashes(client, admin, relay):
    token = await issue(client, admin, "Kitchen Mac")
    assert len(token) >= 43  # At least 256 bits before encoding.
    async with AsyncSessionLocal() as db:
        row = (await db.execute(text("SELECT * FROM home_proxy_pairings"))).mappings().one()
        assert row["token_hash"] == hashlib.sha256(token.encode()).hexdigest()
        assert token not in str(dict(row))
        assert row["consumed_at"] is None
    response = await redeem(client, token, KEY + " optional comment")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "ssh_host": "relay.example.com", "ssh_port": 2222, "ssh_user": "supoclip-relay",
        "ssh_host_key": KEY, "remote_bind": "172.19.0.1", "remote_port": 18888,
        "device_name": "Kitchen Mac",
    }
    from src.home_proxy import active_proxy
    assert active_proxy() == "http://172.19.0.1:18888"
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(text("SELECT public_key FROM home_proxy_devices WHERE revoked_at IS NULL"))).scalars().all()
        assert rows == [KEY]
    assert (await redeem(client, token)).status_code == 400


async def test_setup_requires_admin_and_latest_setup_revokes_outstanding_tokens(client, admin, relay, db_session):
    viewer = await create_user(db_session)
    try:
        for method, path in (("GET", ""), ("POST", "/setup"), ("POST", "/disconnect")):
            assert (await client.request(method, BASE + path)).status_code == 401
            assert (await client.request(method, BASE + path, headers=signed_headers(viewer["id"]))).status_code == 403
        first = await issue(client, admin)
        second = await issue(client, admin)
        assert (await redeem(client, first)).status_code == 400
        assert (await redeem(client, second)).status_code == 200
    finally:
        await db_session.execute(text("DELETE FROM users WHERE id=:id"), {"id": viewer["id"]})
        await db_session.commit()


async def test_expired_pairing_cannot_authorize_device(client, admin, relay):
    token = await issue(client, admin)
    async with AsyncSessionLocal() as db:
        await db.execute(text("UPDATE home_proxy_pairings SET expires_at=NOW()-INTERVAL '1 second'"))
        await db.commit()
    assert (await redeem(client, token)).status_code == 400
    async with AsyncSessionLocal() as db:
        assert (await db.execute(text("SELECT COUNT(*) FROM home_proxy_devices"))).scalar() == 0


async def test_concurrent_redemption_authorizes_exactly_one_device(client, admin, relay, app):
    token = await issue(client, admin)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://second-peer") as other:
        responses = await asyncio.gather(redeem(client, token), redeem(other, token, SECOND_KEY))
    assert sorted(response.status_code for response in responses) == [200, 400]
    async with AsyncSessionLocal() as db:
        assert (await db.execute(text("SELECT COUNT(*) FROM home_proxy_devices WHERE revoked_at IS NULL"))).scalar() == 1
        assert (await db.execute(text("SELECT COUNT(*) FROM home_proxy_pairings WHERE consumed_at IS NOT NULL"))).scalar() == 1


async def test_repair_replaces_active_key_and_disconnect_invalidates_all_tokens(client, admin, relay):
    first = await issue(client, admin, "Old Mac")
    assert (await redeem(client, first)).status_code == 200
    second = await issue(client, admin, "New Mac")
    assert (await redeem(client, second, SECOND_KEY)).status_code == 200
    async with AsyncSessionLocal() as db:
        active = (await db.execute(text("SELECT public_key FROM home_proxy_devices WHERE revoked_at IS NULL"))).scalars().all()
        assert active == [SECOND_KEY]
        assert (await db.execute(text("SELECT COUNT(*) FROM home_proxy_devices WHERE revoked_at IS NOT NULL"))).scalar() == 1
    pending = await issue(client, admin)
    response = await client.post(BASE + "/disconnect", headers=admin)
    assert response.status_code == 200
    assert response.json() == {"available": True, "paired": False, "connected": False, "device_name": None, "paired_at": None}
    from src.home_proxy import active_proxy
    assert active_proxy() == ""
    assert (await redeem(client, pending)).status_code == 400
    async with AsyncSessionLocal() as db:
        assert (await db.execute(text("SELECT COUNT(*) FROM home_proxy_devices WHERE revoked_at IS NULL"))).scalar() == 0


async def test_invalid_keys_are_rejected_without_consuming_pairing_or_logging_token(client, admin, relay, caplog):
    token = await issue(client, admin)
    for key in ("command=evil " + KEY, KEY + "\n" + KEY, "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAAA==", "ssh-rsa AAAA"):
        response = await redeem(client, token, key)
        assert response.status_code == 400
        assert token not in response.text
    assert (await redeem(client, token)).status_code == 200
    assert token not in caplog.text


async def test_invalid_redemption_limit_never_blocks_valid_token_from_same_proxy_peer(client, admin, relay):
    token = await issue(client, admin)
    for index in range(11):
        response = await client.post(BASE + "/pair", json={"token": "invalid", "public_key": KEY}, headers={"x-forwarded-for": f"192.0.2.{index}"})
        assert response.status_code == (400 if index < 10 else 429)
    # Several real Macs can share Caddy's server-observed peer. Knowledge of the
    # one-use 256-bit token must survive another client's failed-attempt budget.
    assert (await redeem(client, token)).status_code == 200
    async with AsyncSessionLocal() as db:
        await db.execute(text("UPDATE home_proxy_pair_attempts SET window_started_at=NOW()-INTERVAL '11 minutes'"))
        await db.commit()
    assert (await redeem(client, "invalid")).status_code == 400


async def test_pairing_body_is_bounded_and_schema_errors_never_echo_token(client, admin, relay, caplog):
    token = await issue(client, admin)
    response = await client.post(BASE + "/pair", json={"token": token, "public_key": {"secret": token}})
    assert response.status_code == 400
    assert token not in response.text
    assert token not in caplog.text
    response = await client.post(BASE + "/pair", content='{"token":"' + "x" * 9000 + '"}')
    assert response.status_code == 413


async def test_status_probes_tcp_only_and_hides_bridge_details(client, admin, relay, monkeypatch):
    from src.api.routes import home_proxy
    token = await issue(client, admin)
    await redeem(client, token)
    server = await asyncio.start_server(lambda reader, writer: writer.close(), "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    original = home_proxy.asyncio.open_connection

    async def redirected(host, requested_port):
        assert host == "172.19.0.1" and requested_port == 18888
        return await original("127.0.0.1", port)

    monkeypatch.setattr(home_proxy.asyncio, "open_connection", redirected)
    try:
        response = await client.get(BASE, headers=admin)
        assert response.status_code == 200
        data = response.json()
        assert set(data) == {"available", "paired", "connected", "device_name", "paired_at"}
        assert data["available"] and data["paired"] and data["connected"]
        assert "172.19.0.1" not in response.text and "relay.example.com" not in response.text
    finally:
        server.close()
        await server.wait_closed()
    response = await client.get(BASE, headers=admin)
    assert response.json()["paired"] and not response.json()["connected"]


async def test_status_connection_timeout_is_capped(client, admin, relay, monkeypatch):
    from src.api.routes import home_proxy
    token = await issue(client, admin)
    await redeem(client, token)

    probe_started = []

    async def stalled(*_args, **_kwargs):
        probe_started.append(time.monotonic())
        await asyncio.sleep(20)

    monkeypatch.setattr(home_proxy.asyncio, "open_connection", stalled)
    response = await client.get(BASE, headers=admin)
    assert 1.5 < time.monotonic() - probe_started[0] < 3
    assert response.json()["paired"] and not response.json()["connected"]


async def test_migration_is_repeatable_and_limits_active_device_to_one(db_session):
    from sqlalchemy.exc import IntegrityError
    schema = "home_proxy_" + uuid4().hex
    await db_session.execute(text(f'CREATE SCHEMA "{schema}"'))
    try:
        await db_session.execute(text(f'SET LOCAL search_path TO "{schema}"'))
        migration = Path(__file__).resolve().parents[2] / "src/migrations/sql/20261118_0001_home_proxy.sql"
        for _ in range(2):
            for statement in migration.read_text().split(";"):
                if statement.strip():
                    await db_session.execute(text(statement))
        await db_session.execute(text("INSERT INTO home_proxy_devices (id,name,public_key) VALUES ('one','Mac',:key)"), {"key": KEY})
        with pytest.raises(IntegrityError):
            await db_session.execute(text("INSERT INTO home_proxy_devices (id,name,public_key) VALUES ('two','Mac',:key)"), {"key": SECOND_KEY})
    finally:
        await db_session.rollback()


async def test_setup_body_is_optional_and_defaults_to_my_mac(client, admin, relay):
    response = await client.post(BASE + "/setup", headers=admin)
    assert response.status_code == 200
    token = shlex.split(response.json()["setup_command"])[-1]
    paired = await redeem(client, token)
    assert paired.status_code == 200
    assert paired.json()["device_name"] == "My Mac"


async def test_disconnect_clears_cached_route_even_when_endpoint_configuration_is_invalid(client, admin, relay, monkeypatch):
    from src.home_proxy import active_proxy
    token = await issue(client, admin)
    assert (await redeem(client, token)).status_code == 200
    assert active_proxy() == "http://172.19.0.1:18888"
    monkeypatch.setenv("HOME_PROXY_URL", "http://8.8.8.8:18888")
    response = await client.post(BASE + "/disconnect", headers=admin)
    assert response.status_code == 200
    assert response.json() == {"available": False, "paired": False, "connected": False, "device_name": None, "paired_at": None}
    assert active_proxy() == ""
    async with AsyncSessionLocal() as db:
        assert (await db.execute(text("SELECT COUNT(*) FROM home_proxy_devices WHERE revoked_at IS NULL"))).scalar() == 0
