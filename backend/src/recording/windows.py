"""Prepare durable stream-copy MP4 windows without discarding source segments."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import tempfile

from .capture import ClosedSegment, _durable_digest, _read_json_command, _terminate

_VERSION = 1
_MAX_MANIFEST_BYTES = 65536


@dataclass(frozen=True)
class PreparedWindow:
    path: Path
    sha256: str
    size_bytes: int
    overlap_seconds: float
    start_seconds: float
    end_seconds: float
    segments: list[dict]


@dataclass(frozen=True)
class _Media:
    duration: float
    signature: tuple


async def _probe(path: Path) -> _Media:
    code, payload = await _read_json_command(
        ["ffprobe", "-v", "error", "-show_entries",
         "format=duration:stream=codec_type,codec_name,profile,width,height,pix_fmt,sample_rate,channels,channel_layout,time_base",
         "-of", "json", str(path)], timeout=30,
    )
    try:
        duration = float(payload["format"]["duration"])
        streams = payload["streams"]
        if code != 0 or not math.isfinite(duration) or duration <= 0:
            raise ValueError
        if not any(stream.get("codec_type") == "video" for stream in streams):
            raise ValueError
        fields = ("codec_type", "codec_name", "profile", "width", "height", "pix_fmt", "sample_rate", "channels", "channel_layout", "time_base")
        signature = tuple(sorted(tuple(str(stream.get(field, "")) for field in fields) for stream in streams if stream.get("codec_type") in {"video", "audio"}))
        return _Media(duration, signature)
    except (KeyError, TypeError, AttributeError, ValueError):
        raise ValueError("Window media is not a valid finite-duration video") from None


async def _run_ffmpeg(arguments: list[str]) -> None:
    process = await asyncio.create_subprocess_exec(
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", *arguments,
        stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL, start_new_session=True,
    )
    try:
        code = await asyncio.wait_for(process.wait(), timeout=180)
        if code != 0:
            raise ValueError("FFmpeg could not prepare a stream-copy MP4 window")
    finally:
        await asyncio.shield(_terminate(process))


def _identity(segment: ClosedSegment) -> dict:
    if not all(math.isfinite(value) for value in (segment.start_seconds, segment.end_seconds)):
        raise ValueError("Segment timestamps must be finite")
    if segment.start_seconds < 0 or segment.end_seconds <= segment.start_seconds:
        raise ValueError("Invalid segment time range")
    return {
        "path": str(segment.path.resolve()), "sequence": segment.sequence,
        "sha256": segment.sha256, "size_bytes": segment.size_bytes,
        "start_seconds": segment.start_seconds, "end_seconds": segment.end_seconds,
    }


async def _verify_original(segment: ClosedSegment) -> None:
    digest, size = await asyncio.to_thread(_durable_digest, segment.path)
    if digest != segment.sha256 or size != segment.size_bytes:
        raise ValueError("Original segment checksum differs from its durable manifest")


def _load_manifest(path: Path) -> dict | None:
    if path.is_symlink():
        return None
    try:
        with path.open("rb") as stream:
            content = stream.read(_MAX_MANIFEST_BYTES + 1)
        if len(content) > _MAX_MANIFEST_BYTES:
            return None
        value = json.loads(content)
        return value if isinstance(value, dict) else None
    except (OSError, ValueError):
        return None


async def _cached(output: Path, manifest: Path, request: str) -> PreparedWindow | None:
    saved = await asyncio.to_thread(_load_manifest, manifest)
    if not saved or saved.get("version") != _VERSION or saved.get("request") != request or output.is_symlink():
        return None
    try:
        digest, size = await asyncio.to_thread(_durable_digest, output)
        if digest != saved["sha256"] or size != saved["size_bytes"]:
            return None
        await _probe(output)
        overlap, start, end = (float(saved[key]) for key in ("overlap_seconds", "start_seconds", "end_seconds"))
        if not all(math.isfinite(value) for value in (overlap, start, end)) or overlap < 0 or end <= start:
            return None
        segments = saved["segments"]
        if not isinstance(segments, list) or not 1 <= len(segments) <= 2 or not all(isinstance(segment, dict) for segment in segments):
            return None
        return PreparedWindow(output, digest, size, overlap, start, end, segments)
    except (OSError, ValueError, TypeError, KeyError, asyncio.TimeoutError):
        return None


def _concat_file(paths: list[Path], destination: Path) -> None:
    lines = []
    for path in paths:
        value = str(path.resolve())
        if not value.isprintable():
            raise ValueError("Media paths must contain printable characters")
        lines.append("file '" + value.replace("'", "'\\''") + "'\n")
    destination.write_text("".join(lines), encoding="utf-8")


def _segment_map(segment: ClosedSegment, window_offset: float, duration: float, source_start: float) -> dict:
    return {
        "path": str(segment.path.resolve()), "sha256": segment.sha256,
        "size_bytes": segment.size_bytes, "sequence": segment.sequence,
        "source_start_seconds": source_start, "source_end_seconds": segment.end_seconds,
        "window_start_seconds": window_offset, "window_end_seconds": window_offset + duration,
    }


def _commit_window(temporary: Path, output: Path, sidecar: Path, metadata: dict) -> None:
    manifest = temporary.with_suffix(".json")
    with manifest.open("w", encoding="utf-8") as stream:
        json.dump(metadata, stream, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        stream.flush()
        os.fsync(stream.fileno())
    # A crash between these replacements leaves a mismatched checksum or absent
    # manifest; the next attempt rebuilds instead of trusting a partial artifact.
    os.replace(temporary, output)
    directory = os.open(output.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
        os.replace(manifest, sidecar)
        os.fsync(directory)
    finally:
        os.close(directory)


async def prepare_window(
    current: ClosedSegment,
    previous: ClosedSegment | None,
    overlap_seconds: int,
    output: Path,
) -> PreparedWindow:
    """Remux one segment with a measured preceding tail when it is compatible.

    Stream-copy cuts follow existing keyframes. ``overlap_seconds`` in the result
    is the *measured* tail duration, not a promise of an exact requested cut.
    Segment maps retain actual original ranges; epochs/gaps are never joined.
    """
    if isinstance(overlap_seconds, bool) or not isinstance(overlap_seconds, int) or overlap_seconds < 0:
        raise ValueError("Overlap duration must be a nonnegative integer")
    destination = Path(output)
    if destination.suffix.lower() != ".mp4" or destination.is_symlink():
        raise ValueError("Window output must be a regular MP4 destination")
    destination = destination.parent.resolve() / destination.name
    if destination == current.path.resolve() or (previous and destination == previous.path.resolve()):
        raise ValueError("A window must not overwrite original media")
    identity = {
        "version": _VERSION, "current": _identity(current),
        "previous": _identity(previous) if previous else None,
        "requested_overlap_seconds": overlap_seconds,
    }
    request = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    sidecar = destination.with_suffix(destination.suffix + ".json")
    cached = await _cached(destination, sidecar, request)
    if cached is not None:
        return cached

    await _verify_original(current)
    media = await _probe(current.path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    workspace = Path(tempfile.mkdtemp(prefix=".recording-window-", dir=destination.parent))
    try:
        inputs = [current.path]
        actual_overlap = 0.0
        segments = []
        if (
            previous is not None and overlap_seconds > 0
            and previous.path.resolve().parent == current.path.resolve().parent
            and previous.sequence < current.sequence
            and abs(previous.end_seconds - current.start_seconds) <= 2
        ):
            await _verify_original(previous)
            prior_media = await _probe(previous.path)
            if prior_media.signature == media.signature:
                tail = workspace / "tail.mkv"
                seek = max(0, prior_media.duration - overlap_seconds)
                await _run_ffmpeg([
                    "-ss", str(seek), "-i", str(previous.path), "-map", "0:v:0", "-map", "0:a:0?",
                    "-c", "copy", "-avoid_negative_ts", "make_zero", str(tail),
                ])
                actual_overlap = (await _probe(tail)).duration
                if actual_overlap > prior_media.duration + 2:
                    raise ValueError("Measured overlap exceeds the original segment")
                inputs.insert(0, tail)
                previous_map = _segment_map(previous, 0, actual_overlap, max(previous.start_seconds, previous.end_seconds - actual_overlap))
                # AAC priming/container padding can extend the measured file a
                # few milliseconds before the source interval. Preserve playback
                # offset while keeping original source ranges within the epoch.
                previous_map["leading_padding_seconds"] = max(0, actual_overlap - (previous.end_seconds - previous.start_seconds))
                segments.append(previous_map)
        segments.append(_segment_map(current, actual_overlap, current.end_seconds - current.start_seconds, current.start_seconds))
        temporary = workspace / "window.mp4"
        if len(inputs) == 2:
            listing = workspace / "inputs.ffconcat"
            _concat_file(inputs, listing)
            source_args = ["-f", "concat", "-safe", "0", "-i", str(listing)]
        else:
            source_args = ["-i", str(current.path)]
        await _run_ffmpeg([
            *source_args, "-map", "0:v:0", "-map", "0:a:0?", "-c", "copy",
            "-avoid_negative_ts", "make_zero", "-movflags", "+faststart", str(temporary),
        ])
        prepared_media = await _probe(temporary)
        if abs(prepared_media.duration - (media.duration + actual_overlap)) > 2:
            raise ValueError("Prepared window duration does not match its segment map")
        digest, size = await asyncio.to_thread(_durable_digest, temporary)
        result = PreparedWindow(
            destination, digest, size, actual_overlap,
            max(0, current.start_seconds - actual_overlap), current.end_seconds, segments,
        )
        metadata = {
            "version": _VERSION, "request": request, "sha256": digest, "size_bytes": size,
            "overlap_seconds": result.overlap_seconds, "start_seconds": result.start_seconds,
            "end_seconds": result.end_seconds, "segments": segments,
        }
        await asyncio.to_thread(_commit_window, temporary, destination, sidecar, metadata)
        return result
    finally:
        await asyncio.to_thread(shutil.rmtree, workspace, True)
