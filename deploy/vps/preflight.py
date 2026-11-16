#!/usr/bin/env python3
"""Validate rendered deployment config without printing secret-bearing values."""
import json
from pathlib import Path
import re
import stat
import subprocess
import sys
from urllib.parse import urlparse


def fail(message: str) -> None:
    raise SystemExit(message)


def validate(config: dict, directory: Path) -> None:
    services = config["services"]
    env = services["backend"]["environment"]
    frontend = services["frontend"]["environment"]
    caddy = services["caddy"]["environment"]
    for filename in (".env", "rclone.conf"):
        private_file = directory / filename
        if not private_file.is_file() or private_file.is_symlink():
            fail(f"{filename} must be a regular private file; run init-env.py first.")
        if stat.S_IMODE(private_file.stat().st_mode) & 0o077:
            fail(f"{filename} must be readable only by its owner (chmod 600).")
    app = urlparse(frontend["BETTER_AUTH_URL"])
    if app.scheme not in {"http", "https"} or not app.hostname or app.path not in {"", "/"}:
        fail("APP_ORIGIN must be an http(s) origin without a path.")
    if app.scheme == "https":
        domain = caddy.get("APP_DOMAIN", "")
        if not re.fullmatch(r"(?=.{1,253}$)(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,63}", domain):
            fail("HTTPS requires a public APP_DOMAIN hostname.")
        proxy_mounts = services["caddy"].get("volumes", [])
        https_proxy = any(mount.get("target") == "/etc/caddy/Caddyfile" and str(mount.get("source", "")).endswith("Caddyfile.https") for mount in proxy_mounts)
        if domain != app.hostname or not https_proxy:
            fail("HTTPS origin and proxy mode must match; rerun installer --domain for first setup.")
        if not caddy.get("ACME_EMAIL"):
            fail("Set ACME_EMAIL for HTTPS certificate management.")
    if services["frontend"]["build"]["args"].get("NEXT_PUBLIC_API_URL") != frontend["BETTER_AUTH_URL"].rstrip("/") + "/backend":
        fail("API_ORIGIN must use the application origin with /backend for this proxy bundle.")
    token = frontend.get("INITIAL_SETUP_TOKEN", "")
    if len(token) < 32:
        fail("INITIAL_SETUP_TOKEN must contain at least 32 characters.")
    if frontend.get("SELF_HOST_SINGLE_USER") != "true":
        fail("This installer requires protected single-operator setup.")
    secrets = {key: env.get(key, "") for key in ("REDIS_PASSWORD", "BACKEND_AUTH_SECRET", "APP_SETTINGS_ENCRYPTION_KEY")}
    secrets["BETTER_AUTH_SECRET"] = frontend.get("BETTER_AUTH_SECRET", "")
    # Validate the decoded database URL password without including it in diagnostics.
    password = urlparse(env["DATABASE_URL"].replace("postgresql+asyncpg:", "postgresql:")).password or ""
    secrets["POSTGRES_PASSWORD"] = password
    for key, value in secrets.items():
        if len(value) < 32 or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
            fail(f"{key} must contain at least 32 URL-safe characters; keep the generated value.")
    if len(set(secrets.values())) != len(secrets):
        fail("Use distinct secrets for each server function.")
    if env.get("ALLOW_UNSIGNED_BACKEND_AUTH") != "false":
        fail("Unsigned backend authentication must remain disabled.")
    if env.get("SOCIAL_PUBLISHING_ACCESS") not in {"off", "admins", "all"}:
        fail("SOCIAL_PUBLISHING_ACCESS must be off, admins, or all.")
    for name, service in services.items():
        if name != "caddy" and service.get("ports"):
            fail(f"{name} must not expose a host port in this bundle.")
    if services["frontend"]["build"].get("target") != "runner":
        fail("Use the production frontend runner target.")


def main() -> None:
    directory = Path(__file__).resolve().parent
    version = subprocess.run(["docker", "compose", "version", "--short"], capture_output=True, text=True)
    match = re.match(r"v?(\d+)\.(\d+)", version.stdout.strip())
    if version.returncode or not match or tuple(map(int, match.groups())) < (2, 30):
        fail("Docker Compose v2.30 or newer is required; update the matching Compose plugin for your existing Docker installation.")
    result = subprocess.run([str(directory / "compose.sh"), "config", "--format", "json"],
                            capture_output=True, text=True)
    if result.returncode:
        fail("Compose configuration is invalid or .env is missing. Run compose.sh config --quiet for diagnostics; do not share a full rendered config.")
    try:
        validate(json.loads(result.stdout), directory)
    except (KeyError, ValueError, TypeError):
        fail("Compose configuration has an unexpected structure.")
    print("Configuration passed: production frontend, private service ports, distinct server secrets, protected first-owner setup. AI/OAuth credentials can be configured in the dashboard.")


if __name__ == "__main__":
    main()
