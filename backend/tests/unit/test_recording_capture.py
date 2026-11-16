"""Capture safety and finalized-media contracts; subprocess mocks only at OS edges."""
import asyncio
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
from unittest.mock import AsyncMock

import pytest


def capture_module():
    from src.recording import capture
    return capture


@pytest.fixture(scope="session")
def small_video(tmp_path_factory):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("ffmpeg and ffprobe are required for capture media validation")
    path = tmp_path_factory.mktemp("recording-source") / "source.mkv"
    subprocess.run([
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "color=c=blue:s=64x64:r=10",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=16000",
        "-t", "0.5", "-c:v", "mpeg4", "-c:a", "aac", str(path),
    ], check=True, timeout=20, capture_output=True)
    return path


def write_segment(directory, source, name="chunk_000000.mkv"):
    path = directory / name
    shutil.copyfile(source, path)
    return path


async def test_only_emits_complete_manifest_rows_and_durable_verified_files(tmp_path, small_video):
    capture = capture_module()
    path = write_segment(tmp_path, small_video)
    manifest = tmp_path / "segments.csv"
    manifest.write_text("chunk_000000.mkv,0.000000,0.500000")
    process = capture.CaptureProcess(tmp_path, "https://www.twitch.tv/demo")
    assert await process.poll() == []
    with manifest.open("a") as output:
        output.write("\n")
    segments = await process.poll()
    assert len(segments) == 1
    segment = segments[0]
    assert segment.path == path.resolve()
    assert segment.sequence == 0
    assert segment.start_seconds == 0
    assert segment.end_seconds == 0.5
    assert segment.size_bytes == path.stat().st_size
    assert segment.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert await process.poll() == []
    replacement = capture.CaptureProcess(tmp_path, "https://www.twitch.tv/demo")
    assert await replacement.poll() == segments


@pytest.mark.parametrize("row", [
    "../outside.mkv,0,1\n", "/tmp/outside.mkv,0,1\n", "sub/chunk_000000.mkv,0,1\n",
    "chunk_000000.mkv,nan,1\n", "chunk_000000.mkv,0,inf\n",
    "chunk_000000.mkv,-1,1\n", "chunk_000000.mkv,1,1\n",
    "chunk_000000.mkv,2,1\n", "chunk_000000.mkv,0,1,extra\n", "broken\n",
    '"chunk_000000.mkv,0,1\n', "chunk_000000.mp4,0,1\n",
])
async def test_rejects_unsafe_or_malformed_manifest_rows(tmp_path, row):
    capture = capture_module()
    (tmp_path / "segments.csv").write_text(row)
    process = capture.CaptureProcess(tmp_path, "https://kick.com/demo")
    assert await process.poll() == []


async def test_rejects_symlink_escape_and_does_not_accept_corrupt_media(tmp_path, small_video):
    capture = capture_module()
    directory = tmp_path / "capture"
    directory.mkdir()
    outside = write_segment(tmp_path, small_video)
    (directory / "chunk_000000.mkv").symlink_to(outside)
    (directory / "chunk_000001.mkv").write_bytes(b"not a video")
    (directory / "segments.csv").write_text("chunk_000000.mkv,0,1\nchunk_000001.mkv,1,2\n")
    process = capture.CaptureProcess(directory, "https://kick.com/demo")
    assert await process.poll() == []


async def test_closed_row_not_lost_when_file_appears_on_later_poll(tmp_path, small_video):
    capture = capture_module()
    (tmp_path / "segments.csv").write_text("chunk_000000.mkv,0,0.5\n")
    process = capture.CaptureProcess(tmp_path, "https://kick.com/demo")
    assert await process.poll() == []
    write_segment(tmp_path, small_video)
    assert len(await process.poll()) == 1


async def test_duplicate_manifest_rows_are_emitted_once(tmp_path, small_video):
    capture = capture_module()
    write_segment(tmp_path, small_video)
    (tmp_path / "segments.csv").write_text("chunk_000000.mkv,0,0.5\n" * 2)
    process = capture.CaptureProcess(tmp_path, "https://kick.com/demo")
    assert len(await process.poll()) == 1


async def test_manifest_duration_must_agree_with_verified_media(tmp_path, small_video):
    capture = capture_module()
    write_segment(tmp_path, small_video)
    (tmp_path / "segments.csv").write_text("chunk_000000.mkv,0,3600\n")
    process = capture.CaptureProcess(tmp_path, "https://kick.com/demo")
    assert await process.poll() == []


