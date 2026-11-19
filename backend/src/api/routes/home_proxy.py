"""Private Mac home-proxy pairing and admin management."""
import asyncio
import base64
import binascii
import hashlib
import ipaddress
import json
import os
import re
import secrets
import shlex
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ...admin_auth import require_admin_user
from ...config import get_config
from ...database import get_db
from ...home_proxy import clear_active_proxy, refresh_home_proxy

router = APIRouter(prefix="/recording/home-proxy", tags=["recording"])


def normalize_public_key(value: str) -> str:
    """Accept a single bare Ed25519 key, never authorized_keys options."""
    if not isinstance(value, str) or len(value) > 1024 or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("Expected an Ed25519 public key")
    fields = value.split()
    if len(fields) < 2 or fields[0] != "ssh-ed25519":
        raise ValueError("Expected an Ed25519 public key")
    try:
        blob = base64.b64decode(fields[1], validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("Invalid Ed25519 public key") from exc
    # SSH strings include a four-byte network-order length. No extra data is allowed.
    if len(blob) != 51 or blob[:19] != b"\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20":
        raise ValueError("Invalid Ed25519 public key")
    return "ssh-ed25519 " + base64.b64encode(blob).decode("ascii")


@dataclass(frozen=True)
class HomeProxySettings:
    ssh_host: str
    ssh_port: int
    ssh_user: str
    ssh_host_key: str
    remote_bind: str
    remote_port: int
    proxy_url: str
    app_origin: str


def load_settings() -> HomeProxySettings | None:
    """An incomplete relay must never produce a partially configured installer."""
    try:
        host = os.environ["HOME_PROXY_SSH_HOST"].strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]{0,252}", host):
            return None
        ssh_port = int(os.getenv("HOME_PROXY_SSH_PORT", "2222"))
        remote_port = int(os.getenv("HOME_PROXY_REMOTE_PORT", "18888"))
        if not 1 <= ssh_port <= 65535 or not 1024 <= remote_port <= 65535:
            return None
        ssh_user = os.getenv("HOME_PROXY_SSH_USER", "supoclip-relay")
        if ssh_user != "supoclip-relay":
            return None
        host_key = normalize_public_key(os.environ["HOME_PROXY_SSH_HOST_KEY"])
        bind = str(ipaddress.IPv4Address(os.environ["HOME_PROXY_REMOTE_BIND"]))
        if not any(ipaddress.ip_address(bind) in ipaddress.ip_network(network) for network in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")):
            return None
        proxy_url = os.environ["HOME_PROXY_URL"]
        proxy = urlsplit(proxy_url)
        if (proxy.scheme != "http" or proxy.hostname != bind or proxy.port != remote_port
                or proxy.username is not None or proxy.password is not None
                or proxy.path not in ("", "/") or proxy.query or proxy.fragment):
            return None
        origin = urlsplit(os.environ["HOME_PROXY_APP_ORIGIN"])
        if (origin.scheme != "https" or not origin.hostname or origin.port == 0 or origin.username is not None
                or origin.password is not None or origin.path not in ("", "/")
                or origin.query or origin.fragment):
            return None
        return HomeProxySettings(host, ssh_port, ssh_user, host_key, bind, remote_port,
                                 proxy_url, origin.geturl().rstrip("/"))
    except (KeyError, ValueError):
        return None


# Setup, pairing and revocation are one instance-wide state transition. The lock
# also orders disconnect against an in-flight redemption in another API process.
_STATE_LOCK = 756482190341
_ASSETS = Path(__file__).resolve().parents[2] / "home_proxy_assets"


def _json(data: dict) -> JSONResponse:
    return JSONResponse(data, headers={"Cache-Control": "no-store"})


def _require_settings() -> HomeProxySettings:
    settings = load_settings()
    if settings is None:
        raise HTTPException(503, "Home connection is not configured on this server")
    return settings


async def _body(request: Request, *, optional: bool = False) -> dict:
    # Parse locally so FastAPI's generic validation handler never logs or echoes
    # a submitted pairing token. Enforce the bound for chunked requests too.
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > 4096:
            raise HTTPException(413, "Pairing request is too large")
        content.extend(chunk)
    if not content and optional:
        return {}
    try:
        value = json.loads(content)
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(400, "Invalid home connection request") from exc
    if not isinstance(value, dict):
        raise HTTPException(400, "Invalid home connection request")
    return value


async def _connected(settings: HomeProxySettings) -> bool:
    async def connect():
        _reader, writer = await asyncio.open_connection(settings.remote_bind, settings.remote_port)
        try:
            writer.close()
            await writer.wait_closed()
        finally:
            writer.close()
        return True

    try:
        return await asyncio.wait_for(connect(), timeout=2)
    except (OSError, TimeoutError):
        return False


def _status(settings: HomeProxySettings | None, device=None, connected: bool = False) -> dict:
    return {
        "available": settings is not None,
        "paired": device is not None,
        "connected": connected,
        "device_name": device["name"] if device is not None else None,
        "paired_at": device["paired_at"].isoformat() if device is not None else None,
    }


@router.get("")
async def home_proxy_status(request: Request, db: AsyncSession = Depends(get_db)):
    await require_admin_user(request, db, get_config())
    settings = load_settings()
    device = (await db.execute(text(
        "SELECT name, paired_at FROM home_proxy_devices WHERE revoked_at IS NULL ORDER BY paired_at DESC LIMIT 1"
    ))).mappings().first()
    # Release the read transaction before probing another machine.
    await db.rollback()
    connected = await _connected(settings) if settings is not None and device is not None else False
    return _json(_status(settings, device, connected))


def _setup_command(origin: str, token: str) -> str:
    script = ('set -eu; script=$(mktemp -t supoclip-home-proxy.XXXXXXXX); '
              'trap \'rm -f "$script"\' EXIT; '
              'curl -fsSL "$1/backend/recording/home-proxy/install.sh" -o "$script"; '
              '/bin/bash "$script" "$1" "$2"')
    return "/bin/bash -c " + shlex.quote(script) + " -- " + shlex.quote(origin) + " " + shlex.quote(token)


@router.post("/setup")
async def setup_home_proxy(request: Request, db: AsyncSession = Depends(get_db)):
    await require_admin_user(request, db, get_config())
    settings = _require_settings()
    payload = await _body(request, optional=True)
    name = payload.get("device_name", "My Mac")
    if (set(payload) - {"device_name"} or not isinstance(name, str) or not name.strip()
            or len(name.strip()) > 80 or any(ord(char) < 32 or ord(char) == 127 for char in name)):
        raise HTTPException(400, "Enter a device name of 1 to 80 characters")
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _STATE_LOCK})
    await db.execute(text("UPDATE home_proxy_pairings SET consumed_at=NOW() WHERE consumed_at IS NULL"))
    await db.execute(text("DELETE FROM home_proxy_pairings WHERE expires_at < NOW()-INTERVAL '1 day'"))
    expires_at = (await db.execute(text(
        "INSERT INTO home_proxy_pairings (token_hash,name,expires_at) "
        "VALUES (:hash,:name,clock_timestamp()+INTERVAL '10 minutes') RETURNING expires_at"
    ), {"hash": token_hash, "name": name.strip()})).scalar_one()
    await db.commit()
    return _json({"setup_command": _setup_command(settings.app_origin, token), "expires_at": expires_at.isoformat()})


