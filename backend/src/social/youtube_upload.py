"""YouTube resumable upload protocol; session URIs are private credentials."""
from __future__ import annotations

from dataclasses import dataclass
import os
import re
from urllib.parse import urlsplit

import requests

from .base import SocialProviderError

UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"


@dataclass(frozen=True)
class UploadProgress:
    confirmed_bytes: int
    video_id: str | None = None


class YouTubeUploadError(SocialProviderError):
    def __init__(self, message: str, reason_code: str, **flags):
        super().__init__(message, **flags)
        self.reason_code = reason_code


def validate_session_uri(uri: str) -> str:
    try:
        parsed = urlsplit(uri)
        valid = (parsed.scheme == "https" and parsed.hostname in {"www.googleapis.com", "youtube.googleapis.com"}
                 and parsed.port in (None, 443) and not parsed.username and not parsed.password
                 and not parsed.fragment and parsed.path.startswith("/upload/youtube/"))
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise YouTubeUploadError("YouTube returned an invalid upload session.", "invalid_session", outcome_unknown=True)
    return uri


def raise_youtube_error(response) -> None:
    code = response.status_code
    try:
        reasons = {item.get("reason") for item in response.json().get("error", {}).get("errors", []) if isinstance(item, dict)}
    except (ValueError, TypeError, AttributeError):
        reasons = set()
    if code in (404, 410):
        raise YouTubeUploadError("The upload session is unavailable. Check YouTube before starting another upload.", "session_expired", outcome_unknown=True)
    if code == 401 or reasons & {"insufficientPermissions", "authError"}:
        raise YouTubeUploadError("Reconnect YouTube to restore publishing access.", "reconnect_required", reauth=True)
    if reasons & {"quotaExceeded", "dailyLimitExceeded"}:
        raise YouTubeUploadError("Google project upload quota is exhausted; the upload will wait.", "project_quota", retryable=True)
    if "uploadLimitExceeded" in reasons:
        raise YouTubeUploadError("This YouTube channel has reached its upload limit.", "channel_quota", retryable=True)
    if code == 429 or code >= 500:
        raise YouTubeUploadError("YouTube is temporarily unavailable; the same upload will be checked again.", "temporary", retryable=True)
    raise YouTubeUploadError("YouTube rejected this upload request. Review its settings before retrying.", "rejected", rejected=True)


class YouTubeUploadProtocol:
    """Mixin for the requests-based provider; all HTTP errors omit request URLs."""

    def _upload_request(self, method: str, uri: str, access_token: str, *, timeout=60, headers=None, **kwargs):
        try:
            return getattr(self.http, method)(uri, headers={"Authorization": f"Bearer {access_token}", **(headers or {})},
                timeout=timeout, allow_redirects=False, **kwargs)
        except requests.RequestException:
            raise YouTubeUploadError("Connection interrupted; the same upload session will be checked again.", "temporary", retryable=True) from None

    def start_upload(self, access_token: str, metadata: dict, size_bytes: int) -> str:
        if size_bytes <= 0:
            raise YouTubeUploadError("The clip is empty.", "invalid_media")
        response = self._upload_request("post", UPLOAD_URL, access_token,
            params={"uploadType": "resumable", "part": "snippet,status"}, json=metadata,
            headers={"Content-Type": "application/json; charset=UTF-8", "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(size_bytes)})
        if response.status_code not in (200, 201):
            raise_youtube_error(response)
        return validate_session_uri(response.headers.get("Location") or "")

    def probe_upload(self, access_token: str, session_uri: str, size_bytes: int) -> UploadProgress:
        response = self._upload_request("put", validate_session_uri(session_uri), access_token,
            data=b"", headers={"Content-Length": "0", "Content-Range": f"bytes */{size_bytes}"})
        return self._upload_progress(response, size_bytes)

    def send_upload(self, access_token: str, session_uri: str, file_path: str, offset: int) -> UploadProgress:
        validate_session_uri(session_uri)
        size = os.path.getsize(file_path)
        if offset == size:
            return self.probe_upload(access_token, session_uri, size)
        if not 0 <= offset < size:
            raise YouTubeUploadError("The upload offset does not match this file.", "invalid_media")
        with open(file_path, "rb") as handle:
            handle.seek(offset)
            response = self._upload_request("put", session_uri, access_token, data=handle, timeout=900,
                headers={"Content-Type": "video/mp4", "Content-Length": str(size - offset),
                         "Content-Range": f"bytes {offset}-{size - 1}/{size}"})
        return self._upload_progress(response, size)

    @staticmethod
    def _upload_progress(response, size_bytes: int) -> UploadProgress:
        if response.status_code == 308:
            received = response.headers.get("Range")
            if received is None:
                return UploadProgress(0)
            match = re.fullmatch(r"bytes=0-(\d+)", received)
            if match and 0 < int(match[1]) + 1 <= size_bytes:
                return UploadProgress(int(match[1]) + 1)
            raise YouTubeUploadError("YouTube returned an inconsistent upload position.", "invalid_acknowledgement", outcome_unknown=True)
        if response.status_code in (200, 201):
            try:
                video_id = response.json().get("id")
            except (ValueError, AttributeError):
                video_id = None
            if isinstance(video_id, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", video_id):
                return UploadProgress(size_bytes, video_id)
            raise YouTubeUploadError("Upload accepted but its video ID could not be confirmed. Check YouTube before retrying.", "unknown_outcome", outcome_unknown=True)
        raise_youtube_error(response)