async def test_never_emits_segment_if_closed_manifest_cannot_be_flushed(tmp_path, small_video, monkeypatch):
    capture = capture_module()
    write_segment(tmp_path, small_video)
    manifest = tmp_path / "segments.csv"
    manifest.write_text("chunk_000000.mkv,0,0.5\n")
    manifest_inode = manifest.stat().st_ino
    real_fsync = os.fsync

    def fail_manifest_sync(descriptor):
        if os.fstat(descriptor).st_ino == manifest_inode:
            raise OSError("Durable manifest write failed")
        return real_fsync(descriptor)

    monkeypatch.setattr(capture.os, "fsync", fail_manifest_sync)
    process = capture.CaptureProcess(tmp_path, "https://kick.com/demo")
    with pytest.raises(OSError, match="manifest write failed"):
        await process.poll()


@pytest.mark.parametrize("url", ["https://example.org/demo", "http://www.twitch.tv/demo", "https://www.twitch.tv/demo?token=secret", "https://www.twitch.tv/demo/other", "https://user:pass@kick.com/demo", "--config"])
def test_rejects_noncanonical_source_urls(url, tmp_path):
    capture = capture_module()
    with pytest.raises(ValueError):
        capture.CaptureProcess(tmp_path, url)


@pytest.mark.parametrize("quality", ["--output", "best;touch x", "best\n", "best,,worst"])
def test_rejects_unsafe_quality(quality, tmp_path):
    capture = capture_module()
    with pytest.raises(ValueError):
        capture.CaptureProcess(tmp_path, "https://kick.com/demo", quality=quality)


@pytest.mark.parametrize("seconds", [0, -1, float("nan"), float("inf")])
def test_rejects_invalid_capture_intervals(tmp_path, seconds):
    capture = capture_module()
    with pytest.raises(ValueError):
        capture.CaptureProcess(tmp_path, "https://kick.com/demo", segment_seconds=seconds)


class FakeProcess:
    def __init__(self, stdout=b"", returncode=0):
        self.stdout = asyncio.StreamReader()
        self.stdout.feed_data(stdout)
        self.stdout.feed_eof()
        self.stderr = None
        self.returncode = returncode
        self.pid = 123456789
        self.wait = AsyncMock(return_value=returncode)


async def test_probe_live_uses_json_no_config_and_youtube_live_url(monkeypatch):
    capture = capture_module()
    launcher = AsyncMock(return_value=FakeProcess(json.dumps({"streams": {"best": {"url": "SECRET"}}}).encode()))
    monkeypatch.setattr(capture.asyncio, "create_subprocess_exec", launcher)
    result = await capture.probe_channel("https://www.youtube.com/@demo")
    assert result.state is capture.ProbeState.LIVE
    args, kwargs = launcher.call_args
    assert args[0] == "streamlink"
    assert "--json" in args and "--no-config" in args
    assert args[-1] == "https://www.youtube.com/@demo/live"
    assert kwargs["start_new_session"] is True
    assert "SECRET" not in result.detail


@pytest.mark.parametrize(("payload", "returncode", "expected"), [
    ({"error": "The channel is offline"}, 1, "offline"),
    ({"error": "No streams found on this URL: https://kick.com/demo"}, 1, "unknown"),
    ({"error": "403 Forbidden token=SECRET"}, 1, "unknown"),
    ({"streams": {}}, 0, "unknown"),
    ({"streams": {"best": {}}}, 1, "unknown"),
    ({"streams": []}, 0, "unknown"),
])
async def test_probe_distinguishes_explicit_offline_from_unknown_failures(monkeypatch, payload, returncode, expected):
    capture = capture_module()
    monkeypatch.setattr(capture.asyncio, "create_subprocess_exec", AsyncMock(return_value=FakeProcess(json.dumps(payload).encode(), returncode)))
    result = await capture.probe_channel("https://kick.com/demo")
    assert result.state.value == expected
    assert "SECRET" not in result.detail


async def test_probe_missing_binary_is_unknown(monkeypatch):
    capture = capture_module()
    monkeypatch.setattr(capture.asyncio, "create_subprocess_exec", AsyncMock(side_effect=FileNotFoundError("secret path")))
    result = await capture.probe_channel("https://kick.com/demo")
    assert result.state is capture.ProbeState.UNKNOWN
    assert "secret" not in result.detail


async def test_poll_drains_final_segment_after_child_exit(tmp_path, small_video):
    capture = capture_module()
    write_segment(tmp_path, small_video)
    (tmp_path / "segments.csv").write_text("chunk_000000.mkv,0,0.5\n")
    process = capture.CaptureProcess(tmp_path, "https://kick.com/demo")
    process._ffmpeg = FakeProcess(returncode=1)
    process._streamlink = FakeProcess(returncode=0)
    assert not process.running
    assert len(await process.poll()) == 1


