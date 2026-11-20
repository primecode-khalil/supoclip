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


def still_assigned(connection: Connection, purpose: str) -> bool:
    registry = snapshot()
    return registry is not None and not registry.unavailable and any(
        c.key == connection.key for c in registry.assigned(purpose))


def by_key(purpose: str, key: str) -> Connection:
    registry = snapshot()
    if registry is not None and not registry.unavailable:
        for connection in registry.assigned(purpose):
            if connection.key == key:
                resolved = resolve(connection)
                if resolved.url:
                    return resolved
    raise ProxyUnavailableError()


def retry_decision(exc: BaseException) -> tuple[bool, str | None]:
    """Source-specific rejection can try another route without a shared penalty."""
    import errno
    import socket
    from ..youtube_proxy import (
        _exception_chain, is_access_blocked_error, is_age_restricted_error,
        is_geo_restricted_error, is_transient_proxy_error,
        DownloadBudgetExceeded, PartialDownloadUnavailable,
    )
    errors = list(_exception_chain(exc))
    messages = ' '.join(str(e).lower() for e in errors)
    if any(isinstance(e, (DownloadBudgetExceeded, PartialDownloadUnavailable)) for e in errors) or is_age_restricted_error(exc):
        return False, None
    if any(term in messages for term in ('private video', 'members-only', 'video has been removed', 'video is unavailable')):
        return False, None
    if is_access_blocked_error(exc):
        return True, 'access'
    if 'http error 407' in messages or 'proxy authentication' in messages or ('socks' in messages and 'authentication' in messages):
        return True, 'authentication'
    if 'http error 429' in messages or 'http error 502' in messages or 'http error 503' in messages or 'http error 504' in messages:
        return True, 'transport'
    if is_transient_proxy_error(exc) or any(term in messages for term in ('certificate verify failed', 'failed to resolve', 'name or service not known')) or any(isinstance(e, socket.gaierror) or (
            isinstance(e, OSError) and e.errno in {errno.ECONNREFUSED, errno.ECONNRESET, errno.ENETUNREACH,
                                                errno.EHOSTUNREACH, errno.ETIMEDOUT, errno.ECONNABORTED}) for e in errors):
        return True, 'transport'
    if is_geo_restricted_error(exc) or 'http error 403' in messages:
        return True, None
    return False, None


@contextmanager
def using(connection: Connection, purpose: str):
    token = _current.set((purpose, connection))
    try:
        yield
    finally:
        _current.reset(token)
