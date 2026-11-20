"""Atomic edits to a private encrypted app-settings document."""
from dataclasses import replace
import inspect
from uuid import uuid4

from sqlalchemy import text

from .. import runtime_settings
from .models import Connection, Registry, SETTING_KEY, validate_proxy_url

_LOCK = 596313893654


class RegistryUnavailable(ValueError):
    pass


def publish(registry: Registry) -> None:
    runtime_settings._settings_cache[SETTING_KEY] = registry.encode()


async def _bootstrap(db) -> Registry:
    from ..config import Config
    from ..home_proxy import active_proxy, refresh_home_proxy

    await refresh_home_proxy(db)
    connections = []
    if active_proxy():
        name = (await db.execute(text("SELECT name FROM home_proxy_devices WHERE revoked_at IS NULL ORDER BY paired_at DESC LIMIT 1"))).scalar_one_or_none()
        connections.append(Connection('home', name or 'My Mac', None, kind='home', revision=uuid4().hex))
    url = Config._get_runtime_setting('YOUTUBE_PROXY_URL')
    if url:
        try:
            url = validate_proxy_url(url)
        except ValueError:
            url = None  # Preserve routing intent; the owner can repair this entry.
        country = (Config._get_runtime_setting('YOUTUBE_PROXY_COUNTRY') or '').lower()
        if len(country) != 2 or not country.isalpha():
            country = ''
        connections.append(Connection(uuid4().hex, 'Saved proxy', url, priority=len(connections), country=country, revision=uuid4().hex))
    return Registry(tuple(connections))


async def _read_locked(db) -> tuple[Registry, bool]:
    await db.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': _LOCK})
    raw = (await db.execute(text('SELECT encrypted_value FROM app_settings WHERE setting_key=:key'), {'key': SETTING_KEY})).scalar_one_or_none()
    if raw is None:
        return await _bootstrap(db), True
    try:
        registry = Registry.decode(runtime_settings.decrypt_setting_value(raw))
    except Exception:
        raise RegistryUnavailable('Saved proxy settings could not be read. Check the server encryption key.') from None
    if registry is None or registry.unavailable:
        raise RegistryUnavailable('Saved proxy settings are invalid. Restore the saved proxy configuration.')
    return registry, False


async def _save(db, registry: Registry, user_id=None):
    value = registry.encode()
    await db.execute(text('''
        INSERT INTO app_settings(setting_key,encrypted_value,prefer_admin_value,updated_by)
        VALUES (:key,:value,true,:user)
        ON CONFLICT(setting_key) DO UPDATE SET encrypted_value=EXCLUDED.encrypted_value,
          prefer_admin_value=true,updated_by=COALESCE(EXCLUDED.updated_by,app_settings.updated_by),updated_at=clock_timestamp()
    '''), {'key': SETTING_KEY, 'value': runtime_settings.encrypt_setting_value(value), 'user': user_id})


async def read(db, user_id=None) -> Registry:
    registry, created = await _read_locked(db)
    if created:
        await _save(db, registry, user_id)
    await db.commit()
    publish(registry)
    return registry


async def mutate(db, operation, user_id=None) -> Registry:
    registry, _ = await _read_locked(db)
    updated = operation(registry)
    if inspect.isawaitable(updated):
        updated = await updated
    await _save(db, updated, user_id)
    await db.commit()
    publish(updated)
    return updated


async def paired_mac_changed(db) -> Registry | None:
    """Join the pairing transaction; publish only after its owner commits."""
    # Old installers/clients still work before the new manager is first opened.
    # Pairing/deleting always lock home state before the registry, in that order.
    await db.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': _LOCK})
    exists = (await db.execute(text('SELECT 1 FROM app_settings WHERE setting_key=:key'), {'key': SETTING_KEY})).scalar_one_or_none()
    if exists is None:
        return None
    registry, _ = await _read_locked(db)
    name = (await db.execute(text('SELECT name FROM home_proxy_devices WHERE revoked_at IS NULL ORDER BY paired_at DESC LIMIT 1'))).scalar_one_or_none()
    if name is None:
        return registry
    rows = list(registry.connections)
    for index, connection in enumerate(rows):
        if connection.kind == 'home':
            rows[index] = replace(connection, revision=uuid4().hex)
            break
    else:
        rows.append(Connection('home', name, None, kind='home', priority=len(rows), revision=uuid4().hex))
    updated = Registry(tuple(rows))
    await _save(db, updated)
    return updated
