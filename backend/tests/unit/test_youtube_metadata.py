"""Provider requests obey byte limits and the owner's explicit upload choices."""
import pytest

from src.social.base import PublishRequest, SocialProviderError
from src.social.youtube import YouTubeProvider
from tests.unit.test_social_providers import FakeResponse, FakeSession, _config


def metadata(tmp_path, *, title="A useful clip", caption="A complete thought", options=None, privacy="private", tags=None):
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"video")
    request = PublishRequest(str(path), title, caption, tags or [], privacy)
    # Dynamic assignment lets these assertions exercise the old adapter first.
    request.provider_options = options or {}
    http = FakeSession({
        ("POST", "/upload/youtube/"): FakeResponse(headers={"Location": "https://www.googleapis.com/upload/youtube/v3/videos?upload_id=test"}),
        ("PUT", "upload_id=test"): FakeResponse(payload={"id": "video-1"}),
    })
    YouTubeProvider(_config(), http).publish("access", request)
    return http.calls[0][2]["json"]


def test_description_is_bounded_in_utf8_bytes(tmp_path):
    result = metadata(tmp_path, caption="é🎥" * 1600)
    description = result["snippet"]["description"]
    assert len(description.encode("utf-8")) <= 5000
    assert "�" not in description
    assert description.endswith("#Shorts")


def test_upload_uses_selected_audience_category_and_disclosure(tmp_path):
    result = metadata(tmp_path, options={"category_id": "20", "made_for_kids": True, "contains_synthetic_media": True})
    assert result["status"] == {"privacyStatus": "private", "selfDeclaredMadeForKids": True, "containsSyntheticMedia": True}
    assert result["snippet"]["categoryId"] == "20"


def test_metadata_fallback_and_title_are_safe(tmp_path):
    result = metadata(tmp_path, title="<>" + "🎥" * 110, caption="")
    assert result["snippet"]["title"] == "🎥" * 100
    assert result["snippet"]["description"] == "#Shorts"
    assert result["status"]["privacyStatus"] == "private"
    assert metadata(tmp_path, title="  ")["snippet"]["title"] == "Untitled clip"


def test_tag_budget_accounts_for_spaces_and_separators(tmp_path):
    result = metadata(tmp_path, tags=["a long tag " + "x" * 100 + str(n) for n in range(30)])
    tags = result["snippet"]["tags"]
    assert sum(len(tag) + (2 if " " in tag else 0) for tag in tags) + max(0, len(tags) - 1) <= 500


@pytest.mark.parametrize("options", [{"made_for_kids": "false"}, {"category_id": "bad"}, {"contains_synthetic_media": "true"}])
def test_invalid_owner_settings_fail_before_network(tmp_path, options):
    with pytest.raises(SocialProviderError):
        metadata(tmp_path, options=options)
