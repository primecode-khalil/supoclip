"""Expose credentialed/TLS/SOCKS routes to ffmpeg as a private HTTP CONNECT hop."""
from __future__ import annotations

import asyncio
import base64
from contextlib import asynccontextmanager, contextmanager
import socket
import ssl
import threading
import time
from urllib.parse import unquote, urlsplit

from ..home_proxy_assets.helper import ProxyServer, authority_host
from .models import SCHEMES, validate_proxy_url


def open_upstream(proxy: str, authority: str):
    host = authority_host(authority)
    parsed = urlsplit(proxy)
    port = parsed.port or SCHEMES[parsed.scheme]
    username = unquote(parsed.username) if parsed.username is not None else None
    password = unquote(parsed.password or '') if username is not None else None
    connection = None
    deadline = time.monotonic() + 15
    try:
        if parsed.scheme.startswith('socks5'):
            # Vendored by the locked yt-dlp package; no extra dependency/runtime.
            from yt_dlp.socks import ProxyType, sockssocket
            families = dict.fromkeys(row[0] for row in socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM))
            for family in families:
                connection = sockssocket(family)
                connection.settimeout(max(0.1, deadline - time.monotonic()))
                connection.setproxy(ProxyType.SOCKS5, parsed.hostname, port,
                                    rdns=parsed.scheme == 'socks5h', username=username, password=password)
                try:
                    connection.connect((host, 443))
                    return connection
                except OSError:
                    connection.close()
                    connection = None
                    if time.monotonic() >= deadline:
                        raise
            raise ConnectionError('Proxy connection failed')
        connection = socket.create_connection((parsed.hostname, port), timeout=15)
        connection.settimeout(max(0.1, deadline - time.monotonic()))
        if parsed.scheme == 'https':
            connection = ssl.create_default_context().wrap_socket(connection, server_hostname=parsed.hostname)
        headers = [f'CONNECT {host}:443 HTTP/1.1', f'Host: {host}:443']
        if username is not None:
            credential = base64.b64encode(f'{username}:{password}'.encode()).decode()
            headers.append('Proxy-Authorization: Basic ' + credential)
        connection.settimeout(max(0.1, deadline - time.monotonic()))
        connection.sendall(('\r\n'.join(headers) + '\r\n\r\n').encode('ascii'))
        response = bytearray()
        while not response.endswith(b'\r\n\r\n'):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError
            connection.settimeout(remaining)
            byte = connection.recv(1)
            if not byte or len(response) >= 16384:
                raise ConnectionError('Proxy handshake failed')
            response.extend(byte)
        fields = response.split(b'\r\n', 1)[0].split()
        if len(fields) < 2 or fields[1] != b'200':
            raise ConnectionError('Proxy handshake was rejected')
        return connection
    except (OSError, ValueError):
        if connection is not None:
            connection.close()
        # No proxy diagnostics/userinfo in parent logs or child errors.
        raise ConnectionError('Proxy connection or authentication failed') from None


@contextmanager
def live_gateway(proxy: str):
    if not proxy:
        yield ''
        return
    proxy = validate_proxy_url(proxy)
    parsed = urlsplit(proxy)
    if parsed.scheme == 'http' and parsed.username is None:
        yield proxy  # The current Mac tunnel already provides the correct hop.
        return
    with ProxyServer(0, open_tunnel=lambda authority: open_upstream(proxy, authority)) as server:
        thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.05}, daemon=True)
        thread.start()
        try:
            yield f'http://127.0.0.1:{server.server_address[1]}'
        finally:
            server.shutdown()
            thread.join(timeout=1)


@asynccontextmanager
async def async_gateway(proxy: str):
    context = live_gateway(proxy)
    # Enter only binds loopback/starts a thread; no network/DNS operation here.
    # Keeping allocation atomic avoids a listener orphaned by cancellation.
    address = context.__enter__()
    try:
        yield address
    finally:
        closing = asyncio.create_task(asyncio.to_thread(context.__exit__, None, None, None))
        try:
            await asyncio.shield(closing)
        except asyncio.CancelledError:
            await closing
            raise
