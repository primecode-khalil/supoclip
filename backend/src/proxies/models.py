"""The encrypted registry's small, versioned value format."""
from __future__ import annotations

import ipaddress
import json
import re
from dataclasses import asdict, dataclass, field
from urllib.parse import urlsplit

SETTING_KEY = "PROXY_CONNECTIONS"
MAX_URL_CONNECTIONS = 10
PURPOSES = {"live", "imports", "both"}
SCHEMES = {"http": 80, "https": 443, "socks5": 1080, "socks5h": 1080}


def validate_proxy_url(value: str) -> str:
    message = "Enter a valid HTTP, HTTPS, SOCKS5 or SOCKS5h proxy endpoint."
    try:
        if not isinstance(value, str) or not value.strip() or len(value) > 2048:
            raise ValueError
        value = value.strip()
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError
        sample = value.replace("{session}", "session").replace("{country}", "us")
        if "{" in sample or "}" in sample:
            raise ValueError
        parsed = urlsplit(sample)
        if (parsed.scheme not in SCHEMES or not parsed.hostname or parsed.path not in {"", "/"}
                or parsed.query or parsed.fragment or parsed.port == 0):
            raise ValueError
        host = parsed.hostname
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            if not re.fullmatch(r"[A-Za-z0-9_.-]{1,253}", host.encode("idna").decode()):
                raise ValueError from None
        else:
            if address.is_unspecified or address.is_multicast:
                raise ValueError
        # Accessing .port validates the numeric range even when no port is given.
        _ = parsed.port
        return value.rstrip("/")
    except (ValueError, UnicodeError):
        raise ValueError(message) from None


def validate_name(value: str) -> str:
    if (not isinstance(value, str) or not 1 <= len(value.strip()) <= 80
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise ValueError("Enter a connection name of 1 to 80 characters.")
    return value.strip()


@dataclass(frozen=True)
class Connection:
    id: str
    name: str
    url: str | None = field(repr=False)
    usage: str = "both"
    priority: int = 0
    enabled: bool = True
    country: str = ""
    revision: str = ""
    kind: str = "url"

    @property
    def key(self) -> str:
        return f"{self.id}:{self.revision}"

    def public(self) -> dict:
        parsed = urlsplit((self.url or "").replace("{session}", "session").replace("{country}", "us"))
        host = parsed.hostname or ""
        port = parsed.port or SCHEMES.get(parsed.scheme)
        endpoint = (f"[{host}]" if ":" in host else host) + (f":{port}" if port else "")
        return {"id": self.id, "name": self.name, "kind": self.kind, "usage": self.usage,
                "priority": self.priority, "enabled": self.enabled, "country": self.country,
                "revision": self.revision, "endpoint": endpoint or None,
                "scheme": parsed.scheme or None, "has_credentials": parsed.username is not None}


@dataclass(frozen=True)
class Registry:
    connections: tuple[Connection, ...] = ()
    unavailable: bool = False

    def assigned(self, purpose: str) -> list[Connection]:
        if purpose not in {"live", "imports"}:
            raise ValueError("Unknown proxy purpose")
        return sorted((c for c in self.connections if c.enabled and c.usage in {purpose, "both"}),
                      key=lambda c: (c.priority, c.id))

    def required(self, purpose: str) -> bool:
        return self.unavailable or bool(self.assigned(purpose))

    def encode(self) -> str:
        if self.unavailable:
            raise ValueError("Saved proxy settings are unavailable.")
        return json.dumps({"schema_version": 1, "connections": [asdict(c) for c in self.connections]}, separators=(",", ":"))

    @classmethod
    def decode(cls, value: str | None) -> Registry | None:
        if value is None:
            return None  # Never configured: preserve legacy routes until adoption.
        try:
            data = json.loads(value)
            if not isinstance(data, dict) or set(data) != {"schema_version", "connections"} or data["schema_version"] != 1:
                raise ValueError
            entries = data["connections"]
            if not isinstance(entries, list) or len(entries) > MAX_URL_CONNECTIONS + 1:
                raise ValueError
            rows, identities = [], set()
            for entry in entries:
                row = Connection(**entry)
                validate_name(row.name)
                if (not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", row.id) or row.id in identities
                        or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", row.revision)
                        or row.usage not in PURPOSES or type(row.enabled) is not bool
                        or type(row.priority) is not int or not 0 <= row.priority <= 1000
                        or (row.country and not re.fullmatch(r"[a-z]{2}", row.country))):
                    raise ValueError
                if row.kind == "url":
                    if row.url is not None:
                        validate_proxy_url(row.url)
                elif row.kind != "home" or row.url is not None:
                    raise ValueError
                identities.add(row.id)
                rows.append(row)
            if sum(c.kind == "home" for c in rows) > 1 or sum(c.kind == "url" for c in rows) > MAX_URL_CONNECTIONS:
                raise ValueError
            return cls(tuple(rows))
        except (ValueError, TypeError, AttributeError, KeyError):
            # Missing credentials/invalid documents must never enable direct use.
            return cls(unavailable=True)
