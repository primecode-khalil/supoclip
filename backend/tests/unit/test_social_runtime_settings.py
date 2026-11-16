import pytest

from src.config import Config
from src.api.routes.admin import SETTING_METADATA
from src.runtime_settings import RUNTIME_SETTING_KEYS


@pytest.mark.parametrize("key,attribute", [
    ("YOUTUBE_OAUTH_CLIENT_ID", "youtube_oauth_client_id"),
    ("YOUTUBE_OAUTH_CLIENT_SECRET", "youtube_oauth_client_secret"),
    ("TIKTOK_CLIENT_KEY", "tiktok_client_key"),
    ("TIKTOK_CLIENT_SECRET", "tiktok_client_secret"),
    ("INSTAGRAM_APP_ID", "instagram_app_id"),
    ("INSTAGRAM_APP_SECRET", "instagram_app_secret"),
])
def test_social_apps_use_encrypted_admin_settings(monkeypatch, key, attribute):
    monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr("src.config.get_cached_setting", lambda name: "configured-in-dashboard" if name == key else None)
    assert key in RUNTIME_SETTING_KEYS and key in SETTING_METADATA
    assert getattr(Config(), attribute) == "configured-in-dashboard"
