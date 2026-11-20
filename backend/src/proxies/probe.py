"""Bounded metadata check. The isolated child receives credentials on stdin."""
import json
from pathlib import Path
import sys


def probe(url, proxy):
    import yt_dlp
    class Silent:
        def debug(self, *_): pass
        def warning(self, *_): pass
        def error(self, *_): pass
    options = {'proxy': proxy, 'quiet': True, 'no_warnings': True, 'logger': Silent(),
               'skip_download': True, 'socket_timeout': 10, 'retries': 0,
               'extractor_retries': 0, 'noplaylist': True, 'cachedir': False}
    try:
        with yt_dlp.YoutubeDL(options) as downloader:
            data = downloader.extract_info(url, download=False)
        return {'ok': bool(data and data.get('formats')), 'reason': 'reachable' if data and data.get('formats') else 'source_unavailable'}
    except Exception as exc:
        message = str(exc).lower()
        if 'not a bot' in message:
            reason = 'access'
        elif '407' in message or 'proxy authentication' in message or ('socks' in message and 'authentication' in message):
            reason = 'authentication'
        elif any(term in message for term in ('timed out', 'connection refused', 'connection reset', 'unable to connect',
                   'tunnel connection failed', 'name or service not known', 'certificate verify failed',
                   'http error 502', 'http error 503', 'http error 504', 'http error 429')):
            reason = 'transport'
        else:
            reason = 'source_unavailable'
        return {'ok': False, 'reason': reason}


async def check(url, proxy):
    from ..recording.capture import _read_json_command
    try:
        code, data = await _read_json_command([sys.executable, str(Path(__file__).resolve())], 20,
            input_data=json.dumps({'url': url, 'proxy': proxy}).encode())
    except (OSError, ValueError, TimeoutError):
        return {'ok': False, 'reason': 'transport'}
    if code != 0 or not isinstance(data, dict) or type(data.get('ok')) is not bool or data.get('reason') not in {
            'reachable', 'access', 'authentication', 'transport', 'source_unavailable'}:
        return {'ok': False, 'reason': 'source_unavailable'}
    return {'ok': data['ok'], 'reason': data['reason']}


if __name__ == '__main__':
    try:
        payload = json.loads(sys.stdin.buffer.read(8193))
        result = probe(payload['url'], payload['proxy'])
    except Exception:
        result = {'ok': False, 'reason': 'source_unavailable'}
    print(json.dumps(result))
