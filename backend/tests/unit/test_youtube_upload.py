"""Exercise Google request boundaries without a real account or upload."""
import requests
import pytest

from src.social.base import SocialProviderError
from src.social.youtube import YouTubeProvider
from tests.unit.test_social_providers import FakeResponse, FakeSession, _config

URI = "https://www.googleapis.com/upload/youtube/v3/videos?upload_id=private-session"


def provider(response):
    return YouTubeProvider(_config(), FakeSession({("PUT", "upload_id="): response}))


@pytest.mark.parametrize("range_header,expected", [(None, 0), ("bytes=0-3", 4), ("bytes=0-9", 10)])
def test_status_probe_uses_confirmed_bytes(range_header, expected):
    upload = provider(FakeResponse(308, headers={"Range": range_header} if range_header else {}))
    result = upload.probe_upload("access", URI, 10)
    assert result.confirmed_bytes == expected and result.video_id is None
    call = upload.http.calls[0][2]
    assert call["headers"]["Content-Range"] == "bytes */10"
    assert call["headers"]["Content-Length"] == "0"
    assert call["allow_redirects"] is False


def test_probe_recovers_the_video_after_a_lost_final_reply():
    result = provider(FakeResponse(201, {"id": "finished-video"})).probe_upload("access", URI, 10)
    assert result.video_id == "finished-video" and result.confirmed_bytes == 10


def test_resume_sends_only_the_remaining_bytes(tmp_path):
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"0123456789")
    bodies = []

    class Capture(FakeSession):
        def put(self, url, **kwargs):
            bodies.append(kwargs["data"].read())
            return super().put(url, **kwargs)

    http = Capture({("PUT", "upload_id="): FakeResponse(201, {"id": "finished-video"})})
    result = YouTubeProvider(_config(), http).send_upload("access", URI, str(path), 4)
    assert result.video_id == "finished-video"
    assert bodies == [b"456789"]
    assert http.calls[0][2]["headers"]["Content-Range"] == "bytes 4-9/10"
    assert http.calls[0][2]["headers"]["Content-Length"] == "6"


@pytest.mark.parametrize("uri", ["http://www.googleapis.com/upload", "https://localhost/upload?token=private", "https://www.googleapis.com.evil.example/upload", "https://user:pass@www.googleapis.com/upload", "https://www.googleapis.com:8443/upload"])
def test_untrusted_session_urls_never_receive_tokens(uri):
    upload = provider(FakeResponse(200, {"id": "wrong"}))
    with pytest.raises(SocialProviderError):
        upload.probe_upload("access", uri, 10)
    assert upload.http.calls == []


@pytest.mark.parametrize("code,reason,reauth,unknown", [(401, "authError", True, False), (403, "quotaExceeded", False, False), (403, "uploadLimitExceeded", False, False), (503, "backendError", False, False), (404, "notFound", False, True), (410, "gone", False, True)])
def test_errors_classify_recovery_without_exposing_the_session(code, reason, reauth, unknown):
    upload = provider(FakeResponse(code, {"error": {"message": URI, "errors": [{"reason": reason}]}}))
    with pytest.raises(SocialProviderError) as error:
        upload.probe_upload("access", URI, 10)
    assert error.value.reauth is reauth
    assert error.value.outcome_unknown is unknown
    assert "private-session" not in str(error.value)


@pytest.mark.parametrize("range_value", ["bytes=5-8", "bytes=0-99", "nonsense"])
def test_invalid_acknowledgements_cannot_advance_the_file(range_value):
    with pytest.raises(SocialProviderError):
        provider(FakeResponse(308, headers={"Range": range_value})).probe_upload("access", URI, 10)


def test_send_timeout_is_recoverable_through_the_same_session(tmp_path):
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"video")

    class LostReply(FakeSession):
        def put(self, *args, **kwargs):
            raise requests.Timeout(URI)

    upload = YouTubeProvider(_config(), LostReply({}))
    with pytest.raises(SocialProviderError) as error:
        upload.send_upload("access", URI, str(path), 0)
    assert error.value.retryable is True
    assert "private-session" not in str(error.value)


def test_session_initialization_sets_size_and_blocks_redirects():
    http = FakeSession({("POST", "/upload/youtube/"): FakeResponse(200, headers={"Location": URI})})
    upload = YouTubeProvider(_config(), http)
    assert upload.start_upload("access", {"status": {"privacyStatus": "private"}}, 10) == URI
    assert http.calls[0][2]["headers"]["X-Upload-Content-Length"] == "10"
    assert http.calls[0][2]["allow_redirects"] is False
