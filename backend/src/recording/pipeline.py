"""Deterministic automation decisions and the authenticated native API client.

Stable request keys are persisted by the native task/post transactions, so a
timeout or recorder restart can replay them without creating another effect.
"""
from __future__ import annotations

import hashlib
import hmac
import math
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx


class PipelineBlocked(Exception):
    """Requires an operator/configuration change; never blindly resubmit."""


class PipelineRetry(Exception):
    """A transient failure with a safe, idempotent retry path."""


def contained_path(root: Path, relative: str) -> Path:
    candidate = Path(relative)
    if not relative or candidate.is_absolute() or ".." in candidate.parts or "\\" in relative or ":" in relative:
        raise PipelineBlocked("Invalid capture media path")
    root = root.resolve()
    result = (root / candidate).resolve()
    if not result.is_relative_to(root) or result == root:
        raise PipelineBlocked("Capture media path escapes the persistent volume")
    return result


def retry_delay(attempt: int) -> int:
    return min(3600, 15 * 2 ** min(8, max(0, attempt)))


def _seconds(value) -> float:
    try:
        parts = str(value).split(":")
        total = 0.0
        if len(parts) > 3:
            return float("nan")
        for part in parts:
            total = total * 60 + float(part)
        return total if total >= 0 and math.isfinite(total) else float("nan")
    except (TypeError, ValueError):
        return float("nan")


def overlaps_reserved(start: float, end: float, account_id: str, reservations: list[dict]) -> bool:
    return any(row.get("account_id") == account_id and
        max(0, min(end, row["end"]) - max(start, row["start"])) / min(end - start, row["end"] - row["start"]) >= 0.5
        for row in reservations if row.get("end", 0) > row.get("start", 0))


def choose_clips(clips: list[dict], *, overlap: float, min_score: float, limit: int) -> list[dict]:
    candidates = []
    for clip in clips:
        start, end = _seconds(clip.get("start_time")), _seconds(clip.get("end_time"))
        # Publishing requires an actual virality assessment; don't substitute
        # transcription confidence or invent a score for unscored candidates.
        score = clip.get("virality_score")
        if not isinstance(score, (int, float)) or isinstance(score, bool) or not math.isfinite(score):
            continue
        if not (0 <= start < end and end > overlap and min_score <= score <= 100):
            continue
        candidates.append((clip, start, end, score))
    selected = []
    ranges = []
    for clip, start, end, _ in sorted(candidates, key=lambda item: (-item[3], item[1], str(item[0].get("id")))):
        if any(max(0, min(end, b) - max(start, a)) / min(end - start, b - a) >= 0.5 for a, b in ranges):
            continue
        selected.append(clip)
        ranges.append((start, end))
        if len(selected) >= limit:
            break
    return selected


class NativeClient:
    def __init__(self, base_url: str, secret: str, *, transport=None):
        parsed = urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("RECORDING_API_URL must be a server-controlled HTTP(S) origin")
        if not secret:
            raise ValueError("BACKEND_AUTH_SECRET is required by the recording supervisor")
        self.secret = secret
        self.client = httpx.AsyncClient(base_url=base_url.rstrip("/"), transport=transport, timeout=300, follow_redirects=False)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self.client.aclose()

    async def request(self, user_id: str, method: str, path: str, *, key: str | None = None, **kwargs):
        timestamp = str(int(time.time()))
        signature = hmac.new(self.secret.encode(), f"{user_id}:{timestamp}".encode(), hashlib.sha256).hexdigest()
        headers = {"x-supoclip-user-id": user_id, "x-supoclip-ts": timestamp, "x-supoclip-signature": signature}
        if key:
            headers["Idempotency-Key"] = key
        try:
            response = await self.client.request(method, path, headers=headers, **kwargs)
        except httpx.HTTPError as exc:
            # Never log request headers, signed URLs, tokens or provider bodies.
            raise PipelineRetry(f"Native API transport failure ({type(exc).__name__})") from None
        if response.status_code in {408, 409, 425, 429} or response.status_code >= 500:
            raise PipelineRetry(f"Native API temporarily unavailable (HTTP {response.status_code})")
        if response.status_code >= 300:
            raise PipelineBlocked(f"Native API rejected automation (HTTP {response.status_code}); check account and provider settings")
        try:
            result = response.json()
        except ValueError:
            raise PipelineRetry("Native API returned an invalid response") from None
        if not isinstance(result, dict):
            raise PipelineRetry("Native API returned an invalid response")
        return result
