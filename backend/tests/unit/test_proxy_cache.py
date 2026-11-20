"""Refreshing settings must never briefly remove an assigned ingestion route."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.fixture
def cache_loader(monkeypatch):
    from src import home_proxy, runtime_settings
    from src.proxies.models import Connection, Registry, SETTING_KEY
    registry = Registry((Connection('home', 'Home', 'http://proxy:80', revision='v1'),)).encode()
    monkeypatch.setattr(home_proxy, 'refresh_home_proxy', AsyncMock())
    monkeypatch.setattr(runtime_settings, '_settings_cache', {SETTING_KEY: registry, 'REMOVED': 'old'})
    monkeypatch.setattr(runtime_settings, '_prefer_admin_value_cache', set())
    monkeypatch.setattr(runtime_settings, 'decrypt_setting_value', lambda value: value)
    def database(value):
        result = SimpleNamespace(mappings=lambda: [{'setting_key': SETTING_KEY, 'encrypted_value': value, 'prefer_admin_value': True}])
        return SimpleNamespace(execute=AsyncMock(return_value=result))
    return runtime_settings, database, registry


async def test_refresh_keeps_assigned_route_visible_to_an_interleaved_reader(cache_loader, monkeypatch):
    from src.proxies import routing
    runtime, database, registry = cache_loader
    observations = []
    class InterleavedReader(dict):
        def clear(self):
            super().clear()
            observations.append(routing.configured('imports'))
        def update(self, values):
            observations.append(routing.configured('imports'))
            super().update(values)
    monkeypatch.setattr(runtime, '_settings_cache', InterleavedReader(runtime._settings_cache))
    await runtime.load_runtime_settings_cache(database(registry))
    assert all(observations), 'A reader observed an unassigned path during refresh'
    assert routing.configured('imports') and 'REMOVED' not in runtime._settings_cache


@pytest.mark.parametrize('value', ['', '  '])
async def test_an_empty_saved_registry_is_unavailable_instead_of_legacy_routing(cache_loader, value):
    from src.proxies import routing
    runtime, database, _ = cache_loader
    await runtime.load_runtime_settings_cache(database(value))
    assert routing.configured('imports') and routing.configured('live')
    assert routing.snapshot().unavailable