async def _limit_attempts(request: Request, db: AsyncSession) -> None:
    # Use the server's peer identity, never an untrusted forwarding header. Store
    # its hash rather than retaining the client's network address.
    peer = request.client.host if request.client else "unknown"
    peer_hash = hashlib.sha256(peer.encode()).hexdigest()
    attempts = (await db.execute(text("""
        INSERT INTO home_proxy_pair_attempts (peer_hash, attempts)
        VALUES (:peer,1)
        ON CONFLICT (peer_hash) DO UPDATE SET
            attempts=CASE WHEN home_proxy_pair_attempts.window_started_at <= NOW()-INTERVAL '10 minutes'
                THEN 1 ELSE LEAST(home_proxy_pair_attempts.attempts+1,11) END,
            window_started_at=CASE WHEN home_proxy_pair_attempts.window_started_at <= NOW()-INTERVAL '10 minutes'
                THEN NOW() ELSE home_proxy_pair_attempts.window_started_at END
        RETURNING attempts
    """), {"peer": peer_hash})).scalar_one()
    await db.execute(text("DELETE FROM home_proxy_pair_attempts WHERE window_started_at < NOW()-INTERVAL '20 minutes'"))
    # Failed and malformed redemptions count even when their transaction rejects
    # the token below. Concurrent API processes share this atomic counter.
    await db.commit()
    if attempts > 10:
        raise HTTPException(429, "Too many pairing attempts. Try again in ten minutes.")


