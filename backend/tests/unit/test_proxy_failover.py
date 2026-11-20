"""Real retry orchestration must never swap in an unassigned direct route."""
from dataclasses import replace
from types import SimpleNamespace

import pytest

from src.proxies.models import Connection, Registry, SETTING_KEY


@pytest.fixture
def managed(monkeypatch):
    from src import runtime_settings
    from src.proxies import health
    monkeypatch.setattr(runtime_settings, '_settings_cache', {})
    monkeypatch.setattr(health, 'state', lambda connection: {})
    monkeypatch.setattr(health, 'failure', lambda *args, **kwargs: None, raising=False)
    monkeypatch.setattr(health, 'success', lambda *args, **kwargs: None, raising=False)
    rows = (Connection('first', 'First', 'http://first.example:80', revision='v1'),
            Connection('second', 'Second', 'http://second.example:80', revision='v1'))

    def save(connections=rows):
        runtime_settings._settings_cache[SETTING_KEY] = Registry(tuple(connections)).encode()
    save()
    return save, rows


def test_bot_challenge_moves_to_next_proxy_and_keeps_the_successful_route_for_this_job(managed, monkeypatch):
    from src import youtube_proxy as download
    from src.proxies import health
    routes, failures, cleanups = [], [], []
    monkeypatch.setattr(health, 'failure', lambda c, *args: failures.append(c.id))

    def operation(options):
        routes.append(options['proxy'])
        if 'first.example' in options['proxy']:
            raise download.YouTubeAccessBlockedError()
        return 'completed'
    budget = download.ByteBudget(100)
    result = download._with_proxy_retry(operation, task_id='task', video_id='video', budget=budget,
        cleanup=lambda: cleanups.append(True))
    assert result == 'completed' and routes == ['http://first.example:80', 'http://second.example:80']
    assert failures == ['first'] and cleanups == [True]
    routes.clear()
    assert download._with_proxy_retry(operation, task_id='task', video_id='video', budget=budget, cleanup=lambda: None) == 'completed'
    assert routes == ['http://second.example:80']


def test_live_only_connections_are_never_used_for_imports(managed):
    from src import youtube_proxy as download
    save, rows = managed
    save([replace(rows[0], usage='live'), replace(rows[1], usage='imports')])
    used = []
    download._with_proxy_retry(lambda options: used.append(options['proxy']), task_id='t', video_id='v',
                               budget=download.ByteBudget(100), cleanup=lambda: None)
    assert used == ['http://second.example:80']


def test_cooling_routes_are_skipped_but_exhaustion_does_not_enable_direct(managed, monkeypatch):
    from src import youtube_proxy as download
    from src.proxies import health, routing
    monkeypatch.setattr(health, 'available', lambda c: False)
    used = []
    with pytest.raises(routing.ProxyUnavailableError):
        download._with_proxy_retry(lambda options: used.append(options), task_id='t', video_id='v',
                                   budget=download.ByteBudget(100), cleanup=lambda: None)
    assert used == [] and download.proxy_configured() is True
    from src.youtube_utils import _provider_order
    assert _provider_order(SimpleNamespace(), skip_proxy=True) == [download.YOUTUBE_DOWNLOAD_PROVIDER_YTDLP_PROXY]


@pytest.mark.parametrize('failure', ['age', 'budget', 'local'])
def test_content_budget_or_local_errors_do_not_condemn_proxies_or_try_every_route(managed, monkeypatch, failure):
    from src import youtube_proxy as download
    from src.proxies import health
    errors = {'age': download.YouTubeAgeRestrictedError(), 'budget': download.DownloadBudgetExceeded('limit'),
              'local': download.PartialDownloadUnavailable('No valid audio format')}
    attempts, condemned = [], []
    monkeypatch.setattr(health, 'failure', lambda c, *args: condemned.append(c.id))
    def operation(options):
        attempts.append(options['proxy'])
        raise errors[failure]
    with pytest.raises(type(errors[failure])):
        download._with_proxy_retry(operation, task_id='t', video_id='v',
                                   budget=download.ByteBudget(100), cleanup=lambda: None)
    assert attempts == ['http://first.example:80'] and condemned == []


def test_job_bytes_remain_shared_when_an_attempt_fails(managed):
    from src import youtube_proxy as download
    budget = download.ByteBudget(10)
    def operation(options):
        budget.add(6)
        if 'first.example' in options['proxy']:
            raise download.YouTubeAccessBlockedError()
        return 'over budget'
    with pytest.raises(download.DownloadBudgetExceeded):
        download._with_proxy_retry(operation, task_id='t', video_id='v', budget=budget, cleanup=lambda: None)
    assert budget.snapshot() == 12


def test_country_and_session_affinity_are_separate_per_connection(managed):
    from src.proxies import routing
    from src.youtube_proxy import ByteBudget
    _, rows = managed
    budget = ByteBudget(100)
    with routing.using(rows[0], 'imports'):
        budget.remember_proxy_route('t', 'v', 'us', 'session-a')
    with routing.using(rows[1], 'imports'):
        assert budget.proxy_route('t', 'v') is None
        budget.remember_proxy_route('t', 'v', 'gb', 'session-b')
    with routing.using(rows[0], 'imports'):
        assert budget.proxy_route('t', 'v') == ('us', 'session-a')
    assert routing.current('imports') is None


def test_a_source_specific_403_can_try_another_route_without_global_cooldown(managed, monkeypatch):
    from src import youtube_proxy as download
    from src.proxies import health
    condemned, attempted = [], []
    monkeypatch.setattr(health, 'failure', lambda c, *args: condemned.append(c.id))
    def operation(options):
        attempted.append(options['proxy'])
        if 'first.example' in options['proxy']:
            raise RuntimeError('HTTP Error 403: Forbidden')
        return 'ok'
    assert download._with_proxy_retry(operation, task_id='t', video_id='v',
        budget=download.ByteBudget(10), cleanup=lambda: None) == 'ok'
    assert len(attempted) == 2 and condemned == []


def test_disabling_a_standby_during_an_attempt_prevents_its_use(managed):
    from src import youtube_proxy as download
    save, rows = managed
    attempted = []
    def operation(options):
        attempted.append(options['proxy'])
        save([rows[0], replace(rows[1], enabled=False)])
        raise download.YouTubeAccessBlockedError()
    with pytest.raises(download.YouTubeAccessBlockedError):
        download._with_proxy_retry(operation, task_id='t', video_id='v', budget=download.ByteBudget(10), cleanup=lambda: None)
    assert attempted == ['http://first.example:80']


def test_failover_does_not_extend_the_callers_deadline(managed, monkeypatch):
    from src import youtube_proxy as download
    clock, attempted = [100.0], []
    monkeypatch.setattr(download.time, 'monotonic', lambda: clock[0])
    def operation(options):
        attempted.append(options['proxy'])
        clock[0] += 5
        raise download.YouTubeAccessBlockedError()
    with pytest.raises(download.YouTubeAccessBlockedError):
        download._with_proxy_retry(operation, task_id='t', video_id='v', budget=download.ByteBudget(10), cleanup=lambda: None, deadline=103)
    assert attempted == ['http://first.example:80']


def test_library_diagnostics_do_not_expose_a_credentialed_endpoint(managed, caplog):
    from src.youtube_proxy import base_proxy_params
    save, rows = managed
    save([replace(rows[0], url='socks5h://api-user:private-password@proxy.example:1080')])
    options = base_proxy_params('task', 'video')
    options['logger'].warning('Proxy failure socks5h://api-user:private-password@proxy.example:1080 private-password')
    assert 'private-password' not in caplog.text and 'api-user' not in caplog.text
