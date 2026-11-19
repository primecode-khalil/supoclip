#!/usr/bin/env python3
"""Root-owned host controller. Installs only validated public tunnel keys."""
import argparse
import base64
import ipaddress
import json
import os
from pathlib import Path
import subprocess
import time

USER = 'supoclip-relay'


def authorized_key(value, bridge, port):
    parts = value.split()
    if len(parts) != 2 or parts[0] != 'ssh-ed25519':
        raise ValueError('Only canonical Ed25519 public keys are accepted')
    raw = base64.b64decode(parts[1], validate=True)
    if len(raw) != 51 or raw[:19] != b'\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20':
        raise ValueError('Malformed public key')
    if not ipaddress.ip_address(bridge).is_private or ipaddress.ip_address(bridge).is_unspecified:
        raise ValueError('A private bridge listener is required')
    if not 1024 <= port <= 65535:
        raise ValueError('Invalid listener port')
    return f'restrict,port-forwarding,permitlisten="{bridge}:{port}",command="/bin/false" {value}\n'


def sync_once(compose, path, bridge, port):
    query = "SELECT COALESCE(json_agg(public_key),'[]'::json) FROM (SELECT public_key FROM home_proxy_devices WHERE revoked_at IS NULL ORDER BY paired_at DESC LIMIT 1) active"
    r = subprocess.run([str(compose), 'exec', '-T', 'postgres', 'psql', '-U', 'supoclip', '-d', 'supoclip', '-Atqc', query],
                       capture_output=True, text=True, timeout=10, check=True)
    keys = json.loads(r.stdout.strip())
    if not isinstance(keys, list) or len(keys) > 1:
        raise ValueError('Invalid relay key state')
    contents = ''.join(authorized_key(k, bridge, port) for k in keys)
    old = path.read_text() if path.exists() else ''
    if old == contents:
        return
    temp = path.with_suffix('.new')
    temp.write_text(contents)
    temp.chmod(0o644)
    os.replace(temp, path)
    # Key removal alone does not close an already authenticated connection.
    subprocess.run(['/usr/bin/pkill', '-TERM', '-u', USER], capture_output=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path('/opt/supoclip'))
    parser.add_argument('--bridge', required=True)
    parser.add_argument('--port', type=int, default=18888)
    args = parser.parse_args()
    path = Path('/var/lib/supoclip-relay/.ssh/authorized_keys')
    last_ok = time.monotonic()
    while True:
        try:
            sync_once(args.root / 'deploy/vps/compose.sh', path, args.bridge, args.port)
            last_ok = time.monotonic()
        except Exception:
            # DB outages must not keep a revoked tunnel alive indefinitely.
            if time.monotonic() - last_ok > 30 and path.exists() and path.stat().st_size:
                path.write_text('')
                subprocess.run(['/usr/bin/pkill', '-TERM', '-u', USER], capture_output=True)
        time.sleep(5)


if __name__ == '__main__':
    main()
