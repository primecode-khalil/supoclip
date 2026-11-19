"""Setup is owner-scoped and never returns credentials or changes automation."""
import pytest

from src.services.social_service import SocialService
from tests.integration.test_social_publishing import social_setup  # noqa: F401


async def test_setup_is_authenticated_and_omits_secrets(social_setup, client, auth_headers, app, monkeypatch):
    monkeypatch.setattr(app.state.config, "youtube_oauth_client_id", "configured-client")
    monkeypatch.setattr(app.state.config, "youtube_oauth_client_secret", "never-display-this")
    assert (await client.get("/social/youtube/setup")).status_code == 401
    response = await client.get("/social/youtube/setup", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["configured"] is True
    assert data["redirect_uri"].endswith("/api/social/callback/youtube")
    assert len(data["connections"]) == 1
    assert data["refresh_access_available"] is True
    assert data["private_test_completed"] is False
    assert "never-display-this" not in response.text
    assert "encrypted" not in response.text and "refresh_token" not in response.text


async def test_self_host_scheduling_does_not_require_a_paid_plan(social_setup, app, db_session, monkeypatch):
    from src.services.billing_service import BillingService

    async def forbidden(*args, **kwargs):
        raise AssertionError("self-host publishing must not query a paid-plan entitlement")

    monkeypatch.setattr(BillingService, "get_usage_summary", forbidden)
    app.state.config.self_host = True
    app.state.config.monetization_enabled = False
    assert await SocialService(db_session, app.state.config).can_schedule("user-1") is True
