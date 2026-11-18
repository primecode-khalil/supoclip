"""Supervise one capture attempt and recover finalized segments from its manifest.

The caller owns durable session/lease state. Every attempt needs a new directory;
an old directory can be opened with ``poll()`` to replay its closed files after a
restart. FFmpeg writes a CSV entry only after closing the segment's trailer.
Unlisted fragments are retained for inspection, never submitted or deleted here.
"""
from __future__ import annotations

import asyncio
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import sys
import time
from dataclasses import dataclass
from enum import Enum
from urllib.parse import urlsplit

from .schemas import ChannelCreate, quality_name

_MAX_JSON_BYTES = 1024 * 1024
_MAX_MANIFEST_BYTES = 16 * 1024 * 1024
_SEGMENT_NAME = re.compile(r"chunk_([0-9]{6,10})\.mkv\Z")
_EXPLICIT_OFFLINE = re.compile(
    r"\b(?:the channel is offline|channel is currently offline|"
    r"stream is offline|is not currently live|is not live right now)\b",
    re.IGNORECASE,
)


class ProbeState(str, Enum):
    LIVE = "live"
    OFFLINE = "offline"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ProbeResult:
    state: ProbeState
    detail: str = ""


@dataclass(frozen=True)
class ClosedSegment:
    path: Path
    sequence: int
    start_seconds: float
    end_seconds: float
    sha256: str
    size_bytes: int


def capture_environment() -> dict[str, str]:
    """Internet-facing media/browser children have no server credentials."""
    allowed = {"PATH", "HOME", "TMPDIR", "TMP", "TEMP", "LANG", "LC_ALL", "DISPLAY", "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE"}
    return {key: value for key, value in os.environ.items() if key in allowed}


def streamlink_command() -> list[str]:
    command = ["streamlink", "--no-config", "--loglevel", "none", "--webbrowser-headless", "yes"]
    browser = os.getenv("RECORDING_BROWSER_EXECUTABLE")
    if browser:
        if not Path(browser).is_absolute():
            raise ValueError("Recording browser must be a server-configured absolute executable path")
        command += ["--webbrowser-executable", browser]
    return command


def youtube_proxy() -> str:
    from ..config import get_config
    from ..youtube_proxy import render_proxy_url
    value = get_config().youtube_proxy_url
    return render_proxy_url(value, 'recording') if value else ''


def youtube_command(url: str, quality: str) -> list[str]:
    match = re.search(r'(\d+)p', quality)
    height = min(2160, max(144, int(match[1]))) if match else 1080
    command = [sys.executable, '-m', 'yt_dlp', '--ignore-config', '--no-playlist',
               '--quiet', '--no-warnings', '--no-progress', '--no-cache-dir',
               '--socket-timeout', '20', '--retries', '1', '--fragment-retries', '1',
               # Separate live playlists can start on different fragments. Keep
               # their common broadcast clock when yt-dlp merges them to stdout.
               '--downloader-args', 'ffmpeg:-copyts',
               '-f', f'bv[height<={height}]+ba/b[height<={height}]']
    proxy = youtube_proxy()
    if proxy:
        command += ['--proxy', proxy]
    return command + [url, '-o', '-']


def _live_url(url: str) -> str:
    """Allow only the same owned platform handles accepted by the registry."""
    try:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.query or parsed.fragment:
            raise ValueError
        if parsed.username or parsed.password or parsed.port:
            raise ValueError
        platform = {
            "www.twitch.tv": "twitch", "kick.com": "kick",
            "www.youtube.com": "youtube",
        }.get(parsed.netloc)
        if platform is None:
            raise ValueError
        path = parsed.path
        if platform == "youtube" and path.endswith("/live"):
            path = path[:-5]
        if not path.startswith("/") or "/" in path[1:]:
            raise ValueError
        channel = ChannelCreate(platform=platform, handle=path[1:], name="Capture")
        expected = channel.url
        if url not in {expected, expected + "/live"}:
            raise ValueError
        if platform != "youtube" and url != expected:
            raise ValueError
        return expected + "/live" if platform == "youtube" else expected
    except (TypeError, ValueError):
        raise ValueError("Capture requires a canonical Twitch, Kick or YouTube channel URL") from None


