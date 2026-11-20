"""Live discovery freezes its winning route for the following capture attempt."""
import asyncio
from dataclasses import replace
from types import SimpleNamespace

import pytest

from tests.unit.test_proxy_failover import managed  # noqa: F401


async def test_slow_proxy_health_does_not_block_live_supervisor_work(managed, monkeypatch):
    import threading
    from src.recording import capture
    from src.proxies import health
    release = threading.Event()
    health_finished = threading.Event()
    def slow_health(connection):
        release.wait(0.5)
        health_finished.set()
        return True
    async def probe(argv, timeout):
        return 0, {'streams': {'best': {}}}
    monkeypatch.setattr(health, 'available', slow_health)
    monkeypatch.setattr(capture, '_read_json_command', probe)
    task = asyncio.create_task(capture.probe_channel('https://www.youtube.com/@demo'))
    try:
        await asyncio.sleep(0.01)
        assert not health_finished.is_set(), 'Supervisor work waited for blocking health I/O'
        assert not task.done(), 'Slow health checks blocked the event loop until discovery finished'
    finally:
        release.set()
        await task


async def test_live_probe_fails_over_and_returns_the_winning_route(managed, monkeypatch):
    from src.recording import capture
    from src.proxies import health
    used, condemned = [], []
    async def probe(argv, timeout):
        used.append(argv[-1])
        return (0, {'detail': 'youtube_access_blocked'}) if 'first.example' in argv[-1] else (0, {'streams': {'best': {}}})
    monkeypatch.setattr(capture, '_read_json_command', probe)
    monkeypatch.setattr(health, 'failure', lambda c, *args: condemned.append(c.id))
    result = await capture.probe_channel('https://www.youtube.com/@demo')
    assert result.state == capture.ProbeState.LIVE
    assert result.proxy_key == managed[1][1].key
    assert used == ['http://first.example:80', 'http://second.example:80'] and condemned == ['first']


async def test_offline_is_not_a_proxy_failure_or_reason_to_probe_every_route(managed, monkeypatch):
    from src.recording import capture
    from src.proxies import health
    used, condemned = [], []
    async def probe(argv, timeout):
        used.append(argv[-1]); return 0, {'error': 'The channel is offline'}
    monkeypatch.setattr(capture, '_read_json_command', probe)
    monkeypatch.setattr(health, 'failure', lambda c, *args: condemned.append(c.id))
    assert (await capture.probe_channel('https://www.youtube.com/@demo')).state == capture.ProbeState.OFFLINE
    assert used == ['http://first.example:80'] and condemned == []


async def test_import_only_routes_are_not_used_for_live_discovery(managed, monkeypatch):
    from src.recording import capture
    save, rows = managed
    save([replace(c, usage='imports') for c in rows])
    used = []
    async def probe(argv, timeout):
        used.append(argv[-1]); return 0, {'streams': {'best': {}}}
    monkeypatch.setattr(capture, '_read_json_command', probe)
    assert (await capture.probe_channel('https://www.youtube.com/@demo')).state == capture.ProbeState.LIVE
    assert used == ['']


async def test_all_unavailable_live_routes_do_not_spawn_a_direct_probe(managed, monkeypatch):
    from src.recording import capture
    from src.proxies import health
    used = []
    monkeypatch.setattr(health, 'available', lambda c: False)
    async def probe(argv, timeout):
        used.append(argv); return 0, {'streams': {'best': {}}}
    monkeypatch.setattr(capture, '_read_json_command', probe)
    result = await capture.probe_channel('https://www.youtube.com/@demo')
    assert result.state == capture.ProbeState.UNKNOWN and result.detail == 'proxy_pool_unavailable'
    assert used == []


async def test_capture_uses_the_probed_route_even_after_priority_changes(managed, monkeypatch, tmp_path):
    from src.recording import capture
    save, rows = managed
    save([replace(rows[0], priority=0), replace(rows[1], priority=10)])
    used = []
    class Process:
        returncode = None
        stderr = None
        async def wait(self):
            self.returncode = 0
    async def launch(*argv, **kwargs):
        used.append(argv); return Process()
    async def stop(process, *args, **kwargs):
        process.returncode = 0
    monkeypatch.setattr(capture.asyncio, 'create_subprocess_exec', launch)
    monkeypatch.setattr(capture, '_terminate', stop)
    process = capture.CaptureProcess(tmp_path / 'attempt', 'https://www.youtube.com/@demo', proxy_key=rows[1].key)
    await process.start()
    try:
        producer = next(argv for argv in used if '-m' in argv)
        assert producer[producer.index('--proxy') + 1] == 'http://second.example:80'
        assert 'ffmpeg:-copyts' in producer
    finally:
        await process.stop()


async def test_removing_the_probed_route_does_not_turn_capture_into_a_direct_connection(managed, monkeypatch, tmp_path):
    from src.recording import capture
    from src.proxies.routing import ProxyUnavailableError
    save, rows = managed
    save([])
    used = []
    async def launch(*argv, **kwargs):
        used.append(argv)
    monkeypatch.setattr(capture.asyncio, 'create_subprocess_exec', launch)
    process = capture.CaptureProcess(tmp_path / 'attempt', 'https://www.youtube.com/@demo', proxy_key=rows[1].key)
    with pytest.raises(ProxyUnavailableError):
        await process.start()
    assert used == []


@pytest.mark.parametrize('message,expected', [
    ('ERROR: HTTP Error 403: Forbidden', ['first']),
    ('ERROR: Invalid data found when processing input', []),
    ('ERROR: Private video. HTTP Error 403: Forbidden', []),
])
async def test_live_media_access_failure_can_rotate_without_condemning_local_or_private_content(managed, monkeypatch, tmp_path, message, expected):
    from src.recording import capture
    from src.proxies import health
    failures = []
    monkeypatch.setattr(health, 'failure', lambda c, *args: failures.append(c.id))
    process = capture.CaptureProcess(tmp_path, 'https://www.youtube.com/@demo', proxy_key=managed[1][0].key)
    stream = asyncio.StreamReader()
    stream.feed_data(message.encode()); stream.feed_eof()
    await process._observe_errors(stream)
    await process.report_connection_failure()
    assert failures == expected
