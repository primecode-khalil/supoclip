"""Shared, disposable health hints; registry configuration remains authoritative."""
import time

import redis

from .models import Connection


def _redis():
    from ..config import get_config
    config = get_config()
    return redis.Redis(host=config.redis_host, port=config.redis_port, password=config.redis_password,
                       decode_responses=True, socket_timeout=1, socket_connect_timeout=1)


def state(connection: Connection) -> dict:
    try:
        with _redis() as client:
            return client.hgetall('supoclip:proxy:' + connection.key)
    except redis.RedisError:
        return {}  # Re-test configured proxies; never substitute a direct route.


def available(connection: Connection) -> bool:
    return float(state(connection).get('cooldown_until', 0)) <= time.time()


def present(connection: Connection) -> dict:
    data = state(connection)
    until = float(data.get('cooldown_until', 0))
    status = 'unavailable' if not connection.url else 'cooldown' if until > time.time() else data.get('result', 'not_checked')
    return {'status': status, 'retry_after_seconds': max(0, int(until - time.time())),
            'last_checked_at': data.get('checked_at'), 'last_purpose': data.get('purpose')}