async def test_start_failure_reaps_already_started_ffmpeg(monkeypatch, tmp_path):
    capture = capture_module()
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg required")
    real_launcher = asyncio.create_subprocess_exec

    async def launch(*args, **kwargs):
        if args[0] == "streamlink":
            raise FileNotFoundError("missing streamlink")
        return await real_launcher(*args, **kwargs)

    launcher = AsyncMock(side_effect=launch)
    monkeypatch.setattr(capture.asyncio, "create_subprocess_exec", launcher)
    process = capture.CaptureProcess(tmp_path / "new", "https://kick.com/demo")
    with pytest.raises(FileNotFoundError):
        # Closing the parent's pipe before cleanup avoids waiting for an EOF
        # that cannot arrive while its own write descriptor is still open.
        await asyncio.wait_for(process.start(), timeout=2)
    assert process._ffmpeg.returncode is not None
    assert not process.running


async def test_start_never_overwrites_an_existing_capture_attempt(tmp_path, small_video):
    capture = capture_module()
    segment = write_segment(tmp_path, small_video)
    process = capture.CaptureProcess(tmp_path, "https://kick.com/demo")
    with pytest.raises(ValueError, match="empty directory"):
        await process.start()
    assert segment.read_bytes() == small_video.read_bytes()


async def test_stop_before_start_does_not_disable_later_process_cleanup(tmp_path, monkeypatch):
    capture = capture_module()
    process = capture.CaptureProcess(tmp_path, "https://kick.com/demo")
    await process.stop()
    producer, consumer = FakeProcess(returncode=None), FakeProcess(returncode=None)
    monkeypatch.setattr(capture.asyncio, "create_subprocess_exec", AsyncMock(side_effect=[consumer, producer]))

    def terminate(pid, sig):
        producer.returncode = consumer.returncode = 0

    monkeypatch.setattr(capture.os, "killpg", terminate)
    await process.start()
    assert process.running
    await process.stop()
    assert not process.running


async def test_probe_timeout_kills_only_owned_process_group(monkeypatch):
    capture = capture_module()
    process = FakeProcess(returncode=None)
    process.stdout = asyncio.StreamReader()  # never produces EOF
    signals = []

    def terminate(pid, sig):
        signals.append((pid, sig))
        process.returncode = 0

    monkeypatch.setattr(capture.asyncio, "create_subprocess_exec", AsyncMock(return_value=process))
    monkeypatch.setattr(capture.os, "killpg", terminate)
    result = await capture.probe_channel("https://kick.com/demo", timeout=0.01)
    assert result.state is capture.ProbeState.UNKNOWN
    assert signals == [(process.pid, signal.SIGTERM)]


async def test_probe_oversized_output_is_bounded_and_not_exposed(monkeypatch):
    capture = capture_module()
    process = FakeProcess(b"SECRET" * (1024 * 1024), returncode=None)

    def terminate(pid, sig):
        process.returncode = 0

    monkeypatch.setattr(capture.asyncio, "create_subprocess_exec", AsyncMock(return_value=process))
    monkeypatch.setattr(capture.os, "killpg", terminate)
    result = await capture.probe_channel("https://kick.com/demo")
    assert result.state is capture.ProbeState.UNKNOWN
    assert "SECRET" not in result.detail
    assert process.returncode == 0


def make_streamlink_stub(directory, source, *, keep_open=False):
    directory.mkdir()
    executable = directory / "streamlink"
    executable.write_text(
        f"#!{sys.executable}\n"
        "import pathlib, sys, time\n"
        f"sys.stdout.buffer.write(pathlib.Path({str(source)!r}).read_bytes())\n"
        "sys.stdout.buffer.flush()\n"
        f"pathlib.Path({str(directory / 'ready')!r}).touch()\n"
        + ("time.sleep(60)\n" if keep_open else "")
    )
    executable.chmod(0o700)
    return directory


def test_capture_children_do_not_inherit_server_credentials(monkeypatch):
    capture = capture_module()
    monkeypatch.setenv("BACKEND_AUTH_SECRET", "must-not-reach-browser-or-ffmpeg")
    monkeypatch.setenv("DATABASE_URL", "private-database-credentials")
    monkeypatch.setenv("PATH", "/usr/bin")
    environment = capture.capture_environment()
    assert environment["PATH"] == "/usr/bin"
    assert "BACKEND_AUTH_SECRET" not in environment and "DATABASE_URL" not in environment


def test_streamlink_can_solve_browser_challenges_on_a_headless_host(monkeypatch):
    capture = capture_module()
    monkeypatch.setenv("RECORDING_BROWSER_EXECUTABLE", "/usr/local/bin/supoclip-chromium")
    arguments = capture.streamlink_command()
    assert arguments[arguments.index("--webbrowser-headless") + 1] == "yes"
    assert arguments[arguments.index("--webbrowser-executable") + 1] == "/usr/local/bin/supoclip-chromium"


