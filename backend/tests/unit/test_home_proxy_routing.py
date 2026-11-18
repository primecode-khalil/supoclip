from unittest.mock import AsyncMock, MagicMock

async def test_paired_route_wins_even_when_tunnel_offline(monkeypatch):
    from src import home_proxy
    from src.config import Config
    monkeypatch.setenv('HOME_PROXY_URL','http://172.19.0.1:18888')
    db=AsyncMock()
    result=MagicMock()
    db.execute.return_value=result
    result.scalar_one.return_value=True
    await home_proxy.refresh_home_proxy(db)
    assert Config().youtube_proxy_url=='http://172.19.0.1:18888'
    result.scalar_one.return_value=False
    await home_proxy.refresh_home_proxy(db)
    assert Config().youtube_proxy_url!='http://172.19.0.1:18888'


def test_youtube_commands_use_proxy_for_lookup_and_capture(monkeypatch):
    from src.recording import capture
    monkeypatch.setattr(capture,'youtube_proxy',lambda:'http://172.19.0.1:18888')
    args=capture.youtube_command('https://www.youtube.com/@demo/live','720p,best')
    assert '--proxy' in args and 'http://172.19.0.1:18888' in args
    assert 'bv[height<=720]+ba/b[height<=720]' in args
    assert args[-2:] == ['-o','-']


def test_live_without_playable_formats_is_unknown(monkeypatch):
    from src.recording import youtube_probe
    from unittest.mock import MagicMock
    downloader=MagicMock()
    downloader.__enter__.return_value.extract_info.return_value={'live_status':'is_live','formats':[]}
    monkeypatch.setattr(youtube_probe.yt_dlp,'YoutubeDL',lambda options:downloader)
    assert youtube_probe.probe('https://www.youtube.com/@demo/live') == {'detail':'youtube_probe_unavailable'}
