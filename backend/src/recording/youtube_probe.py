"""Credential-isolated yt-dlp probe; emit only a tiny sanitized result."""
import json
import sys
import yt_dlp


def probe(url, proxy=''):
    options = {'quiet': True, 'no_warnings': True, 'skip_download': True,
               'socket_timeout': 15, 'retries': 0, 'extractor_retries': 0,
               'noplaylist': True, 'cachedir': False}
    if proxy:
        options['proxy'] = proxy
    try:
        with yt_dlp.YoutubeDL(options) as downloader:
            data = downloader.extract_info(url, download=False)
        if data and data.get('live_status') == 'is_live' and data.get('formats'):
            return {'streams': {'best': {}}}
        if data and data.get('live_status') in {'not_live', 'was_live', 'post_live', 'is_upcoming'}:
            return {'error': 'The channel is offline'}
        return {'detail': 'youtube_probe_unavailable'}
    except Exception as exc:
        message = str(exc).lower()
        if any(term in message for term in ('not currently live', 'is not live', 'channel is offline')):
            return {'error': 'The channel is offline'}
        if 'not a bot' in message:
            return {'detail': 'youtube_access_blocked'}
        transport = ('timed out', 'connection refused', 'connection reset', 'proxy error',
                     'tunnel connection failed', 'proxy authentication', 'http error 407',
                     'http error 502', 'http error 503', 'http error 504', 'http error 429',
                     'unable to connect', 'failed to resolve', 'name or service not known')
        return {'detail': 'youtube_transport_failed' if any(term in message for term in transport) else 'youtube_probe_unavailable'}


if __name__ == '__main__':
    print(json.dumps(probe(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else '')))
