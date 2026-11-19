"""Real stream-copy window assembly and immutable-manifest recovery."""
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest


def windows_module():
    from src.recording import windows
    return windows


@pytest.fixture
def segment_factory(tmp_path):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("ffmpeg and ffprobe required for rolling-window tests")
    from src.recording.capture import ClosedSegment

    def create(sequence, *, width=64, start=None, duration=3, codec="libx264", directory=None):
        path = (directory or tmp_path) / f"chunk_{sequence:06d}.mkv"
        path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([
            "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=blue:s={width}x64:r=10",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=16000",
            "-t", str(duration), "-c:v", codec, "-g", "10", "-bf", "0",
            "-c:a", "aac", str(path),
        ], check=True, timeout=20, capture_output=True)
        return ClosedSegment(
            path=path, sequence=sequence, start_seconds=sequence * duration if start is None else start,
            end_seconds=(sequence * duration if start is None else start) + duration,
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(), size_bytes=path.stat().st_size,
        )

    return create


async def test_current_segment_becomes_verified_mp4_with_manifest(segment_factory, tmp_path):
    windows = windows_module()
    current = segment_factory(0)
    output = tmp_path / "window.mp4"
    result = await windows.prepare_window(current, None, 60, output)
    assert result.path == output.resolve()
    assert result.overlap_seconds == 0
    assert result.start_seconds == current.start_seconds
    assert result.end_seconds == current.end_seconds
    assert result.size_bytes == output.stat().st_size
    assert result.sha256 == hashlib.sha256(output.read_bytes()).hexdigest()
    assert len(result.segments) == 1
    assert result.segments[0]["path"] == str(current.path)
    assert result.segments[0]["sha256"] == current.sha256
    manifest = json.loads(output.with_suffix(".mp4.json").read_text())
    assert manifest["sha256"] == result.sha256
    assert manifest["segments"] == result.segments
    assert current.path.exists()


async def test_precedes_current_with_measured_keyframe_aligned_tail(segment_factory, tmp_path):
    windows = windows_module()
    previous, current = segment_factory(0), segment_factory(1)
    result = await windows.prepare_window(current, previous, 1, tmp_path / "window.mp4")
    assert 0.8 <= result.overlap_seconds <= 2.1
    assert result.start_seconds == pytest.approx(current.start_seconds - result.overlap_seconds)
    assert result.end_seconds == current.end_seconds
    assert [segment["sequence"] for segment in result.segments] == [0, 1]
    assert result.segments[0]["window_start_seconds"] == 0
    assert result.segments[1]["window_start_seconds"] == result.overlap_seconds
    assert previous.path.exists() and current.path.exists()


async def test_early_short_window_keeps_padding_without_negative_source_time(segment_factory, tmp_path):
    windows = windows_module()
    previous, current = segment_factory(0, duration=1), segment_factory(1, duration=1)
    result = await windows.prepare_window(current, previous, 60, tmp_path / "window.mp4")
    assert result.overlap_seconds >= 1
    assert result.start_seconds == 0
    assert result.segments[0]["source_start_seconds"] == 0


@pytest.mark.parametrize("variant", ["gap", "different_resolution", "different_codec", "different_epoch"])
async def test_does_not_overlap_discontinuous_or_incompatible_segments(segment_factory, tmp_path, variant):
    windows = windows_module()
    previous = segment_factory(0)
    current = segment_factory(
        1, width=128 if variant == "different_resolution" else 64,
        start=8 if variant == "gap" else 3,
        codec="mpeg4" if variant == "different_codec" else "libx264",
        directory=tmp_path / "different-epoch" if variant == "different_epoch" else None,
    )
    result = await windows.prepare_window(current, previous, 1, tmp_path / "window.mp4")
    assert result.overlap_seconds == 0
    assert len(result.segments) == 1
    assert result.start_seconds == current.start_seconds


async def test_reuses_immutable_verified_window_without_rerendering(segment_factory, tmp_path, monkeypatch):
    windows = windows_module()
    current = segment_factory(0)
    output = tmp_path / "window.mp4"
    initial = await windows.prepare_window(current, None, 60, output)
    initial_mtime = output.stat().st_mtime_ns

    async def unexpected_render(*args, **kwargs):
        pytest.fail("A verified persisted window must not be rendered again")

    monkeypatch.setattr(windows, "_run_ffmpeg", unexpected_render)
    recovered = await windows.prepare_window(current, None, 60, output)
    assert recovered == initial
    assert output.stat().st_mtime_ns == initial_mtime


async def test_rebuilds_window_when_cached_output_is_corrupted(segment_factory, tmp_path):
    windows = windows_module()
    current = segment_factory(0)
    output = tmp_path / "window.mp4"
    await windows.prepare_window(current, None, 60, output)
    output.write_bytes(b"corrupted cache")
    recovered = await windows.prepare_window(current, None, 60, output)
    assert recovered.sha256 == hashlib.sha256(output.read_bytes()).hexdigest()
    assert recovered.size_bytes > len(b"corrupted cache")


async def test_recovers_output_without_manifest_after_interrupted_atomic_replace(segment_factory, tmp_path):
    windows = windows_module()
    current = segment_factory(0)
    output = tmp_path / "window.mp4"
    await windows.prepare_window(current, None, 60, output)
    output.with_suffix(".mp4.json").unlink()
    recovered = await windows.prepare_window(current, None, 60, output)
    assert recovered.sha256 == hashlib.sha256(output.read_bytes()).hexdigest()
    assert output.with_suffix(".mp4.json").exists()


async def test_checks_original_checksum_before_new_window_creation(segment_factory, tmp_path):
    windows = windows_module()
    current = segment_factory(0)
    current.path.write_bytes(b"unexpected replacement")
    output = tmp_path / "window.mp4"
    with pytest.raises(ValueError, match="checksum"):
        await windows.prepare_window(current, None, 60, output)
    assert not output.exists()


async def test_concat_paths_with_apostrophes_remain_local_files(segment_factory, tmp_path):
    windows = windows_module()
    source_dir = tmp_path / "operator's recordings"
    previous = segment_factory(0, directory=source_dir)
    current = segment_factory(1, directory=source_dir)
    result = await windows.prepare_window(current, previous, 1, tmp_path / "operator's window.mp4")
    assert result.path.exists() and result.overlap_seconds > 0


@pytest.mark.parametrize("overlap", [-1, float("nan"), float("inf"), "60", True])
async def test_rejects_invalid_overlap(segment_factory, tmp_path, overlap):
    windows = windows_module()
    current = segment_factory(0)
    with pytest.raises(ValueError):
        await windows.prepare_window(current, None, overlap, tmp_path / "window.mp4")


async def test_never_overwrites_original_media(segment_factory):
    windows = windows_module()
    current = segment_factory(0)
    with pytest.raises(ValueError):
        await windows.prepare_window(current, None, 0, current.path)
    assert hashlib.sha256(current.path.read_bytes()).hexdigest() == current.sha256
