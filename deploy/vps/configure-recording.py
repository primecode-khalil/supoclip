#!/usr/bin/env python3
"""Privileged, owner-scoped setup CLI. Run inside the backend container.

Server root access already grants access to the signing key. Keep it inside
this process: never print it, produce a reusable token, or put it in argv.
"""
import argparse
import asyncio
import hashlib
import hmac
import json
import os
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPRedirectHandler


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Authentication headers must never follow an unexpected redirect.
        return None


async def owner_id(email: str) -> str:
    from sqlalchemy import select
    from src.database import AsyncSessionLocal, close_db
    from src.models import User

    try:
        async with AsyncSessionLocal() as db:
            identity = (await db.execute(select(User.id).where(User.email == email))).scalar_one_or_none()
        if identity is None:
            raise SystemExit("Owner not found. Register the account in the web app first.")
        return str(identity)
    finally:
        await close_db()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True, help="Existing registered owner email")
    parser.add_argument("method", choices=("GET", "POST", "PUT", "PATCH"))
    parser.add_argument("path", help="Owner-scoped recording route, or GET /social/connections")
    args = parser.parse_args()
    if not (args.path.startswith("/recording/") or (args.method == "GET" and args.path == "/social/connections")):
        parser.error("Only recording setup and social connection listing are supported")
    if any(character in args.path for character in ("\r", "\n", "#", "\\")) or "://" in args.path:
        parser.error("Invalid API path")
    secret = os.getenv("BACKEND_AUTH_SECRET", "")
    if not secret:
        raise SystemExit("BACKEND_AUTH_SECRET is not configured")
    user = asyncio.run(owner_id(args.email))
    timestamp = str(int(time.time()))
    signature = hmac.new(secret.encode(), f"{user}:{timestamp}".encode(), hashlib.sha256).hexdigest()
    payload = None
    if args.method != "GET":
        try:
            data = json.load(sys.stdin)
        except ValueError:
            raise SystemExit("Provide a JSON object on stdin.")
        if not isinstance(data, dict):
            raise SystemExit("Provide a JSON object on stdin.")
        payload = json.dumps(data).encode()
    request = Request("http://localhost:8000" + args.path, data=payload, method=args.method,
                      headers={"Content-Type": "application/json", "x-supoclip-user-id": user,
                               "x-supoclip-ts": timestamp, "x-supoclip-signature": signature})
    try:
        with build_opener(NoRedirect()).open(request, timeout=60) as response:
            print(json.dumps(json.load(response), indent=2))
    except HTTPError as exc:
        # These scoped endpoints return safe validation errors, not signing keys.
        print(f"API returned {exc.code}: {exc.read().decode(errors='replace')[:4000]}", file=sys.stderr)
        raise SystemExit(1)
    except URLError:
        raise SystemExit("Could not reach the local backend API.")


if __name__ == "__main__":
    main()
