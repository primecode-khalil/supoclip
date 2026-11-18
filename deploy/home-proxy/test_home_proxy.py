import importlib.util
from pathlib import Path
import socket
import shlex
import pytest


def module():
    spec = importlib.util.spec_from_file_location('home_proxy', Path(__file__).resolve().parents[2] / 'backend/src/home_proxy_assets/helper.py')
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


@pytest.mark.parametrize('value', ['localhost:443','127.0.0.1:443','youtube.com.evil.test:443','youtube.com:22','user@youtube.com:443','youtube.com:443/path','[::1]:443','googlevideo.com:80','youtube.com:443?x=1'])
def test_rejects_non_youtube_authorities(value):
    with pytest.raises(ValueError): module().destination(value)


def test_pins_public_resolved_address(monkeypatch):
    m=module()
    monkeypatch.setattr(m.socket,'getaddrinfo',lambda *a, **kw: [(socket.AF_INET,socket.SOCK_STREAM,6,'',('142.250.1.1',443))])
    assert m.destination('WWW.YouTube.com:443') == ('142.250.1.1',443)


@pytest.mark.parametrize('ip',['127.0.0.1','192.168.1.2','169.254.169.254','100.64.0.1','::1','fc00::1'])
def test_rejects_private_dns_answers(monkeypatch,ip):
    m=module()
    monkeypatch.setattr(m.socket,'getaddrinfo',lambda *a, **kw: [(socket.AF_INET,socket.SOCK_STREAM,6,'',(ip,443))])
    with pytest.raises(ValueError): m.destination('www.youtube.com:443')


def test_ssh_pins_identity_and_host_and_private_forward(tmp_path):
    m=module()
    c={'ssh_host':'server.example.com','ssh_port':2222,'ssh_user':'supoclip-relay','remote_bind':'172.19.0.1','remote_port':18888}
    argv=m.ssh_command(c,tmp_path,19891)
    assert 'StrictHostKeyChecking=yes' in argv
    assert 'IdentitiesOnly=yes' in argv
    assert 'IdentityAgent=none' in argv
    assert '172.19.0.1:18888:127.0.0.1:19891' in argv
    assert '-NT' in argv
    assert 'BatchMode=yes' in argv
    assert 'Compression=no' in argv


@pytest.mark.parametrize('folder', ['Application Support/SupoClip Home Proxy', 'Mac "personal" files', r'Mac\files'])
def test_known_hosts_path_remains_one_openssh_filename(tmp_path, folder):
    directory = tmp_path / folder
    config = {'ssh_host': 'server.example.com', 'ssh_port': 2222, 'ssh_user': 'supoclip-relay', 'remote_bind': '172.19.0.1', 'remote_port': 18888}
    argv = module().ssh_command(config, directory, 19891)
    option = next(value for value in argv if value.startswith('UserKnownHostsFile='))
    # OpenSSH parses this option's value as a list of filenames, even when
    # subprocess receives the entire -o value as a single argv element.
    assert shlex.split(option.split('=', 1)[1]) == [str(directory / 'known_hosts')]


@pytest.mark.parametrize('field,value',[('remote_bind','0.0.0.0'),('ssh_host','-oProxyCommand=bad'),('ssh_port',0),('ssh_user','root'),('remote_port',22)])
def test_rejects_dangerous_descriptor(tmp_path,field,value):
    c={'ssh_host':'server.example.com','ssh_port':2222,'ssh_user':'supoclip-relay','remote_bind':'172.19.0.1','remote_port':18888}
    c[field]=value
    with pytest.raises(ValueError): module().ssh_command(c,tmp_path,19891)

@pytest.mark.parametrize('port,expected',[(22,'server.example.com'),(2222,'[server.example.com]:2222')])
def test_known_hosts_uses_openssh_standard_port_rules(port,expected):
    m=module()
    assert m.known_hosts_entry({'ssh_host':'server.example.com','ssh_port':port,'ssh_host_key':'ssh-ed25519 AAAA comment'}) == expected+' ssh-ed25519 AAAA\n'


def controller():
    spec=importlib.util.spec_from_file_location('home_proxy_controller',Path(__file__).with_name('controller.py'))
    obj=importlib.util.module_from_spec(spec);spec.loader.exec_module(obj);return obj


def test_controller_only_emits_constrained_authorized_key():
    import base64
    key='ssh-ed25519 '+base64.b64encode(b'\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20'+bytes(32)).decode()
    line=controller().authorized_key(key,'172.19.0.1',18888)
    assert line.startswith('restrict,port-forwarding,permitlisten="172.19.0.1:18888",command="/bin/false" ')
    assert line.endswith(key+'\n')


@pytest.mark.parametrize('key',['command="evil" ssh-ed25519 AAAA','ssh-rsa AAAA','ssh-ed25519 AAAA','ssh-ed25519 AAAA\nssh-ed25519 BBBB'])
def test_controller_rejects_options_and_extra_keys(key):
    with pytest.raises(ValueError):
        controller().authorized_key(key,'172.19.0.1',18888)