async def test_real_process_pair_emits_final_fragment_after_producer_exit(tmp_path, small_video, monkeypatch):
    capture = capture_module()
    executables = make_streamlink_stub(tmp_path / "bin", small_video)
    monkeypatch.setenv("PATH", f"{executables}{os.pathsep}{os.environ['PATH']}")
    process = capture.CaptureProcess(tmp_path / "capture", "https://kick.com/demo", segment_seconds=1)
    await process.start()
    try:
        await asyncio.wait_for(process._streamlink.wait(), 5)
        await asyncio.wait_for(process._ffmpeg.wait(), 5)
        assert process._ffmpeg.returncode == 0
        assert not process.running
        segments = await process.poll()
        assert len(segments) == 1
        assert 0 < segments[0].end_seconds < 1
    finally:
        await process.stop()


async def test_real_stop_closes_pipe_and_preserves_final_fragment(tmp_path, small_video, monkeypatch):
    capture = capture_module()
    executables = make_streamlink_stub(tmp_path / "bin", small_video, keep_open=True)
    monkeypatch.setenv("PATH", f"{executables}{os.pathsep}{os.environ['PATH']}")
    process = capture.CaptureProcess(tmp_path / "capture", "https://kick.com/demo", segment_seconds=1)
    await process.start()
    try:
        # Wait for the child to write into the pipe, without depending on FFmpeg's
        # probing buffer completing before producer EOF.
        for _ in range(100):
            if (executables / "ready").exists():
                break
            await asyncio.sleep(0.02)
        assert (executables / "ready").exists()
        assert process.running
        await process.stop()
        assert not process.running
        assert process._streamlink.returncode is not None
        assert process._ffmpeg.returncode == 0
        assert len(await process.poll()) == 1
    finally:
        await process.stop()


def test_stall_uses_byte_progress_not_only_closed_segment_count(tmp_path, monkeypatch):
    capture = capture_module()
    clock = [0.0]
    monkeypatch.setattr(capture.time, "monotonic", lambda: clock[0])
    process = capture.CaptureProcess(tmp_path, "https://kick.com/demo", stall_seconds=10)
    process._streamlink = FakeProcess(returncode=None)
    process._ffmpeg = FakeProcess(returncode=None)
    clock[0] = 11
    assert process.stalled
    (tmp_path / "chunk_000000.mkv").write_bytes(b"new open file bytes")
    process._progress()
    assert not process.stalled
    clock[0] = 22
    assert process.stalled


async def test_cancelled_stop_still_reaps_both_owned_children(monkeypatch, tmp_path):
    capture = capture_module()
    process = capture.CaptureProcess(tmp_path, "https://kick.com/demo")
    producer = FakeProcess(returncode=None)
    consumer = FakeProcess(returncode=None)
    process._streamlink, process._ffmpeg = producer, consumer
    producer_terminated = asyncio.Event()
    producer_exited = asyncio.Event()

    def terminate(pid, sig):
        assert pid == producer.pid
        producer_terminated.set()

    async def producer_wait():
        await producer_exited.wait()
        producer.returncode = 0
        consumer.returncode = 0  # EOF lets FFmpeg finish normally.
        return 0

    producer.wait = AsyncMock(side_effect=producer_wait)
    monkeypatch.setattr(capture.os, "killpg", terminate)
    stopping = asyncio.create_task(process.stop())
    await producer_terminated.wait()
    stopping.cancel()
    asyncio.get_running_loop().call_later(0.01, producer_exited.set)
    with pytest.raises(asyncio.CancelledError):
        await stopping
    assert producer.returncode == 0 and consumer.returncode == 0


async def test_real_muxer_closes_multiple_segments_with_actual_pts(tmp_path, monkeypatch):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("ffmpeg and ffprobe required")
    capture = capture_module()
    source = tmp_path / "input.ts"
    subprocess.run([
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "color=c=blue:s=64x64:r=10",
        "-t", "3.4", "-c:v", "mpeg2video", "-g", "10", "-bf", "0",
        "-f", "mpegts", str(source),
    ], check=True, timeout=20, capture_output=True)
    executables = make_streamlink_stub(tmp_path / "bin", source)
    monkeypatch.setenv("PATH", f"{executables}{os.pathsep}{os.environ['PATH']}")
    process = capture.CaptureProcess(tmp_path / "capture", "https://kick.com/demo", segment_seconds=1)
    await process.start()
    try:
        await asyncio.wait_for(process._streamlink.wait(), 5)
        await asyncio.wait_for(process._ffmpeg.wait(), 5)
        assert process._ffmpeg.returncode == 0
        segments = await process.poll()
        assert [segment.sequence for segment in segments] == [0, 1, 2, 3]
        assert segments[-1].end_seconds - segments[0].start_seconds == pytest.approx(3.4, abs=0.15)
        assert all(left.end_seconds == pytest.approx(right.start_seconds) for left, right in zip(segments, segments[1:]))
        assert await process.poll() == []
    finally:
        await process.stop()
