"""Dedicated live recorder, independent of API and finite ARQ render jobs.

Run with ``python -m src.workers.recording_supervisor``. PostgreSQL leases
fence each channel; finalized CSV entries and immutable windows recover rebooted
capture attempts. Only the process owning a live lease may advance work.
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import re
import shutil
import signal
import time
from uuid import uuid4

from sqlalchemy import select

from ..config import get_config
from ..database import AsyncSessionLocal, init_db
from ..observability import configure_logging
from ..recording.automation_models import RecordingWindow
from ..recording.automation_schema import AutomationPolicy
from ..recording.automation_store import LostLeaseError
from ..recording.capture import CaptureProcess, ProbeState, probe_channel
from ..recording.pipeline import NativeClient, contained_path, retry_delay
from ..recording.runner import AutomationPipeline, store_call
from ..recording.windows import PreparedWindow, prepare_window

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RuntimeSettings:
    root: Path
    min_free_bytes: int
    max_channels: int
    max_backlog: int

    @classmethod
    def from_env(cls):
        root = Path(os.getenv("CAPTURE_ROOT", "/data/recordings"))
        free_gb = float(os.getenv("RECORDING_MIN_FREE_GB", "5"))
        channels = int(os.getenv("RECORDING_MAX_CHANNELS", "4"))
        backlog = int(os.getenv("RECORDING_MAX_BACKLOG", "24"))
        if not root.is_absolute() or not 1 <= free_gb <= 100000 or not 1 <= channels <= 100 or not 1 <= backlog <= 10000:
            raise ValueError("Invalid recording host limits or CAPTURE_ROOT")
        return cls(root.resolve(), int(free_gb * 1024 ** 3), channels, backlog)


def atomic_json(path: Path, value: dict):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf8") as output:
        json.dump(value, output, sort_keys=True)
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def load_epoch(path: Path) -> dict:
    if path.is_symlink() or path.stat().st_size > 65536:
        raise ValueError("Invalid capture epoch manifest")
    value = json.loads(path.read_text())
    if not isinstance(value, dict) or any(not isinstance(value.get(key), str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", value[key]) for key in ("session_id", "epoch")):
        raise ValueError("Invalid capture epoch identity")
    AutomationPolicy.model_validate(value["policy"])
    return value


def healthy(root: Path) -> bool:
    try:
        age = time.time() - (root / ".supervisor-heartbeat").stat().st_mtime
        return 0 <= age <= 120
    except OSError:
        return False


class ChannelRunner:
    def __init__(self, channel, token, settings: RuntimeSettings, pipeline: AutomationPipeline):
        self.channel, self.token, self.settings, self.pipeline = channel, token, settings, pipeline
        self.capture: CaptureProcess | None = None
        self.capture_epoch: Path | None = None
        self.readers: dict[Path, CaptureProcess] = {}
        self.segments: dict[Path, dict] = {}
        self.registered: set[tuple[Path, int]] = set()
        self.loaded_epochs: set[Path] = set()
        self.next_probe = 0.0
        self.failures = 0
        self.offline_count = 0

    async def _heartbeat(self, owner_task):
        while True:
            await asyncio.sleep(15)
            try:
                renewed = await asyncio.wait_for(store_call("renew", self.token), timeout=10)
            except Exception:
                renewed = None
            if renewed is None:
                owner_task.cancel()
                return

    async def _recover(self):
        parent = self.settings.root / self.channel.channel_id
        for manifest in sorted(parent.glob("*/*/epoch.json")):
            epoch = manifest.parent
            if not epoch.resolve().is_relative_to(parent.resolve()):
                continue
            try:
                metadata = load_epoch(manifest)
                if manifest.parent.name != metadata["epoch"] or manifest.parent.parent.name != metadata["session_id"]:
                    raise ValueError("Capture manifest and directory identity differ")
            except (OSError, ValueError, KeyError, TypeError):
                await store_call("report_error", self.token, "An invalid capture manifest was retained for inspection; other work continues")
                continue
            if epoch not in self.loaded_epochs:
                async with AsyncSessionLocal() as db:
                    existing = (await db.execute(select(RecordingWindow.sequence).where(RecordingWindow.channel_id == self.channel.channel_id,
                        RecordingWindow.session_id == metadata["session_id"], RecordingWindow.epoch == metadata["epoch"]))).scalars().all()
                self.registered.update((epoch, sequence) for sequence in existing)
                self.loaded_epochs.add(epoch)
            reader = self.readers.setdefault(epoch, CaptureProcess(epoch / "segments", self.channel.url))
            known = self.segments.setdefault(epoch, {})
            if epoch != self.capture_epoch:
                for segment in await reader.poll():
                    known[segment.sequence] = segment
                if metadata.get("fence", 0) < self.token.fence and not (epoch / "ended.json").exists():
                    await self.pipeline._live(self.token)
                    atomic_json(epoch / "ended.json", {"ended_at": datetime.now(timezone.utc).isoformat(), "recovered": True})
            policy = AutomationPolicy.model_validate(metadata["policy"])
            for sequence, segment in sorted(known.items()):
                identity = (epoch, sequence)
                if identity in self.registered:
                    continue
                await self.pipeline._live(self.token)
                warning = None
                try:
                    prepared = await prepare_window(segment, known.get(sequence - 1), policy.overlap_seconds,
                        epoch / "windows" / f"window_{sequence:06d}.mp4")
                except (OSError, ValueError, TimeoutError):
                    # A valid original may not stream-copy into MP4 (for example
                    # codec/container changes). Native processing can transcode
                    # MKV inputs, so preserve that source and omit the overlap.
                    warning = "Window remux unavailable; processing the verified original without overlap"
                    prepared = PreparedWindow(segment.path, segment.sha256, segment.size_bytes, 0,
                        segment.start_seconds, segment.end_seconds, [{"path": str(segment.path), "sha256": segment.sha256,
                            "size_bytes": segment.size_bytes, "sequence": segment.sequence,
                            "source_start_seconds": segment.start_seconds, "source_end_seconds": segment.end_seconds,
                            "window_start_seconds": 0, "window_end_seconds": segment.end_seconds - segment.start_seconds}])
                provenance = []
                for source in prepared.segments:
                    reference = Path(source["path"]).resolve().relative_to(self.settings.root).as_posix()
                    provenance.append({**source, "path": reference})
                await store_call("register_window", self.token, metadata["session_id"], metadata["epoch"], sequence,
                    prepared.path.relative_to(self.settings.root).as_posix(), prepared.sha256, prepared.size_bytes,
                    prepared.start_seconds, prepared.end_seconds, prepared.overlap_seconds,
                    metadata={"policy": policy.model_dump(), "segments": provenance, **({"preparation_warning": warning} if warning else {})})
                if warning:
                    await store_call("report_error", self.token, warning)
                self.registered.add(identity)

    async def _stop_capture(self, *, interrupted=True):
        if self.capture is None:
            return
        capture, epoch = self.capture, self.capture_epoch
        self.capture, self.capture_epoch = None, None
        await capture.stop()
        known = self.segments.setdefault(epoch, {})
        for segment in await capture.poll():
            known[segment.sequence] = segment
        atomic_json(epoch / "ended.json", {"ended_at": datetime.now(timezone.utc).isoformat()})
        try:
            metadata = load_epoch(epoch / "epoch.json")
            await store_call("finish_session", self.token, metadata["session_id"], "interrupted" if interrupted else "completed")
        except LostLeaseError:
            pass  # The new owner recovers the closed files from CSV.

    async def _backlog(self) -> int:
        async with AsyncSessionLocal() as db:
            from sqlalchemy import func
            return (await db.execute(select(func.count()).select_from(RecordingWindow).where(
                RecordingWindow.channel_id == self.channel.channel_id, RecordingWindow.status != "completed"))).scalar_one()

    async def _retention(self):
        cutoff = time.time() - self.channel.policy.retain_days * 86400
        for epoch in list(self.readers):
            if epoch == self.capture_epoch or not (epoch / "ended.json").exists() or epoch.stat().st_mtime >= cutoff:
                continue
            metadata = load_epoch(epoch / "epoch.json")
            async with AsyncSessionLocal() as db:
                windows = (await db.execute(select(RecordingWindow).where(RecordingWindow.channel_id == self.channel.channel_id,
                    RecordingWindow.session_id == metadata["session_id"], RecordingWindow.epoch == metadata["epoch"]))).scalars().all()
            known = self.segments.get(epoch, {})
            # Never remove partial/unregistered/pending/blocked originals, nor a
            # local archive whose offsite copy has not been acknowledged.
            originals = {path.resolve() for path in (epoch / "segments").glob("chunk_*.mkv")}
            if not known or originals != {segment.path.resolve() for segment in known.values()} or len(windows) != len(known) or any(w.status != "completed" or (w.details.get("policy", {}).get("archive") and not w.details.get("archived")) for w in windows):
                continue
            await self.pipeline._live(self.token)
            await asyncio.to_thread(shutil.rmtree, epoch)
            self.readers.pop(epoch, None)
            self.segments.pop(epoch, None)
            self.loaded_epochs.discard(epoch)
            self.registered = {key for key in self.registered if key[0] != epoch}

    async def _background_work(self):
        while True:
            await self._recover()
            for window in await store_call("list_pending", self.token, limit=10):
                await self.pipeline.step(self.channel, self.token, window)
            await self._retention()
            await asyncio.sleep(2)

    async def run(self):
        heartbeat = asyncio.create_task(self._heartbeat(asyncio.current_task()))
        work = asyncio.create_task(self._background_work())
        try:
            while True:
                if work.done():
                    await work  # Surface failed recovery instead of silently hanging.
                # Slow archives and API requests run in a separate tracked task.
                # This loop continues observing disk space and child liveness.
                if self.capture is not None:
                    known = self.segments.setdefault(self.capture_epoch, {})
                    closed = await self.capture.poll()
                    for segment in closed:
                        known[segment.sequence] = segment
                    if closed:
                        self.failures = 0
                free = shutil.disk_usage(self.settings.root).free
                backlog = await self._backlog()
                available = free >= self.settings.min_free_bytes and backlog < self.settings.max_backlog
                if self.capture and (not self.capture.running or self.capture.stalled or not available):
                    await self._stop_capture()
                    self.failures += 1
                    self.next_probe = time.monotonic() + retry_delay(self.failures - 1)
                if not available:
                    await store_call("report_error", self.token, "Capture paused: disk reserve or pending-work limit reached; existing media retained")
                elif self.capture is None and time.monotonic() >= self.next_probe:
                    result = await probe_channel(self.channel.url)
                    if result.state == ProbeState.LIVE:
                        session = await store_call("create_or_resume_session", self.token)
                        epoch = self.settings.root / self.channel.channel_id / session.id / str(uuid4())
                        atomic_json(epoch / "epoch.json", {"session_id": session.id, "epoch": epoch.name,
                            "policy": self.channel.policy.model_dump(), "fence": self.token.fence})
                        capture = CaptureProcess(epoch / "segments", self.channel.url, self.channel.quality,
                            segment_seconds=self.channel.policy.segment_seconds)
                        self.capture, self.capture_epoch = capture, epoch
                        self.readers[epoch] = capture
                        await capture.start()
                        self.offline_count = 0
                        await store_call("report_error", self.token, None)
                    elif result.state == ProbeState.OFFLINE:
                        self.offline_count += 1
                        self.next_probe = time.monotonic() + 60
                        if self.offline_count >= 2:
                            # A resumed session only exists after actual live
                            # detection. Offline probes never create dummy ones.
                            from ..models import RecordingSession
                            async with AsyncSessionLocal() as db:
                                active = (await db.execute(select(RecordingSession.id).where(RecordingSession.channel_id == self.channel.channel_id,
                                    RecordingSession.status.in_(["recording", "interrupted"])))).scalar_one_or_none()
                            if active:
                                await store_call("finish_session", self.token, active, "completed")
                    else:
                        self.failures += 1
                        self.next_probe = time.monotonic() + retry_delay(self.failures - 1)
                        message = ("YouTube rejected this connection. Connect your Mac in Home connection; existing media is retained."
                                   if result.detail == 'youtube_access_blocked' else "Stream availability is unknown; retrying without deleting media")
                        await store_call("report_error", self.token, message)
                await asyncio.sleep(5)
        finally:
            heartbeat.cancel()
            work.cancel()
            await asyncio.gather(heartbeat, work, return_exceptions=True)
            try:
                await self._stop_capture()
            finally:
                await store_call("release", self.token)


async def run(settings: RuntimeSettings):
    settings.root.mkdir(parents=True, exist_ok=True, mode=0o700)
    await init_db()
    config = get_config()
    holder = f"recorder:{uuid4()}"
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    running = {}
    async with NativeClient(os.getenv("RECORDING_API_URL", "http://backend:8000"), config.backend_auth_secret) as native:
        pipeline = AutomationPipeline(settings.root, native, archive_remote=os.getenv("RECORDING_ARCHIVE_REMOTE", ""))
        try:
            while not stop.is_set():
                from ..runtime_settings import load_runtime_settings_cache
                async with AsyncSessionLocal() as db:
                    await load_runtime_settings_cache(db)
                channels = {channel.channel_id: channel for channel in await asyncio.wait_for(store_call("list_enabled_channels"), timeout=30)}
                for identity, (runner, task) in list(running.items()):
                    if identity not in channels:
                        task.cancel()
                    else:
                        runner.channel = channels[identity]
                    if task.done() or identity not in channels:
                        result = await asyncio.gather(task, return_exceptions=True)
                        if result and isinstance(result[0], Exception):
                            logger.error("Channel runtime stopped (%s)", type(result[0]).__name__)
                        running.pop(identity)
                for channel in channels.values():
                    if channel.channel_id in running or len(running) >= settings.max_channels:
                        continue
                    token = await store_call("acquire", channel.channel_id, holder)
                    if token:
                        runner = ChannelRunner(channel, token, settings, pipeline)
                        running[channel.channel_id] = (runner, asyncio.create_task(runner.run()))
                (settings.root / ".supervisor-heartbeat").touch()
                try:
                    await asyncio.wait_for(stop.wait(), timeout=15)
                except TimeoutError:
                    pass
        finally:
            for _, task in running.values():
                task.cancel()
            await asyncio.gather(*(task for _, task in running.values()), return_exceptions=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--healthcheck", action="store_true")
    args = parser.parse_args()
    settings = RuntimeSettings.from_env()
    if args.healthcheck:
        raise SystemExit(0 if healthy(settings.root) else 1)
    os.environ["SUPOCLIP_SERVICE"] = "recorder"
    configure_logging()
    asyncio.run(run(settings))


if __name__ == "__main__":
    main()
