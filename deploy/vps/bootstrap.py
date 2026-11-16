#!/usr/bin/env python3
"""Resume first installation without replacing an existing container or its work."""
from __future__ import annotations
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4


class BootstrapError(RuntimeError):
    pass


def run(arguments: list[str], *, capture: bool = False, input_text: str | None = None) -> str:
    result = subprocess.run(arguments, check=True, text=True, input=input_text,
                            stdout=subprocess.PIPE if capture else None)
    return result.stdout or ""


def current_revision(directory: Path) -> str:
    try:
        return run(["git", "-C", str(directory.parents[1]), "rev-parse", "HEAD"], capture=True).strip()
    except subprocess.CalledProcessError:
        return "unknown"


def write_marker(path: Path, revision: str) -> None:
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "w") as output:
        json.dump({"revision": revision, "at": datetime.now(timezone.utc).isoformat()}, output)
        output.flush()
        os.fsync(output.fileno())
    temporary.replace(path)
    directory_descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory_descriptor)
    finally:
        os.close(directory_descriptor)


def initialize(directory: Path) -> None:
    compose = str(directory / "compose.sh")
    health = str(directory / "health.sh")
    complete = directory / ".bootstrap-complete"
    started = directory / ".bootstrap-started"
    if complete.exists():
        print("Existing completed installation detected; checking health without restarting services.")
        try:
            run([health])
        except subprocess.CalledProcessError as exc:
            raise BootstrapError("Existing installation is unhealthy. No services were restarted. Run deploy/vps/health.sh and deploy/vps/compose.sh ps; use the drained maintenance runbook before replacing containers.") from exc
        return

    revision = current_revision(directory)
    if started.exists():
        try:
            recorded = json.loads(started.read_text())["revision"]
        except (ValueError, KeyError):
            raise BootstrapError("The bootstrap state file is invalid; inspect it before resuming.")
        if recorded != revision and "unknown" not in {recorded, revision}:
            raise BootstrapError("An incomplete installation belongs to a different source revision. Return to its recorded revision before resuming; running containers were left untouched.")
    else:
        write_marker(started, revision)

    existing = bool(run([compose, "ps", "--all", "--quiet"], capture=True).strip())
    if existing:
        print("Incomplete first installation detected; starting missing services only. Running containers will not be replaced.")
    else:
        run(["df", "-h", str(directory)])
        run([compose, "build", "--pull"])
        run([compose, "pull", "--ignore-buildable", "postgres", "redis", "caddy"])
        run([compose, "run", "--rm", "--no-deps", "caddy", "caddy", "validate", "--config", "/etc/caddy/Caddyfile"])

    # --no-recreate is essential on every recovery path: no running API, worker,
    # recorder, or queued work is interrupted, even if config files have changed.
    up = [compose, "up", "-d", "--no-build", "--no-recreate", "--wait", "--wait-timeout", "300"]
    run([*up, "backend"])
    guard = run([compose, "exec", "-T", "postgres", "psql", "-v", "ON_ERROR_STOP=1", "-U", "supoclip", "-d", "supoclip", "-Atqc",
                 "SELECT to_regclass('public.single_user_installation') IS NOT NULL"], capture=True).strip()
    if guard != "t":
        # Never alter an exposed installation whose first-owner guard is missing.
        exposed = run([compose, "ps", "--status", "running", "--quiet", "frontend"], capture=True).strip()
        if exposed:
            raise BootstrapError("The frontend is already running without the single-owner database guard. No containers were replaced; restrict public access and follow the setup recovery runbook before continuing.")
        run([compose, "exec", "-T", "postgres", "psql", "-v", "ON_ERROR_STOP=1", "-U", "supoclip", "-d", "supoclip"],
            input_text=(directory / "single-user.sql").read_text())

    run(up)
    run([health])
    # This is the sole success marker; merely having PostgreSQL/backend containers
    # is not evidence that the dashboard and all workers started successfully.
    write_marker(complete, revision)
    print("Initial installation completed and all application health checks passed.")


def main() -> None:
    directory = Path(__file__).resolve().parent
    # An OS lock releases itself after a crash; no stale PID/lock directory blocks
    # the next invocation. The file contains no credentials.
    lock_descriptor = os.open(directory / ".bootstrap.lock", os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(lock_descriptor, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("Another installer is already working on this checkout.")
        try:
            initialize(directory)
        except BootstrapError as exc:
            raise SystemExit(str(exc))
        except subprocess.CalledProcessError:
            raise SystemExit("Bootstrap did not complete. Its success marker was not written. Rerun install.sh at the same revision to start missing services without replacing running containers; inspect compose.sh ps/logs if a service remains unhealthy.")


if __name__ == "__main__":
    main()
