"""A held route overrides the refreshed registry only for its current operation."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import replace

from ..runtime_settings import get_cached_setting
from .models import Connection, Registry, SETTING_KEY

_current = ContextVar('ingestion_proxy_connection', default=None)


class ProxyUnavailableError(RuntimeError):
    def __init__(self):
        super().__init__('No assigned proxy is available. Check Proxy connections or wait for a retry.')


def snapshot() -> Registry | None:
    return Registry.decode(get_cached_setting(SETTING_KEY))


def configured(purpose: str) -> bool:
    registry = snapshot()
    return registry is not None and registry.required(purpose)


def resolve(connection: Connection) -> Connection:
    if connection.kind == 'home':
        from ..home_proxy import active_proxy
        return replace(connection, url=active_proxy() or None)
    return connection


def candidates(purpose: str, preferred: str | None = None) -> list[Connection]:
    registry = snapshot()
    if registry is None:
        return []
    rows = [resolve(c) for c in registry.assigned(purpose)]
    from . import health
    rows = [c for c in rows if c.url and health.available(c)]
    if preferred:
        rows.sort(key=lambda c: c.key != preferred)
    return rows


def current(purpose: str) -> Connection | None:
    held = _current.get()
    return held[1] if held and held[0] == purpose else None


@contextmanager
def using(connection: Connection, purpose: str):
    token = _current.set((purpose, connection))
    try:
        yield
    finally:
        _current.reset(token)
