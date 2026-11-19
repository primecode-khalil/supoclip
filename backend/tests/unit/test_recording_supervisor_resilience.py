"""Capture safety remains live while processing or recovery is blocked.

These tests exercise the real channel loops and cancellation lifecycle. Stream
capture, database access and long-running external work are the isolated edges.
"""
import asyncio
import hashlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from src.recording.automation_schema import AutomationPolicy
from src.recording.automation_store import Lease
from src.recording.capture import ClosedSegment, ProbeResult, ProbeState
from src.workers import recording_supervisor as supervisor


class OwnedCapture:
    def __init__(self):
        self.running = True
        self.stalled = False
        self.stopped = asyncio.Event()

    async def poll(self):
        return []

    async def stop(self):
        self.running = False
        self.stopped.set()


class WaitingPipeline:
    def __init__(self):
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.cancelled = asyncio.Event()

    async def _live(self, token):
        return None

    async def step(self, channel, token, window):
        self.entered.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise


@pytest.fixture
def existing_sequences(monkeypatch):
    """The durable window lookup is a read-only database boundary."""
    sequences = set()

    class Database:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def execute(self, statement):
            return self

        def scalars(self):
            return self

        def all(self):
            return sorted(sequences)

    monkeypatch.setattr(supervisor, "AsyncSessionLocal", Database)
    return sequences


def runner_with_capture(tmp_path, pipeline):
    policy = AutomationPolicy(enabled=True)
    channel = SimpleNamespace(channel_id="channel", user_id="owner", url="https://www.twitch.tv/demo", quality="best", policy=policy)
    token = Lease("channel", "holder", 1, datetime.now(timezone.utc) + timedelta(seconds=60))
    settings = supervisor.RuntimeSettings(tmp_path, 1_000_000, 1, 24)
    runner = supervisor.ChannelRunner(channel, token, settings, pipeline)
    epoch = tmp_path / "channel" / "session" / "epoch"
    supervisor.atomic_json(epoch / "epoch.json", {"session_id": "session", "epoch": "epoch", "policy": policy.model_dump(), "fence": 1})
    capture = OwnedCapture()
    runner.capture, runner.capture_epoch = capture, epoch
    runner.readers[epoch] = capture
    return runner, capture


async def cancel_and_reap(task):
    if not task.done():
        task.cancel()
    await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize('failure', ['probe', 'capture'])
async def test_capture_retries_within_one_minute_after_many_connection_failures(tmp_path, monkeypatch, failure):
    runner, capture = runner_with_capture(tmp_path, WaitingPipeline())
    runner.failures = 8  # A long outage must not leave a reconnected Mac waiting an hour.
    if failure == 'probe':
        runner.capture = None
    else:
        capture.stalled = True
    observed = asyncio.Event()
    blocked = asyncio.Event()
    real_sleep = asyncio.sleep

    async def background():
        await blocked.wait()

    async def backlog():
        return 0

    async def probe(*args, **kwargs):
        return ProbeResult(ProbeState.UNKNOWN, 'probe_unavailable')

    async def sleep(seconds):
        if seconds == 5:
            observed.set()
            await blocked.wait()
        else:
            await real_sleep(seconds)

    async def store(method, *args, **kwargs):
        assert method in {'report_error', 'finish_session', 'release'}

    monkeypatch.setattr(runner, '_background_work', background)
    monkeypatch.setattr(runner, '_backlog', backlog)
    monkeypatch.setattr(supervisor, 'probe_channel', probe)
    monkeypatch.setattr(supervisor, 'store_call', store)
    monkeypatch.setattr(supervisor.shutil, 'disk_usage', lambda _: SimpleNamespace(free=10_000_000))
    monkeypatch.setattr(supervisor.asyncio, 'sleep', sleep)
    task = asyncio.create_task(runner.run())
    try:
        await asyncio.wait_for(observed.wait(), timeout=1)
        assert 0 < runner.next_probe - supervisor.time.monotonic() <= 60
    finally:
        await cancel_and_reap(task)


async def test_disk_guard_stops_capture_while_pipeline_is_still_waiting(tmp_path, monkeypatch, existing_sequences):
    """Awaiting upload/archive work in the monitor would leave capture running."""
    pipeline = WaitingPipeline()
    runner, capture = runner_with_capture(tmp_path, pipeline)
    real_sleep = asyncio.sleep
    disk_checks = 0

    def disk_usage(_):
        nonlocal disk_checks
        disk_checks += 1
        return SimpleNamespace(free=10_000_000 if disk_checks == 1 else 0)

    async def sleep(seconds):
        if seconds == 5:
            await pipeline.entered.wait()
            await real_sleep(0)
        else:
            await real_sleep(seconds)

    async def store(method, *args, **kwargs):
        if method == "list_pending":
            return [SimpleNamespace(id="pending-window")]
        if method in {"finish_session", "report_error", "release"}:
            return None
        raise AssertionError(f"Unexpected database access: {method}")

    async def backlog():
        return 0

    monkeypatch.setattr(supervisor, "store_call", store)
    monkeypatch.setattr(supervisor.shutil, "disk_usage", disk_usage)
    monkeypatch.setattr(supervisor.asyncio, "sleep", sleep)
    monkeypatch.setattr(runner, "_backlog", backlog)
    task = asyncio.create_task(runner.run())
    try:
        await asyncio.wait_for(pipeline.entered.wait(), timeout=1)
        await asyncio.wait_for(capture.stopped.wait(), timeout=1)
        assert not pipeline.release.is_set()
        assert not task.done(), "A slow pipeline must not crash its capture monitor"
        assert (tmp_path / "channel/session/epoch/ended.json").is_file()
    finally:
        await cancel_and_reap(task)
    assert pipeline.cancelled.is_set(), "Shutdown must reap the tracked processing task"


