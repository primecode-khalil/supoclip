"""Process-local route snapshot, refreshed from durable pairing state."""
import ipaddress
import os
from urllib.parse import urlsplit
from sqlalchemy import text

_active_proxy = ''


def clear_active_proxy():
    global _active_proxy
    _active_proxy = ''


def active_proxy():
    # Environment removal must not leave a previous test/deployment route active.
    return _active_proxy if os.getenv('HOME_PROXY_URL') else ''


async def refresh_home_proxy(db):
    global _active_proxy
    url = os.getenv('HOME_PROXY_URL', '')
    if not url:
        _active_proxy = ''
        return
    p = urlsplit(url)
    if (p.scheme != 'http' or not p.hostname or p.username or p.password or p.path not in ('', '/')
            or p.query or p.fragment or not p.port or not 1024 <= p.port <= 65535
            or not ipaddress.ip_address(p.hostname).is_private or ipaddress.ip_address(p.hostname).is_unspecified):
        raise ValueError('Invalid private home proxy endpoint')
    paired = (await db.execute(text('SELECT EXISTS(SELECT 1 FROM home_proxy_devices WHERE revoked_at IS NULL)'))).scalar_one()
    _active_proxy = url if paired else ''