def _positive_interval(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a finite positive number")
    return float(value)


def _send_signal(process: asyncio.subprocess.Process, sig: signal.Signals) -> None:
    if process.returncode is None:
        try:
            # Only subprocesses spawned with start_new_session=True reach here.
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            pass


async def _terminate(
    process: asyncio.subprocess.Process | None,
    first_signal: signal.Signals = signal.SIGTERM,
    grace: float = 5,
) -> None:
    if process is None or process.returncode is not None:
        return
    _send_signal(process, first_signal)
    try:
        await asyncio.wait_for(process.wait(), timeout=grace)
    except asyncio.TimeoutError:
        _send_signal(process, signal.SIGKILL)
        await asyncio.wait_for(process.wait(), timeout=5)


async def _read_json_command(argv: list[str], timeout: float) -> tuple[int, object]:
    """Bound output and runtime; never expose stream URLs or child diagnostics."""
    process = await asyncio.create_subprocess_exec(
        *argv, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL, start_new_session=True, env=capture_environment(),
    )

    async def read_result():
        output = bytearray()
        while chunk := await process.stdout.read(65536):
            output.extend(chunk)
            if len(output) > _MAX_JSON_BYTES:
                raise ValueError("Subprocess JSON output exceeded its limit")
        code = await process.wait()
        return code, json.loads(output)

    try:
        return await asyncio.wait_for(read_result(), timeout=timeout)
    finally:
        # Also reap on timeout, malformed/oversized output, and cancellation.
        await asyncio.shield(_terminate(process))


async def probe_channel(url: str, timeout: float = 30) -> ProbeResult:
    """A request failure is UNKNOWN, never evidence that a channel went offline."""
    source_url = _live_url(url)
    _positive_interval(timeout, "Probe timeout")
    try:
        command = ([sys.executable, str(Path(__file__).with_name('youtube_probe.py')), source_url, youtube_proxy()]
                   if urlsplit(source_url).hostname == 'www.youtube.com' else [*streamlink_command(), '--json', source_url])
        code, payload = await _read_json_command(
            command,
            timeout,
        )
    except (OSError, ValueError, asyncio.TimeoutError):
        return ProbeResult(ProbeState.UNKNOWN, "probe_unavailable")
    if not isinstance(payload, dict):
        return ProbeResult(ProbeState.UNKNOWN, "probe_invalid_response")
    streams = payload.get("streams")
    if code == 0 and isinstance(streams, dict) and streams:
        return ProbeResult(ProbeState.LIVE)
    error = payload.get("error")
    if isinstance(error, str) and _EXPLICIT_OFFLINE.search(error):
        return ProbeResult(ProbeState.OFFLINE)
    return ProbeResult(ProbeState.UNKNOWN, payload.get('detail', 'probe_inconclusive'))


def _durable_digest(path: Path) -> tuple[str, int]:
    """Hash a stable non-symlink file and flush data plus its directory entry."""
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(descriptor)
        digest = hashlib.sha256()
        with os.fdopen(os.dup(descriptor), "rb") as media:
            while block := media.read(1024 * 1024):
                digest.update(block)
        os.fsync(descriptor)
        after = os.fstat(descriptor)
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError("Segment changed while being verified")
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        return digest.hexdigest(), after.st_size
    finally:
        os.close(descriptor)


class CaptureProcess:
    """One owned process pair; no process-local state is treated as durable."""

    def __init__(
        self,
        directory: Path,
        url: str,
        quality: str = "best",
        segment_seconds: int = 600,
        stall_seconds: float = 120,
    ):
        self.directory = Path(directory).resolve()
        self.url = _live_url(url)
        self.quality = quality_name(quality)
        self.segment_seconds = _positive_interval(segment_seconds, "Segment duration")
        self.stall_seconds = _positive_interval(stall_seconds, "Stall timeout")
        self._streamlink: asyncio.subprocess.Process | None = None
        self._ffmpeg: asyncio.subprocess.Process | None = None
        self._emitted: set[int] = set()
        self._last_progress = time.monotonic()
        self._last_size = 0
        self._stop_task: asyncio.Task | None = None

    @property
    def running(self) -> bool:
        return bool(
            self._streamlink and self._ffmpeg
            and self._streamlink.returncode is None and self._ffmpeg.returncode is None
        )

    @property
    def stalled(self) -> bool:
        return self.running and time.monotonic() - self._last_progress >= self.stall_seconds

    async def start(self) -> None:
        if self._streamlink is not None or self._ffmpeg is not None:
            raise RuntimeError("A capture attempt cannot be started twice")
        if self._stop_task is not None:
            if not self._stop_task.done():
                raise RuntimeError("Capture is still stopping")
            self._stop_task = None
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if any(self.directory.iterdir()):
            raise ValueError("A new capture attempt requires an empty directory")
        youtube = urlsplit(self.url).hostname == 'www.youtube.com'
        # Preserve video packets. Pad any initial audio gap on the same clock
        # so transcription timestamps still use the video's zero origin.
        codecs = (['-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k',
                   '-af', 'aresample=async=1:first_pts=0', '-shortest'] if youtube else ['-c', 'copy'])
        read_descriptor, write_descriptor = os.pipe()
        try:
            # Parent copies close before cleanup runs, including partial-start
            # failures. Otherwise FFmpeg waits for EOF from our own write end.
            with os.fdopen(read_descriptor, "rb") as input_pipe, os.fdopen(write_descriptor, "wb") as output_pipe:
                self._ffmpeg = await asyncio.create_subprocess_exec(
                    "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
                    "-fflags", "+genpts", "-i", "pipe:0", "-map", "0:v:0",
                    "-map", "0:a:0?", *codecs, "-f", "segment",
                    "-segment_format", "matroska", "-segment_time", str(self.segment_seconds),
                    "-segment_list", "segments.csv", "-segment_list_type", "csv",
                    "-segment_list_size", "0", "-reset_timestamps", "1",
                    "-avoid_negative_ts", "make_zero", "chunk_%06d.mkv",
                    stdin=input_pipe, stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL, cwd=self.directory, start_new_session=True, env=capture_environment(),
                )
                self._streamlink = await asyncio.create_subprocess_exec(
                    *(youtube_command(self.url, self.quality) if youtube
                      else [*streamlink_command(), '--stdout', self.url, self.quality]),
                    stdin=asyncio.subprocess.DEVNULL, stdout=output_pipe,
                    stderr=asyncio.subprocess.DEVNULL, start_new_session=True, env=capture_environment(),
                )
            self._last_progress = time.monotonic()
        except BaseException:
            await asyncio.shield(self.stop())
            raise

    async def stop(self) -> None:
        if self._stop_task is None:
            self._stop_task = asyncio.create_task(self._stop_owned())
        try:
            await asyncio.shield(self._stop_task)
        except asyncio.CancelledError:
            # A supervisor cancellation must not leave a detached recorder
            # writing after its database lease has been relinquished.
            await asyncio.shield(self._stop_task)
            raise

    async def _stop_owned(self) -> None:
        # Stop the producer first: EOF normally lets FFmpeg write the last trailer
        # and CSV row without truncating the useful final fragment.
        await _terminate(self._streamlink)
        if self._ffmpeg is not None and self._ffmpeg.returncode is None:
            try:
                await asyncio.wait_for(self._ffmpeg.wait(), timeout=5)
            except asyncio.TimeoutError:
                await _terminate(self._ffmpeg, signal.SIGINT)

    def _rows(self) -> list[list[str]]:
        manifest = self.directory / "segments.csv"
        if not manifest.exists() or manifest.is_symlink():
            return []
        with manifest.open("rb") as stream:
            content = stream.read(_MAX_MANIFEST_BYTES + 1)
            # FFmpeg flushes its userspace CSV buffer after each closed segment;
            # make those timing identities durable before the caller commits a
            # ready row. File+directory fsync alone does not flush CSV contents.
            os.fsync(stream.fileno())
        if len(content) > _MAX_MANIFEST_BYTES:
            raise ValueError("Capture manifest exceeded its size limit")
        # An interrupted CSV write is not a finalized row. Never infer completion
        # from an unchanged file size or from being the second-newest segment.
        complete = content[:content.rfind(b"\n") + 1]
        rows = []
        for line in complete.splitlines():
            try:
                row = next(csv.reader([line.decode("utf-8")], strict=True))
            except (UnicodeDecodeError, csv.Error, StopIteration):
                continue
            if len(row) == 3:
                rows.append(row)
        return rows

    def _progress(self) -> None:
        # Observe bytes of the open segment as well as completed segments. A long
        # keyframe interval must not look stalled merely because no file closed.
        try:
            total = sum(path.stat().st_size for path in self.directory.glob("chunk_*.mkv") if not path.is_symlink())
        except OSError:
            return
        if total != self._last_size:
            self._last_size = total
            self._last_progress = time.monotonic()

    async def poll(self) -> list[ClosedSegment]:
        self._progress()
        segments = []
        for name, raw_start, raw_end in await asyncio.to_thread(self._rows):
            match = _SEGMENT_NAME.fullmatch(name)
            if match is None:
                continue
            sequence = int(match.group(1))
            if sequence in self._emitted or sequence > 2147483647:
                continue
            try:
                start, end = float(raw_start), float(raw_end)
                if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
                    continue
                path = self.directory / name
                if path.is_symlink() or not path.is_file() or path.resolve().parent != self.directory:
                    continue
                code, media = await _read_json_command(
                    ["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type",
                     "-of", "json", str(path)], timeout=30,
                )
                if code != 0 or not isinstance(media, dict):
                    continue
                duration = float(media.get("format", {}).get("duration", 0))
                if not math.isfinite(duration) or duration <= 0:
                    continue
                if abs(duration - (end - start)) > max(2, duration * 0.01):
                    continue
                if not any(stream.get("codec_type") == "video" for stream in media.get("streams", []) if isinstance(stream, dict)):
                    continue
                digest, size = await asyncio.to_thread(_durable_digest, path)
                if size <= 0:
                    continue
            except (OSError, ValueError, TypeError, asyncio.TimeoutError):
                continue
            self._emitted.add(sequence)
            segments.append(ClosedSegment(path.resolve(), sequence, start, end, digest, size))
        return segments
