#!/usr/bin/env python3
"""Private YouTube CONNECT proxy and reconnecting tunnel. Standard library only."""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import re
import select
import signal
import socket
import socketserver
import subprocess
import threading
import time
from urllib.parse import urlsplit

DOMAINS = ('youtube.com', 'youtube-nocookie.com', 'googlevideo.com', 'ytimg.com', 'googleapis.com', 'gstatic.com', 'google.com', 'ggpht.com')


def authority_host(authority):
    parsed = urlsplit('//' + authority)
    host = (parsed.hostname or '').lower()
    if (parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment
            or parsed.port != 443 or not re.fullmatch(r'[a-z0-9.-]+', host)
            or not any(host == d or host.endswith('.' + d) for d in DOMAINS)):
        raise ValueError('Only public YouTube HTTPS destinations are allowed')
    return host


def destination(authority):
    host = authority_host(authority)
    answers = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    addresses = [entry[4][0] for entry in answers]
    if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
        raise ValueError('Private network destinations are not allowed')
    # Connect to this exact IP, rather than resolving the name a second time.
    return addresses[0], 443


class ConnectHandler(socketserver.StreamRequestHandler):
    def handle(self):
        if not self.server.slots.acquire(blocking=False):
            return
        upstream = None
        try:
            self.connection.settimeout(15)
            line = self.rfile.readline(8193)
            if len(line) > 8192:
                raise ValueError('Request too large')
            method, authority, version = line.decode('ascii').strip().split(' ')
            if method != 'CONNECT' or version not in {'HTTP/1.0', 'HTTP/1.1'}:
                raise ValueError('CONNECT required')
            total = len(line)
            while True:
                header = self.rfile.readline(8193)
                total += len(header)
                if total > 16384 or not header:
                    raise ValueError('Invalid headers')
                if header in (b'\r\n', b'\n'):
                    break
            upstream = self.server.open_tunnel(authority)
            self.connection.sendall(b'HTTP/1.1 200 Connection Established\r\n\r\n')
            self.connection.settimeout(30)
            upstream.settimeout(30)
            while True:
                pending = getattr(upstream, 'pending', lambda: 0)() > 0
                ready, _, _ = select.select([self.connection, upstream], [], [], 0 if pending else 90)
                if pending and upstream not in ready:
                    ready.append(upstream)
                if not ready:
                    break
                for source in ready:
                    data = source.recv(65536)
                    if not data:
                        return
                    (upstream if source is self.connection else self.connection).sendall(data)
        except (OSError, ValueError, UnicodeError):
            if upstream is None:
                try:
                    self.connection.sendall(b'HTTP/1.1 502 Proxy destination unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
                except OSError:
                    pass
        finally:
            if upstream is not None:
                upstream.close()
            self.server.slots.release()


class ProxyServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    request_queue_size = 64

    def __init__(self, port, open_tunnel=None):
        self.slots = threading.BoundedSemaphore(64)
        self.open_tunnel = open_tunnel or (lambda authority: socket.create_connection(destination(authority), timeout=15))
        super().__init__(('127.0.0.1', port), ConnectHandler)


def ssh_command(config, directory, port):
    host = config['ssh_host']
    bind = config['remote_bind']
    user = config['ssh_user']
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{0,252}', host):
        raise ValueError('Invalid SSH host')
    if user != 'supoclip-relay' or not ipaddress.ip_address(bind).is_private or ipaddress.ip_address(bind).is_unspecified or ':' in bind:
        raise ValueError('Invalid tunnel configuration')
    if type(config['ssh_port']) is not int or not 1 <= config['ssh_port'] <= 65535:
        raise ValueError('Invalid SSH port')
    for value in (config['remote_port'], port):
        if type(value) is not int or not 1024 <= value <= 65535:
            raise ValueError('Invalid tunnel port')
    # OpenSSH parses -o values again as ssh_config syntax. Without these
    # quotes, macOS's "Application Support" becomes several known-hosts files.
    known_hosts = str(directory / 'known_hosts').replace('\\', '\\\\').replace('"', '\\"')
    return [
        '/usr/bin/ssh', '-F', '/dev/null', '-NT', '-i', str(directory / 'id_ed25519'),
        '-o', 'IdentitiesOnly=yes', '-o', 'IdentityAgent=none', '-o', 'BatchMode=yes',
        '-o', 'StrictHostKeyChecking=yes', '-o', 'UserKnownHostsFile="' + known_hosts + '"',
        '-o', 'ExitOnForwardFailure=yes', '-o', 'ConnectTimeout=15',
        '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=3', '-o', 'Compression=no',
        '-R', f'{bind}:{config["remote_port"]}:127.0.0.1:{port}',
        '-p', str(config['ssh_port']), user + '@' + host,
    ]


def known_hosts_entry(config):
    host = config['ssh_host'] if config['ssh_port'] == 22 else f"[{config['ssh_host']}]:{config['ssh_port']}"
    return host + ' ' + ' '.join(config['ssh_host_key'].split()[:2]) + '\n'


def restart_login_service(plist):
    """Wait for asynchronous launchd removal before loading a replacement."""
    label = 'io.supoclip.home-proxy'
    domain = f'gui/{os.getuid()}'
    service = domain + '/' + label
    subprocess.run(['/bin/launchctl', 'bootout', service],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(150):
        state = subprocess.run(['/bin/launchctl', 'print', service],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if state.returncode != 0:
            break
        time.sleep(0.1)
    else:
        raise RuntimeError('The previous home connection is still stopping. Try setup again.')
    subprocess.run(['/bin/launchctl', 'bootstrap', domain, str(plist)], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    subprocess.run(['/bin/launchctl', 'kickstart', service], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path)
    parser.add_argument('--proxy-only', type=int, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.proxy_only:
        with ProxyServer(args.proxy_only) as server:
            server.serve_forever()
        return
    if not args.config:
        parser.error('--config is required')
    directory = args.config.resolve().parent
    config = json.loads(args.config.read_text())
    with ProxyServer(0) as server:
        command = ssh_command(config, directory, server.server_address[1])
        threading.Thread(target=server.serve_forever, daemon=True).start()
        stopping = threading.Event()
        child = None

        def stop(*_):
            stopping.set()
            if child is not None and child.poll() is None:
                child.terminate()

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        delay = 2
        while not stopping.is_set():
            started = time.monotonic()
            child = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            child.wait()
            # No host addresses, URLs, credentials or SSH diagnostic bodies in logs.
            if stopping.is_set():
                break
            print('Home connection interrupted; reconnecting.', flush=True)
            if time.monotonic() - started > 60:
                delay = 2
            stopping.wait(delay)
            delay = min(60, delay * 2)


if __name__ == '__main__':
    main()