async def test_lease_loss_cancels_processing_and_stops_owned_capture(tmp_path, monkeypatch, existing_sequences):
    """Ignoring a failed renewal would let the old owner continue writing media."""
    pipeline = WaitingPipeline()
    runner, capture = runner_with_capture(tmp_path, pipeline)
    real_sleep = asyncio.sleep
    released = asyncio.Event()

    async def sleep(seconds):
        if seconds == 15:
            await pipeline.entered.wait()
        else:
            await real_sleep(seconds)

    async def store(method, *args, **kwargs):
        if method == "list_pending":
            return [SimpleNamespace(id="pending-window")]
        if method == "renew":
            return None
        if method == "release":
            released.set()
            return False
        if method == "finish_session":
            raise supervisor.LostLeaseError()
        raise AssertionError(f"Unexpected database access: {method}")

    async def backlog():
        return 0

    monkeypatch.setattr(supervisor, "store_call", store)
    monkeypatch.setattr(supervisor.shutil, "disk_usage", lambda _: SimpleNamespace(free=10_000_000))
    monkeypatch.setattr(supervisor.asyncio, "sleep", sleep)
    monkeypatch.setattr(runner, "_backlog", backlog)
    task = asyncio.create_task(runner.run())
    try:
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=1)
    finally:
        await cancel_and_reap(task)
    assert capture.stopped.is_set()
    assert pipeline.cancelled.is_set()
    assert released.is_set()


async def test_malformed_epoch_does_not_starve_already_pending_work(tmp_path, monkeypatch, existing_sequences):
    """A corrupt old manifest must not restart the channel before pending work."""
    pipeline = WaitingPipeline()
    runner, _ = runner_with_capture(tmp_path, pipeline)
    broken = tmp_path / "channel" / "older-session" / "older-epoch" / "epoch.json"
    broken.parent.mkdir(parents=True)
    broken.write_text("{partial-json")
    visible_errors = []

    async def store(method, *args, **kwargs):
        if method == "list_pending":
            return [SimpleNamespace(id="already-registered")]
        if method == "report_error":
            visible_errors.append(args[1])
            return None
        raise AssertionError(f"Unexpected database access: {method}")

    monkeypatch.setattr(supervisor, "store_call", store)
    work = asyncio.create_task(runner._background_work())
    progress = asyncio.create_task(pipeline.entered.wait())
    try:
        done, _ = await asyncio.wait((work, progress), timeout=1, return_when=asyncio.FIRST_COMPLETED)
        if work in done:
            await work
        assert progress in done, "An invalid epoch prevented existing work from progressing"
        assert visible_errors, "The operator must see that a capture manifest needs recovery"
        assert broken.exists(), "Recovery must retain malformed input for inspection"
    finally:
        await cancel_and_reap(work)
        await cancel_and_reap(progress)


async def test_failed_remux_registers_original_once_and_reuses_receipt_after_restart(tmp_path, monkeypatch, existing_sequences):
    """A remux error must not poison later recovery or change replayed media."""
    pipeline = WaitingPipeline()
    runner, _ = runner_with_capture(tmp_path, pipeline)
    epoch = runner.capture_epoch
    original = epoch / "segments" / "chunk_000000.mkv"
    original.parent.mkdir()
    original.write_bytes(b"verified finalized original")
    segment = ClosedSegment(original, 0, 0.0, 600.0, hashlib.sha256(original.read_bytes()).hexdigest(), original.stat().st_size)
    runner.segments[epoch] = {0: segment}
    registrations = []
    remux_attempts = 0

    async def fail_remux(*args, **kwargs):
        nonlocal remux_attempts
        remux_attempts += 1
        raise ValueError("Container cannot stream-copy this codec")

    async def store(method, *args, **kwargs):
        if method == "register_window":
            registrations.append((args, kwargs))
            existing_sequences.add(args[3])
            return SimpleNamespace(id="durable-original-window")
        if method == "report_error":
            return None
        raise AssertionError(f"Unexpected database access: {method}")

    class RecoveredCapture(OwnedCapture):
        def __init__(self, *args, **kwargs):
            super().__init__()

        async def poll(self):
            return [segment]

    monkeypatch.setattr(supervisor, "store_call", store)
    monkeypatch.setattr(supervisor, "prepare_window", fail_remux)
    monkeypatch.setattr(supervisor, "CaptureProcess", RecoveredCapture)
    await runner._recover()
    await runner._recover()
    new_token = Lease("channel", "replacement", 2, datetime.now(timezone.utc) + timedelta(seconds=60))
    restarted = supervisor.ChannelRunner(runner.channel, new_token, runner.settings, pipeline)
    await restarted._recover()
    assert len(registrations) == 1
    arguments, keyword = registrations[0]
    assert arguments[4] == "channel/session/epoch/segments/chunk_000000.mkv"
    assert arguments[5] == hashlib.sha256(b"verified finalized original").hexdigest()
    assert arguments[9] == 0
    assert keyword["metadata"]["preparation_warning"]
    assert remux_attempts == 1, "A persisted original binding must not be remuxed after restart"
    assert original.read_bytes() == b"verified finalized original"
    assert (epoch / "ended.json").is_file(), "A new fence must close its predecessor's orphan epoch"
