"""An admin can save useful proxy templates without leaking credential values."""
import pytest


@pytest.mark.parametrize('url', [
    'http://user:secret@proxy.example:8000',
    'https://user-country-{country}-session-{session}:secret@proxy.example:443',
    'socks5h://proxy.example:1080', 'http://172.19.0.1:18888',
])
def test_proxy_urls_accept_supported_transports_and_templates(url):
    from src.proxies.models import validate_proxy_url
    assert validate_proxy_url('  ' + url + '  ') == url


@pytest.mark.parametrize('url', [
    'file:///etc/passwd', 'http://', 'http://proxy:0', 'http://proxy:65536',
    'http://proxy/path', 'http://proxy?secret=yes', 'http://proxy#fragment',
    'http://proxy\nInjected: x', 'http://proxy-{unknown}:80', 'http://proxy:bad',
])
def test_invalid_proxy_input_returns_a_message_without_the_url(url):
    from src.proxies.models import validate_proxy_url
    with pytest.raises(ValueError) as error:
        validate_proxy_url(url)
    assert url not in str(error.value)


def test_connection_presentation_and_repr_do_not_expose_credentials():
    from src.proxies.models import Connection
    connection = Connection(id='test', name='Home backup', url='http://user:supersecret@proxy.example:8000',
                            usage='both', priority=0, revision='revision')
    public = connection.public()
    assert public['endpoint'] == 'proxy.example:8000'
    assert public['has_credentials'] is True
    assert public['usage'] == 'both'
    assert all(value not in str(public) + repr(connection) for value in ['supersecret', 'http://user:'])


def test_purposes_are_filtered_and_ties_have_a_stable_order():
    from src.proxies.models import Connection, Registry
    rows = [Connection(id=i, name=i, url='http://proxy:80', usage=usage, priority=priority,
                       enabled=enabled, revision='v1') for i, usage, priority, enabled in [
        ('c', 'both', 1, True), ('b', 'live', 0, True), ('a', 'imports', 1, True),
        ('d', 'both', -1, False)]]
    registry = Registry(connections=tuple(rows))
    assert [c.id for c in registry.assigned('imports')] == ['a', 'c']
    assert [c.id for c in registry.assigned('live')] == ['b', 'c']


def test_bad_saved_configuration_is_fail_closed_instead_of_legacy_routing():
    from src.proxies.models import Registry
    assert Registry.decode(None) is None
    registry = Registry.decode('broken encrypted registry payload')
    assert registry.unavailable is True
    assert registry.required('imports') and registry.required('live')
    assert Registry.decode('{"schema_version":1,"connections":[]}').required('imports') is False