@router.post("/pair")
async def pair_home_proxy(request: Request, db: AsyncSession = Depends(get_db)):
    settings = _require_settings()
    try:
        payload = await _body(request)
    except HTTPException:
        await _limit_attempts(request, db)
        raise
    token = payload.get("token")
    try:
        if set(payload) != {"token", "public_key"} or not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
            raise ValueError("Invalid pairing request")
        public_key = normalize_public_key(payload.get("public_key"))
    except ValueError as exc:
        await _limit_attempts(request, db)
        raise HTTPException(400, "Invalid pairing token or Ed25519 public key") from exc
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    known = (await db.execute(text(
        "SELECT 1 FROM home_proxy_pairings WHERE token_hash=:hash "
        "AND consumed_at IS NULL AND expires_at>clock_timestamp()"
    ), {"hash": token_hash})).scalar_one_or_none()
    if known is None:
        await _limit_attempts(request, db)
        raise HTTPException(400, "Pairing token is invalid or expired. Create a new setup command.")
    # A valid high-entropy token bypasses failed attempts from other clients
    # sharing the reverse proxy peer. The locked update below still decides
    # expiry and single-use atomically against setup, disconnect and replay.
    await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _STATE_LOCK})
    pairing = (await db.execute(text(
        "UPDATE home_proxy_pairings SET consumed_at=NOW() "
        "WHERE token_hash=:hash AND consumed_at IS NULL AND expires_at>clock_timestamp() RETURNING name"
    ), {"hash": token_hash})).mappings().first()
    if pairing is None:
        await db.rollback()
        raise HTTPException(400, "Pairing token is invalid or expired. Create a new setup command.")
    await db.execute(text("UPDATE home_proxy_devices SET revoked_at=NOW() WHERE revoked_at IS NULL"))
    await db.execute(text(
        "INSERT INTO home_proxy_devices (id,name,public_key) VALUES (:id,:name,:key)"
    ), {"id": str(uuid4()), "name": pairing["name"], "key": public_key})
    await db.execute(text("UPDATE home_proxy_pairings SET consumed_at=NOW() WHERE consumed_at IS NULL"))
    await db.commit()
    await refresh_home_proxy(db)
    return _json({
        "ssh_host": settings.ssh_host, "ssh_port": settings.ssh_port,
        "ssh_user": settings.ssh_user, "ssh_host_key": settings.ssh_host_key,
        "remote_bind": settings.remote_bind, "remote_port": settings.remote_port,
        "device_name": pairing["name"],
    })


@router.post("/disconnect")
async def disconnect_home_proxy(request: Request, db: AsyncSession = Depends(get_db)):
    await require_admin_user(request, db, get_config())
    await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _STATE_LOCK})
    await db.execute(text("UPDATE home_proxy_devices SET revoked_at=NOW() WHERE revoked_at IS NULL"))
    await db.execute(text("UPDATE home_proxy_pairings SET consumed_at=NOW() WHERE consumed_at IS NULL"))
    await db.commit()
    try:
        await refresh_home_proxy(db)
    except ValueError:
        # Revocation is already durable. An invalid relay configuration must
        # not prevent disconnecting the Mac or leave its previous route cached.
        clear_active_proxy()
    return _json(_status(load_settings()))


@router.get("/install.sh", include_in_schema=False)
async def installer_asset():
    return FileResponse(_ASSETS / "install.sh", media_type="text/plain", headers={"Cache-Control": "no-store"})


@router.get("/helper.py", include_in_schema=False)
async def helper_asset():
    return FileResponse(_ASSETS / "helper.py", media_type="text/plain", headers={"Cache-Control": "no-store"})
