#!/usr/bin/env python3
"""Create private deployment files once, without displaying generated secrets."""
from pathlib import Path
import os
import secrets


def main() -> None:
    directory = Path(__file__).resolve().parent
    template = (directory / ".env.example").read_text()
    for key in ("POSTGRES_PASSWORD", "REDIS_PASSWORD", "BACKEND_AUTH_SECRET",
                "APP_SETTINGS_ENCRYPTION_KEY", "BETTER_AUTH_SECRET", "INITIAL_SETUP_TOKEN"):
        template = template.replace(f"{key}=\n", f"{key}={secrets.token_hex(32)}\n")
    destination = directory / ".env"
    try:
        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise SystemExit("Private .env already exists; it was left untouched.")
    with os.fdopen(descriptor, "w") as output:
        output.write(template)
    try:
        descriptor = os.open(directory / "rclone.conf", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(descriptor)
    except FileExistsError:
        pass
    print("Created private server configuration and archive config. Provider and channel setup will be available in the dashboard.")


if __name__ == "__main__":
    main()
