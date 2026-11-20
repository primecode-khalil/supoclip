"""Independent workers share cooldowns, without storing credentials or errors."""
from dataclasses import replace
import os
from uuid import uuid4

import pytest
import redis


@pytest.fixture
def proxy_health(monkeypatch):
    from src.proxies import health
    from src.proxies.models import Connection
    port = int(os.environ.get('REDIS_PORT', '6379'))
    make = lambda: redis.Redis(host=os.environ.get('REDIS_HOST', '127.0.0.1'), port=port, decode_responses=True)
    monkeypatch.setattr(health, '_redis', make)
    connection = Connection('test_' + uuid4().hex, 'Test', 'http://user:secret@proxy:80', revision='one')
    with make() as client:
        assert client.ping()
    yield health, connection
    with make() as client:
        client.delete('supoclip:proxy:' + connection.key, 'supoclip:proxy:' + replace(connection, revision='two').key)


def test_failure_backoff_is_shared_bounded_and_reset_by_success(proxy_health):
    health, connection = proxy_health
    assert health.available(connection)
    for delay in [30, 60, 120, 240, 480, 900, 900]:
        health.failure(connection, 'imports', 'transport')
        assert not health.available(connection)
        state = health.present(connection)
        assert state['status'] == 'cooldown'
        assert delay - 2 <= state['retry_after_seconds'] <= delay
        assert 'secret' not in str(state) and 'proxy:80' not in str(state)
    health.success(connection, 'imports')
    assert health.available(connection)
    assert health.present(connection)['status'] == 'working'
    assert health.state(connection)['failures'] == '0'


def test_an_old_endpoint_failure_does_not_poison_a_replacement(proxy_health):
    health, connection = proxy_health
    health.failure(connection, 'live', 'access')
    changed = replace(connection, revision='two')
    assert health.available(changed)
    assert health.present(changed)['status'] == 'not_checked'


def test_losing_redis_only_loses_health_hints(proxy_health, monkeypatch):
    health, connection = proxy_health
    def unavailable():
        raise redis.ConnectionError('offline')
    monkeypatch.setattr(health, '_redis', unavailable)
    assert health.available(connection) is True
    assert health.present(connection)['status'] == 'not_checked'
    health.failure(connection, 'live', 'transport')
    health.success(connection, 'imports')
