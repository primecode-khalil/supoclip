"""Shared, disposable health hints; registry configuration remains authoritative."""
import time

import redis

from .models import Connection

_FAILURE = '''
local stamp=tonumber(redis.call('TIME')[1])
local failures=redis.call('HINCRBY',KEYS[1],'failures',1)
local delay=math.min(900,30*2^math.min(5,failures-1))
redis.call('HSET',KEYS[1],'cooldown_until',stamp+delay,'checked_at',stamp,
 'result','failed','purpose',ARGV[1],'reason',ARGV[2])
redis.call('EXPIRE',KEYS[1],86400)
return delay
'''
_SUCCESS = '''
local stamp=tonumber(redis.call('TIME')[1])
redis.call('HSET',KEYS[1],'failures',0,'cooldown_until',0,'checked_at',stamp,
 'result',ARGV[2],'purpose',ARGV[1])
redis.call('HDEL',KEYS[1],'reason')
redis.call('EXPIRE',KEYS[1],86400)
return 1
'''


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
    return _cooldown(state(connection)) <= time.time()


def _cooldown(data: dict) -> float:
    try:
        value = float(data.get('cooldown_until', 0))
        return value if 0 <= value < float('inf') else 0
    except (ValueError, TypeError):
        return 0


def failure(connection: Connection, purpose: str, reason: str) -> None:
    if purpose not in {'imports', 'live'} or reason not in {'transport', 'access', 'authentication'}:
        raise ValueError('Unknown proxy failure category')
    try:
        with _redis() as client:
            client.eval(_FAILURE, 1, 'supoclip:proxy:' + connection.key, purpose, reason)
    except redis.RedisError:
        pass


def success(connection: Connection, purpose: str, *, result='working') -> None:
    if purpose not in {'imports', 'live'} or result not in {'working', 'reachable'}:
        raise ValueError('Unknown proxy success category')
    try:
        with _redis() as client:
            client.eval(_SUCCESS, 1, 'supoclip:proxy:' + connection.key, purpose, result)
    except redis.RedisError:
        pass


def present(connection: Connection) -> dict:
    data = state(connection)
    until = _cooldown(data)
    status = 'unavailable' if not connection.url else 'cooldown' if until > time.time() else data.get('result', 'not_checked')
    return {'status': status, 'retry_after_seconds': max(0, int(until - time.time())),
            'last_checked_at': data.get('checked_at'), 'last_purpose': data.get('purpose')}
