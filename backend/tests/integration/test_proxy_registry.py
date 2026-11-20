"""A shared encrypted registry replaces scattered settings without losing them."""
import asyncio

import pytest
from sqlalchemy import text

from tests.integration.test_home_proxy import admin, relay, issue, redeem, KEY, SECOND_KEY, signed_headers  # noqa: F401
from tests.fixtures.factories import create_user


@pytest.fixture
async def proxy_registry(db_session, monkeypatch):
    from src import runtime_settings, home_proxy
    monkeypatch.setenv('APP_SETTINGS_ENCRYPTION_KEY', 'proxy-registry-test-encryption-key')
    monkeypatch.delenv('YOUTUBE_PROXY_URL', raising=False)
    monkeypatch.delenv('HOME_PROXY_URL', raising=False)
    monkeypatch.setattr(runtime_settings, '_settings_cache', {})
    await db_session.execute(text("DELETE FROM app_settings WHERE setting_key='PROXY_CONNECTIONS'"))
    await db_session.commit()
    runtime_settings._settings_cache.pop('PROXY_CONNECTIONS', None)
    home_proxy.clear_active_proxy()
    yield
    await db_session.execute(text("DELETE FROM app_settings WHERE setting_key='PROXY_CONNECTIONS'"))
    await db_session.commit()
    runtime_settings._settings_cache.pop('PROXY_CONNECTIONS', None)
    home_proxy.clear_active_proxy()


async def add(client, admin, **fields):
    response = await client.post('/proxy/connections', headers=admin, json={
        'name': 'Backup', 'url': 'http://user:private-password@proxy.example:8000', 'usage': 'both', **fields})
    assert response.status_code == 200, response.text
    return response.json()


async def test_registry_is_admin_only_and_never_echoes_secrets(proxy_registry, client, admin, db_session):
    assert (await client.get('/proxy')).status_code == 401
    regular = await create_user(db_session)
    try:
        assert (await client.get('/proxy', headers=signed_headers(regular['id']))).status_code == 403
    finally:
        await db_session.execute(text('DELETE FROM users WHERE id=:id'), {'id': regular['id']})
        await db_session.commit()
    data = await add(client, admin)
    assert data['connections'][0]['endpoint'] == 'proxy.example:8000'
    assert 'private-password' not in str(data) and 'http://user:' not in str(data)
    encrypted = (await db_session.execute(text("SELECT encrypted_value FROM app_settings WHERE setting_key='PROXY_CONNECTIONS'"))).scalar_one()
    assert 'private-password' not in encrypted and 'proxy.example' not in encrypted
    from src.runtime_settings import decrypt_setting_value
    assert 'private-password' in decrypt_setting_value(encrypted)
    generic = await client.get('/admin/runtime-settings', headers=admin)
    assert 'PROXY_CONNECTIONS' not in generic.text


async def test_edit_keeps_secret_reorders_and_does_not_reimport_deleted_legacy(proxy_registry, client, admin, monkeypatch):
    monkeypatch.setenv('YOUTUBE_PROXY_URL', 'http://legacy:secret@old-proxy.example:8080')
    first = await client.get('/proxy', headers=admin)
    assert first.status_code == 200, first.text
    legacy = first.json()['connections'][0]
    data = await add(client, admin, name='Second')
    second = next(c for c in data['connections'] if c['name'] == 'Second')
    edited = await client.patch(f"/proxy/connections/{second['id']}", headers=admin,
        json={'name': 'Preferred', 'url': '', 'usage': 'imports', 'enabled': True, 'expected_revision': second['revision']})
    assert edited.status_code == 200, edited.text
    latest = next(c for c in edited.json()['connections'] if c['id'] == second['id'])
    assert latest['endpoint'] == second['endpoint'] and latest['revision'] == second['revision']
    ordered = await client.put('/proxy/order', headers=admin, json={'connection_ids': [second['id'], legacy['id']]})
    assert ordered.status_code == 200
    assert [c['id'] for c in ordered.json()['connections']] == [second['id'], legacy['id']]
    assert (await client.delete(f"/proxy/connections/{legacy['id']}", headers=admin)).status_code == 200
    reread = await client.get('/proxy', headers=admin)
    assert [c['id'] for c in reread.json()['connections']] == [second['id']]
    stale_order = await client.put('/proxy/order', headers=admin, json={'connection_ids': [second['id'], legacy['id']]})
    assert stale_order.status_code == 409


