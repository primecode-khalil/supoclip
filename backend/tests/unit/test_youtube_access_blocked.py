from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from src import youtube_proxy, youtube_utils
from src.api.routes import admin, tasks
from src.config import Config, set_config_override
from src.runtime_settings import RUNTIME_SETTING_KEYS

URL = "https://www.youtube.com/watch?v=abcdefghijk"
BOT = "Sign in to confirm you’re not a bot. Use --cookies for authentication."


@pytest.fixture
def config():
    config = Config()
    config.youtube_metadata_provider = "yt_dlp"
    set_config_override(config)
    yield config
    set_config_override(None)


def test_missing_metadata_key_does_not_hide_youtube_bot_block(config, monkeypatch):
    monkeypatch.setattr(youtube_utils, "_fetch_video_info_with_ytdlp", Mock(side_effect=RuntimeError(BOT)))
    monkeypatch.setattr(youtube_utils, "_fetch_video_info_with_youtube_data_api", Mock(side_effect=RuntimeError("Missing metadata key")))
    with pytest.raises(RuntimeError, match="YouTube blocked"):
        youtube_utils.get_youtube_video_info(URL)


def test_successful_independent_metadata_provider_still_wins(config, monkeypatch):
    monkeypatch.setattr(youtube_utils, "_fetch_video_info_with_ytdlp", Mock(side_effect=RuntimeError(BOT)))
    monkeypatch.setattr(youtube_utils, "_fetch_video_info_with_youtube_data_api", Mock(return_value={"duration": 600}))
    assert youtube_utils.get_youtube_video_info(URL) == {"duration": 600}


def test_provider_errors_do_not_leak_proxy_credentials(config, monkeypatch, caplog):
    monkeypatch.setattr(youtube_utils, "_fetch_video_info_with_ytdlp", Mock(side_effect=RuntimeError("Failed http://proxy-user:proxy-password@proxy.invalid:8080")))
    monkeypatch.setattr(youtube_utils, "_fetch_video_info_with_youtube_data_api", Mock(side_effect=RuntimeError("Missing metadata key")))
    assert youtube_utils.get_youtube_video_info(URL) is None
    assert "proxy-password" not in caplog.text


@pytest.mark.asyncio
async def test_bot_block_has_actionable_preflight_error(config, monkeypatch):
    error_type = getattr(youtube_proxy, "YouTubeAccessBlockedError", RuntimeError)
    monkeypatch.setattr(tasks, "async_get_youtube_video_info", AsyncMock(side_effect=error_type()))
    with pytest.raises(HTTPException) as error:
        await tasks._preflight_youtube_source(URL, 5400)
    assert error.value.status_code == 503
    assert error.value.detail["code"] == "YOUTUBE_ACCESS_BLOCKED"
    assert "Admin" in error.value.detail["message"]
    assert "No minutes were used" in error.value.detail["message"]


@pytest.mark.parametrize("key,attribute,value", [
    ("YOUTUBE_PROXY_URL", "youtube_proxy_url", "http://user:secret@proxy.invalid:8080"),
    ("YOUTUBE_PROXY_COUNTRY", "youtube_proxy_country", "de"),
    ("YOUTUBE_POT_PROVIDER_URL", "youtube_pot_provider_url", "http://token-provider:4416"),
])
def test_youtube_connection_uses_encrypted_dashboard_settings(monkeypatch, key, attribute, value):
    monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr("src.config.get_cached_setting", lambda name: value if name == key else None)
    assert key in RUNTIME_SETTING_KEYS and key in admin.SETTING_METADATA
    assert getattr(Config(), attribute) == value

