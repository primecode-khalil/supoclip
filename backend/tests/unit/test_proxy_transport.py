"""Live ffmpeg receives a local HTTP proxy while the real upstream stays private."""
import base64
from contextlib import contextmanager
import socket
import socketserver
import ssl
import struct
import threading
from urllib.parse import urlsplit

import pytest


class EchoHTTPProxy(socketserver.StreamRequestHandler):
    def handle(self):
        request = self.rfile.readline().decode().strip()
        headers = {}
        while line := self.rfile.readline():
            if line == b'\r\n':
                break
            key, value = line.decode().split(':', 1)
            headers[key.lower()] = value.strip()
        self.server.requests.append((request, headers))
        self.wfile.write(b'HTTP/1.1 200 Connection Established\r\n\r\n')
        self.wfile.flush()
        while data := self.connection.recv(4096):
            self.connection.sendall(data)


class EchoSOCKSProxy(socketserver.StreamRequestHandler):
    def handle(self):
        version, count = self.rfile.read(2)
        methods = self.rfile.read(count)
        assert version == 5
        self.wfile.write(b'\x05\x02'); self.wfile.flush()
        version, length = self.rfile.read(2)
        username = self.rfile.read(length)
        password = self.rfile.read(self.rfile.read(1)[0])
        self.server.credentials.append((username, password))
        self.wfile.write(b'\x01\x00'); self.wfile.flush()
        version, command, reserved, kind = self.rfile.read(4)
        if kind == 3:
            address = self.rfile.read(self.rfile.read(1)[0]).decode()
        else:
            address = socket.inet_ntoa(self.rfile.read(4))
        port = struct.unpack('!H', self.rfile.read(2))[0]
        self.server.requests.append((address, port))
        self.wfile.write(b'\x05\x00\x00\x01\x7f\x00\x00\x01\x00\x00'); self.wfile.flush()
        while data := self.connection.recv(4096):
            self.connection.sendall(data)


@contextmanager
def server(handler, tls=None):
    class Server(socketserver.ThreadingTCPServer):
        daemon_threads = True
    with Server(('127.0.0.1', 0), handler) as instance:
        if tls:
            instance.socket = tls.wrap_socket(instance.socket, server_side=True)
        instance.requests, instance.credentials = [], []
        thread = threading.Thread(target=instance.serve_forever, kwargs={'poll_interval': 0.02}, daemon=True)
        thread.start()
        try:
            yield instance
        finally:
            instance.shutdown()
            thread.join(timeout=1)


def connect(address, authority='www.youtube.com:443'):
    proxy = urlsplit(address)
    client = socket.create_connection((proxy.hostname, proxy.port), timeout=3)
    client.sendall(f'CONNECT {authority} HTTP/1.1\r\nHost: {authority}\r\n\r\n'.encode())
    response = bytearray()
    while not response.endswith(b'\r\n\r\n'):
        byte = client.recv(1)
        assert byte, 'Gateway closed without a complete response'
        response.extend(byte)
    return client, bytes(response)


def test_authenticated_http_proxy_uses_a_local_gateway_without_disclosing_upstream_credentials():
    from src.proxies.transport import live_gateway
    with server(EchoHTTPProxy) as upstream:
        with live_gateway(f'http://user:p%40ss@127.0.0.1:{upstream.server_address[1]}') as address:
            assert address.startswith('http://127.0.0.1:') and 'user' not in address and 'p%40ss' not in address
            client, response = connect(address)
            with client:
                assert b' 200 ' in response
                client.sendall(b'video and audio bytes')
                assert client.recv(4096) == b'video and audio bytes'
            request, headers = upstream.requests[0]
            assert request == 'CONNECT www.youtube.com:443 HTTP/1.1'
            assert headers['proxy-authorization'] == 'Basic ' + base64.b64encode(b'user:p@ss').decode()
        closed = urlsplit(address)
        with pytest.raises(OSError):
            socket.create_connection((closed.hostname, closed.port), timeout=0.2)


def test_socks5h_preserves_remote_dns_and_carries_authentication():
    from src.proxies.transport import live_gateway
    with server(EchoSOCKSProxy) as upstream:
        with live_gateway(f'socks5h://user:password@127.0.0.1:{upstream.server_address[1]}') as address:
            client, response = connect(address)
            with client:
                assert b' 200 ' in response
                client.sendall(b'live bytes')
                assert client.recv(4096) == b'live bytes'
            assert upstream.requests == [('www.youtube.com', 443)]
            assert upstream.credentials == [(b'user', b'password')]


@pytest.mark.parametrize('authority', ['127.0.0.1:443', 'www.youtube.com.attacker.example:443', 'www.youtube.com:80'])
def test_adapter_rejects_non_youtube_destinations_without_contacting_the_upstream(authority):
    from src.proxies.transport import live_gateway
    with server(EchoHTTPProxy) as upstream:
        with live_gateway(f'http://user:password@127.0.0.1:{upstream.server_address[1]}') as address:
            client, response = connect(address, authority)
            client.close()
            assert b' 502 ' in response
            assert upstream.requests == []


def test_plain_home_http_connection_needs_no_extra_gateway():
    from src.proxies.transport import live_gateway
    with live_gateway('http://172.19.0.1:18888') as address:
        assert address == 'http://172.19.0.1:18888'


@pytest.fixture
def tls_proxy(tmp_path):
    from datetime import datetime, timedelta, timezone
    import ipaddress
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, 'localhost')])
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(datetime.now(timezone.utc) - timedelta(minutes=1))
            .not_valid_after(datetime.now(timezone.utc) + timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost'), x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]), critical=False)
            .sign(key, hashes.SHA256()))
    cert_path, key_path = tmp_path / 'certificate.pem', tmp_path / 'key.pem'
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_path, key_path)
    return context, cert_path


def test_https_proxy_uses_validated_tls_and_preserves_large_tunnel_payloads(tls_proxy, monkeypatch):
    from src.proxies import transport
    tls, cert = tls_proxy
    trust = ssl.create_default_context(cafile=str(cert))
    monkeypatch.setattr(transport.ssl, 'create_default_context', lambda: trust)
    with server(EchoHTTPProxy, tls=tls) as upstream:
        with transport.live_gateway(f'https://user:password@127.0.0.1:{upstream.server_address[1]}') as address:
            client, response = connect(address)
            with client:
                assert b' 200 ' in response
                payload = b'frame bytes' * 12000
                client.sendall(payload)
                received = bytearray()
                while len(received) < len(payload):
                    received.extend(client.recv(65536))
                assert received == payload


def test_https_proxy_does_not_ignore_an_untrusted_certificate(tls_proxy):
    from src.proxies.transport import live_gateway
    tls, _ = tls_proxy
    with server(EchoHTTPProxy, tls=tls) as upstream:
        with live_gateway(f'https://user:password@127.0.0.1:{upstream.server_address[1]}') as address:
            client, response = connect(address)
            client.close()
            assert b' 502 ' in response and upstream.requests == []


async def test_cancelling_a_gateway_owner_closes_its_listener():
    import asyncio
    from src.proxies.transport import async_gateway
    entered = asyncio.Event()
    address = []
    async def owner():
        async with async_gateway('http://user:password@127.0.0.1:12345') as url:
            address.append(url)
            entered.set()
            await asyncio.Future()
    task = asyncio.create_task(owner())
    await entered.wait()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    endpoint = urlsplit(address[0])
    with pytest.raises(OSError):
        socket.create_connection((endpoint.hostname, endpoint.port), timeout=0.2)
