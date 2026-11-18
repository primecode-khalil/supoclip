"""Boundary tests for private home-proxy setup and credentials."""
import pytest
from httpx import ASGITransport, AsyncClient

from src.config import Config, set_config_override
from src.database import get_db
from src.main import create_app


async def test_home_proxy_management_rejects_anonymous_requests_without_database():
    config = Config()
    config.backend_auth_secret = "home-proxy-test-secret"
    config.allow_unsigned_backend_auth = False
    app = create_app(config=config)

    async def no_database():
        yield None

    app.dependency_overrides[get_db] = no_database
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        for method, path in (("GET", ""), ("POST", "/setup"), ("POST", "/disconnect")):
            response = await client.request(method, "/recording/home-proxy" + path)
            assert response.status_code == 401
    set_config_override(None)


# A real OpenSSH Ed25519 wire key (algorithm string + 32-byte public key).
KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIJvTNd7zvW4TP3Hobf2N+KtOUaQKa1Ywm/bhl7Uy7xua"


@pytest.mark.parametrize("value", [
    "", "ssh-rsa AAAAB3NzaC1yc2E=", "ssh-ed25519 invalid!", "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAAA==",
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIJvTNd7zvW4TP3Hobf2N+KtOUaQKa1Ywm/bhl7Uy7xuaAAAA",
    KEY + "\ncommand=evil", "command=evil " + KEY,
])
def test_public_key_rejects_other_algorithms_bad_lengths_and_authorized_key_options(value):
    from src.api.routes.home_proxy import normalize_public_key
    with pytest.raises(ValueError):
        normalize_public_key(value)


def test_public_key_removes_comments_before_persisting():
    from src.api.routes.home_proxy import normalize_public_key
    assert normalize_public_key(KEY + " My Mac public key") == KEY


@pytest.fixture
def proxy_env(monkeypatch):
    values = {
        "HOME_PROXY_SSH_HOST": "relay.example.com",
        "HOME_PROXY_SSH_HOST_KEY": KEY,
        "HOME_PROXY_REMOTE_BIND": "172.30.0.1",
        "HOME_PROXY_URL": "http://172.30.0.1:18888",
        "HOME_PROXY_APP_ORIGIN": "https://app.example.com",
    }
    for key in ("HOME_PROXY_SSH_PORT", "HOME_PROXY_SSH_USER", "HOME_PROXY_REMOTE_PORT"):
        monkeypatch.delenv(key, raising=False)
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    return values


def test_environment_requires_matching_private_bridge_and_valid_pinned_key(proxy_env):
    from src.api.routes.home_proxy import load_settings
    settings = load_settings()
    assert settings is not None
    assert settings.ssh_port == 2222
    assert settings.ssh_user == "supoclip-relay"
    assert settings.remote_port == 18888
    assert settings.app_origin == "https://app.example.com"


@pytest.mark.parametrize("key,value", [
    ("HOME_PROXY_SSH_HOST", ""), ("HOME_PROXY_SSH_HOST", "-oProxyCommand=evil"),
    ("HOME_PROXY_SSH_HOST_KEY", "ssh-rsa AAAA"), ("HOME_PROXY_SSH_PORT", "70000"),
    ("HOME_PROXY_SSH_USER", "root; evil"),
    ("HOME_PROXY_SSH_USER", "other-user"),
    ("HOME_PROXY_REMOTE_PORT", "1023"), ("HOME_PROXY_REMOTE_BIND", "0.0.0.0"),
    ("HOME_PROXY_REMOTE_BIND", "8.8.8.8"), ("HOME_PROXY_URL", "http://169.254.169.254:18888"),
    ("HOME_PROXY_URL", "http://name:password@172.30.0.1:18888"),
    ("HOME_PROXY_URL", "http://172.30.0.1:18888/path"),
    ("HOME_PROXY_APP_ORIGIN", "https://app.example.com/?token=oops"),
    ("HOME_PROXY_APP_ORIGIN", "http://app.example.com"),
    ("HOME_PROXY_APP_ORIGIN", "https://app.example.com:bad"),
    ("HOME_PROXY_APP_ORIGIN", "https://app.example.com:70000"),
])
def test_invalid_or_missing_environment_disables_setup(proxy_env, monkeypatch, key, value):
    from src.api.routes.home_proxy import load_settings
    monkeypatch.setenv(key, value)
    assert load_settings() is None


@pytest.mark.parametrize("curl_exit", [0, 22])
def test_setup_command_uses_private_temp_file_cleans_up_and_requires_successful_download(tmp_path, monkeypatch, curl_exit):
    import os
    import subprocess
    from pathlib import Path
    import sys
    from src.api.routes.home_proxy import _setup_command

    # A real shell executes the wrapper; only the network download is replaced.
    log = tmp_path / "installer-args"
    download = tmp_path / "download-location"
    fake_curl = tmp_path / "curl"
    fake_curl.write_text(
        "#!" + sys.executable + "\n"
        "import os, pathlib, stat, sys\n"
        "destination = pathlib.Path(sys.argv[sys.argv.index('-o') + 1])\n"
        "assert stat.S_IMODE(destination.stat().st_mode) == 0o600\n"
        "pathlib.Path(os.environ['HOME_PROXY_TEST_DOWNLOAD']).write_text(str(destination))\n"
        "destination.write_text('printf \\\'%s\\\\n\\\' \\\"$1\\\" \\\"$2\\\" > \\\"$HOME_PROXY_TEST_LOG\\\"\\n')\n"
        f"sys.exit({curl_exit})\n"
    )
    fake_curl.chmod(0o700)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("HOME_PROXY_TEST_LOG", str(log))
    monkeypatch.setenv("HOME_PROXY_TEST_DOWNLOAD", str(download))
    token = "test-token-with-'quotes' and $literal;data"
    result = subprocess.run(_setup_command("https://app.example.com", token), shell=True, capture_output=True)
    assert result.returncode == curl_exit
    assert not Path(download.read_text()).exists()
    if curl_exit == 0:
        assert log.read_text().splitlines() == ["https://app.example.com", token]
    else:
        assert not log.exists()


async def test_install_assets_are_anonymous_but_have_no_instance_credentials():
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        for filename in ("install.sh", "helper.py"):
            response = await client.get("/recording/home-proxy/" + filename)
            assert response.status_code == 200
            assert response.headers["cache-control"] == "no-store"
            assert "ssh-ed25519 AAAA" not in response.text
            assert "test-backend-auth-secret" not in response.text



def test_standard_ssh_port_is_supported_but_reverse_listener_must_be_unprivileged(proxy_env, monkeypatch):
    from src.api.routes.home_proxy import load_settings
    monkeypatch.setenv("HOME_PROXY_SSH_PORT", "22")
    assert load_settings().ssh_port == 22
    monkeypatch.setenv("HOME_PROXY_REMOTE_PORT", "22")
    monkeypatch.setenv("HOME_PROXY_URL", "http://172.30.0.1:22")
    assert load_settings() is None
