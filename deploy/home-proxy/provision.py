#!/usr/bin/env python3
"""Optional root-run provisioning for the dashboard's Mac home connection."""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess


def run(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout.strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('/opt/supoclip'))
    parser.add_argument('--ssh-host', required=True)
    parser.add_argument('--ssh-port', type=int, default=2222)
    parser.add_argument('--remote-port', type=int, default=18888)
    args = parser.parse_args()
    if os.getuid() != 0:
        parser.error('Run this server provisioning command as root')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{0,252}', args.ssh_host):
        parser.error('Use a public SSH hostname or IPv4 address')
    if not 1 <= args.ssh_port <= 65535 or not 1024 <= args.remote_port <= 65535:
        parser.error('Use a valid SSH port and an unprivileged proxy port')
    root = args.root.resolve()
    network = json.loads(run('docker', 'network', 'inspect', 'supoclip-vps_default'))[0]
    bridge = network['IPAM']['Config'][0]['Gateway']
    if not ipaddress.ip_address(bridge).is_private or ':' in bridge:
        parser.error('The recording network needs a private IPv4 gateway')
    if subprocess.run(['id', '-u', 'supoclip-relay'], capture_output=True).returncode:
        run('useradd', '--system', '--create-home', '--home-dir', '/var/lib/supoclip-relay', '--shell', '/bin/false', 'supoclip-relay')
    directory = Path('/var/lib/supoclip-relay/.ssh')
    directory.mkdir(mode=0o755, parents=True, exist_ok=True)
    config = Path('/etc/ssh/sshd_config.d/80-supoclip-relay.conf')
    previous = config.read_text() if config.exists() else None
    if previous and 'Match User supoclip-relay' not in previous:
        raise RuntimeError('Preserve an existing non-SupoClip SSH configuration')
    config.write_text(f'''# Managed by SupoClip home proxy provisioning.
Match User supoclip-relay
    AllowTcpForwarding remote
    AllowStreamLocalForwarding no
    GatewayPorts clientspecified
    PermitListen {bridge}:{args.remote_port}
    PermitOpen none
    PasswordAuthentication no
    KbdInteractiveAuthentication no
    AuthenticationMethods publickey
    PermitTTY no
    X11Forwarding no
    AllowAgentForwarding no
    ForceCommand /bin/false
    MaxSessions 0
Match all
''')
    try:
        run('sshd', '-t')
    except Exception:
        if previous is None:
            config.unlink()
        else:
            config.write_text(previous)
        raise
    run('systemctl', 'reload', 'ssh')
    firewall = run('ufw', 'status') if Path('/usr/sbin/ufw').exists() else ''
    if 'Status: active' in firewall:
        interface = network.get('Options', {}).get('com.docker.network.bridge.name') or 'br-' + network['Id'][:12]
        subnet = str(ipaddress.ip_network(network['IPAM']['Config'][0]['Subnet']))
        run('ufw', 'allow', 'in', 'on', interface, 'proto', 'tcp', 'from', subnet, 'to', bridge,
            'port', str(args.remote_port), 'comment', 'SupoClip home proxy private')
    env = root / 'deploy/vps/.env'
    lines = env.read_text().splitlines()
    values = dict(l.split('=', 1) for l in lines if l and not l.startswith('#') and '=' in l)
    updates = {
        'HOME_PROXY_SSH_HOST': args.ssh_host,
        'HOME_PROXY_SSH_PORT': str(args.ssh_port),
        'HOME_PROXY_SSH_USER': 'supoclip-relay',
        'HOME_PROXY_SSH_HOST_KEY': ' '.join(Path('/etc/ssh/ssh_host_ed25519_key.pub').read_text().split()[:2]),
        'HOME_PROXY_REMOTE_BIND': bridge,
        'HOME_PROXY_REMOTE_PORT': str(args.remote_port),
        'HOME_PROXY_URL': f'http://{bridge}:{args.remote_port}',
        'HOME_PROXY_APP_ORIGIN': values['APP_ORIGIN'],
    }
    output = [line for line in lines if line.split('=', 1)[0] not in updates]
    env.write_text('\n'.join(output + [k + '=' + v for k, v in updates.items()]) + '\n')
    env.chmod(0o600)
    unit = Path('/etc/systemd/system/supoclip-home-proxy.service')
    if any(c in str(root) for c in '\n\r"%') or ' ' in str(root):
        raise RuntimeError('Use a simple absolute installation path for the host service')
    unit.write_text(f'''[Unit]
Description=SupoClip restricted home proxy public-key controller
After=docker.service supoclip-vps.service
Requires=docker.service
[Service]
Type=simple
ExecStart=/usr/bin/python3 {root}/deploy/home-proxy/controller.py --root {root} --bridge {bridge} --port {args.remote_port}
Restart=on-failure
RestartSec=10
UMask=0077
NoNewPrivileges=true
[Install]
WantedBy=multi-user.target
''')
    run('systemctl', 'daemon-reload')
    run('systemctl', 'enable', '--now', 'supoclip-home-proxy.service')
    # enable --now does not apply changed ExecStart arguments to an existing process.
    run('systemctl', 'restart', 'supoclip-home-proxy.service')
    print('Home connection provisioned. Apply the updated Compose environment after draining active work.')


if __name__ == '__main__':
    main()
