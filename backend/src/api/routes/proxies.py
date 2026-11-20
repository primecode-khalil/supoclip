"""Instance-admin proxy management. Submitted credentials are never echoed."""
import asyncio
from dataclasses import replace
import json
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ...admin_auth import require_admin_user
from ...config import get_config
from ...database import get_db
from ...proxies import health, routing, store
from ...proxies.models import Connection, Registry, MAX_URL_CONNECTIONS, validate_name, validate_proxy_url

router = APIRouter(prefix='/proxy', tags=['proxy'])


class ConnectionInput(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    name: str = Field(max_length=80)
    url: str = Field(max_length=2048, repr=False)
    usage: Literal['live', 'imports', 'both'] = 'both'
    enabled: bool = True
    country: str = Field(default='', max_length=2)

    @field_validator('name')
    @classmethod
    def name_valid(cls, value):
        return validate_name(value)

    @field_validator('url')
    @classmethod
    def url_valid(cls, value):
        return validate_proxy_url(value)

    @field_validator('country')
    @classmethod
    def country_valid(cls, value):
        from yt_dlp.utils import ISO3166Utils
        value = value.lower()
        if value and not ISO3166Utils.short2full(value.upper()):
            raise ValueError('Choose a two-letter country code.')
        return value


class ConnectionEdit(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    expected_revision: str = Field(min_length=1, max_length=64)
    name: str | None = Field(default=None, max_length=80)
    url: str | None = Field(default=None, max_length=2048, repr=False)
    usage: Literal['live', 'imports', 'both'] | None = None
    enabled: bool | None = None
    country: str | None = Field(default=None, max_length=2)


class OrderInput(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    connection_ids: list[str] = Field(max_length=MAX_URL_CONNECTIONS + 1)


async def _body(request, model):
    content = bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > 8192:
            raise HTTPException(413, 'Proxy settings are too large.')
    try:
        return model.model_validate(json.loads(content))
    except (ValidationError, ValueError, UnicodeError):
        # The generic validation handler includes submitted values in errors.
        raise HTTPException(400, 'Invalid proxy settings. Check the name, endpoint and purpose.') from None


async def _payload(registry: Registry):
    def present():
        rows = [routing.resolve(c) for c in sorted(registry.connections, key=lambda c: (c.priority, c.id))]
        return {'connections': [{**c.public(), 'health': health.present(c)} for c in rows],
                'max_url_connections': MAX_URL_CONNECTIONS}
    return JSONResponse(await asyncio.to_thread(present), headers={'Cache-Control': 'no-store'})


async def _read(db, user):
    try:
        return await store.read(db, user)
    except store.RegistryUnavailable as exc:
        raise HTTPException(503, str(exc)) from None


async def _mutate(db, user, operation):
    try:
        return await store.mutate(db, operation, user)
    except store.RegistryUnavailable as exc:
        raise HTTPException(503, str(exc)) from None


def _find(registry, identity):
    for connection in registry.connections:
        if connection.id == identity:
            return connection
    raise HTTPException(404, 'Proxy connection not found.')


def _unique_name(registry, name, identity=None):
    if any(c.id != identity and c.name.casefold() == name.casefold() for c in registry.connections):
        raise HTTPException(409, 'Use a different connection name.')


@router.get('')
async def list_connections(request: Request, db: AsyncSession = Depends(get_db)):
    user = await require_admin_user(request, db, get_config())
    return await _payload(await _read(db, user))


@router.post('/connections')
async def add_connection(request: Request, db: AsyncSession = Depends(get_db)):
    user = await require_admin_user(request, db, get_config())
    body = await _body(request, ConnectionInput)

    def add(registry):
        if sum(c.kind == 'url' for c in registry.connections) >= MAX_URL_CONNECTIONS:
            raise HTTPException(409, 'You can save up to ten proxy endpoints.')
        _unique_name(registry, body.name)
        row = Connection(uuid4().hex, body.name, body.url, usage=body.usage, enabled=body.enabled,
                         priority=max((c.priority for c in registry.connections), default=-1) + 1,
                         country=body.country, revision=uuid4().hex)
        return Registry((*registry.connections, row))
    return await _payload(await _mutate(db, user, add))


@router.patch('/connections/{identity}')
async def edit_connection(identity: str, request: Request, db: AsyncSession = Depends(get_db)):
    user = await require_admin_user(request, db, get_config())
    body = await _body(request, ConnectionEdit)

    def edit(registry):
        old = _find(registry, identity)
        if old.revision != body.expected_revision:
            raise HTTPException(409, 'This connection changed. Reload it before editing.')
        values = body.model_dump(exclude_unset=True, exclude={'expected_revision'})
        if any(v is None for key, v in values.items() if key != 'url'):
            raise HTTPException(400, 'Connection settings cannot be empty.')
        values['url'] = body.url.strip() if body.url and body.url.strip() else old.url
        if old.kind == 'home':
            if body.url or body.country:
                raise HTTPException(400, 'Use Mac setup to change a home connection.')
            values['url'] = None
        else:
            try:
                checked = ConnectionInput.model_validate({
                    'name': values.get('name', old.name), 'url': values['url'],
                    'country': values.get('country', old.country)})
            except ValidationError:
                raise HTTPException(400, 'Check the connection name and endpoint.') from None
            values.update(name=checked.name, url=checked.url, country=checked.country)
        try:
            name = validate_name(values.get('name', old.name))
        except ValueError:
            raise HTTPException(400, 'Enter a connection name of 1 to 80 characters.') from None
        values['name'] = name
        _unique_name(registry, name, identity)
        if values['url'] != old.url or values.get('country', old.country) != old.country:
            values['revision'] = uuid4().hex
        changed = replace(old, **values)
        return Registry(tuple(changed if c.id == identity else c for c in registry.connections))
    return await _payload(await _mutate(db, user, edit))


@router.put('/order')
async def order_connections(request: Request, db: AsyncSession = Depends(get_db)):
    user = await require_admin_user(request, db, get_config())
    body = await _body(request, OrderInput)

    def reorder(registry):
        ids = body.connection_ids
        if len(ids) != len(set(ids)) or set(ids) != {c.id for c in registry.connections}:
            raise HTTPException(409, 'The connection list changed. Reload before reordering.')
        order = {identity: index for index, identity in enumerate(ids)}
        return Registry(tuple(replace(c, priority=order[c.id]) for c in registry.connections))
    return await _payload(await _mutate(db, user, reorder))


@router.delete('/connections/{identity}')
async def remove_connection(identity: str, request: Request, db: AsyncSession = Depends(get_db)):
    user = await require_admin_user(request, db, get_config())
    from .home_proxy import _STATE_LOCK
    await db.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': _STATE_LOCK})

    async def remove(registry):
        old = _find(registry, identity)
        if old.kind == 'home':
            await db.execute(text('UPDATE home_proxy_devices SET revoked_at=NOW() WHERE revoked_at IS NULL'))
            await db.execute(text('UPDATE home_proxy_pairings SET consumed_at=NOW() WHERE consumed_at IS NULL'))
        return Registry(tuple(c for c in registry.connections if c.id != identity))
    registry = await _mutate(db, user, remove)
    from ...home_proxy import refresh_home_proxy
    await refresh_home_proxy(db)
    await db.rollback()
    return await _payload(registry)