async def test_invalid_or_unknown_input_is_bounded_and_secret_free(proxy_registry, client, admin):
    bad = await client.post('/proxy/connections', headers=admin,
        json={'name': 'Bad', 'url': 'http://user:private-password@proxy.example/path'})
    assert bad.status_code == 400 and 'private-password' not in bad.text
    for n in range(10):
        await add(client, admin, name=f'Proxy {n}')
    over = await client.post('/proxy/connections', headers=admin, json={'name': 'Too many', 'url': 'http://proxy:80'})
    assert over.status_code == 409


async def test_edited_url_resets_health_identity_and_rejects_stale_edit(proxy_registry, client, admin):
    item = (await add(client, admin))['connections'][0]
    updated = await client.patch(f"/proxy/connections/{item['id']}", headers=admin,
        json={'url': 'http://new-secret@new.example:80', 'expected_revision': item['revision']})
    assert updated.status_code == 200
    fresh = updated.json()['connections'][0]
    assert fresh['revision'] != item['revision'] and fresh['endpoint'] == 'new.example:80'
    stale = await client.patch(f"/proxy/connections/{item['id']}", headers=admin,
        json={'enabled': False, 'expected_revision': item['revision']})
    assert stale.status_code == 409


async def test_registry_reloads_in_another_worker_and_keeps_secrets_private(proxy_registry, client, admin, db_session):
    from src import runtime_settings
    from src.proxies.routing import snapshot
    item = (await add(client, admin, usage='live'))['connections'][0]
    runtime_settings._settings_cache.pop('PROXY_CONNECTIONS')
    await runtime_settings.load_runtime_settings_cache(db_session)
    held = snapshot().connections[0]
    assert held.id == item['id'] and held.usage == 'live'
    assert held.url == 'http://user:private-password@proxy.example:8000'
    assert snapshot().required('imports') is False
    assert snapshot().required('live') is True


async def test_mac_adoption_and_replacement_preserve_route_choices(proxy_registry, relay, client, admin):
    token = await issue(client, admin, 'Existing Mac')
    assert (await redeem(client, token)).status_code == 200
    data = (await client.get('/proxy', headers=admin)).json()
    home = data['connections'][0]
    assert home['kind'] == 'home' and home['usage'] == 'both'
    edited = await client.patch('/proxy/connections/home', headers=admin,
        json={'expected_revision': home['revision'], 'usage': 'live', 'enabled': False})
    assert edited.status_code == 200, edited.text
    token = await issue(client, admin, 'Replacement Mac')
    assert (await redeem(client, token, SECOND_KEY)).status_code == 200
    updated = (await client.get('/proxy', headers=admin)).json()['connections'][0]
    assert updated['id'] == home['id'] and updated['usage'] == 'live' and updated['enabled'] is False
    assert updated['revision'] != home['revision']


async def test_removing_mac_against_inflight_pairing_cannot_resurrect_it(proxy_registry, relay, client, admin, db_session):
    assert (await redeem(client, await issue(client, admin))).status_code == 200
    assert (await client.get('/proxy', headers=admin)).status_code == 200
    token = await issue(client, admin, 'Replacement')
    deleted, paired = await asyncio.gather(client.delete('/proxy/connections/home', headers=admin), redeem(client, token, SECOND_KEY))
    assert deleted.status_code == 200, deleted.text
    assert paired.status_code in {200, 400}, paired.text
    final = (await client.get('/proxy', headers=admin)).json()
    assert final['connections'] == []
    assert (await db_session.execute(text('SELECT count(*) FROM home_proxy_devices WHERE revoked_at IS NULL'))).scalar_one() == 0
