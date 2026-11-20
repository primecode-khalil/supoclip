"""Live tracks must retain their shared clock through yt-dlp and segmentation."""
import asyncio
import json
import shutil
import subprocess
import sys

import numpy as np
import pytest
import yt_dlp
from yt_dlp.downloader.external import FFmpegFD

from src.recording import capture


def ffmpeg(*args):
    return subprocess.run(
        ['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-y', *map(str, args)],
        check=True, capture_output=True, timeout=30,
    ).stdout


@pytest.mark.parametrize('audio_start_delay,sample_rate,fps', [(0.0, 48000, 30), (1.5, 44100, 30), (2.0, 44100, 60)])
async def test_live_capture_keeps_flash_and_beep_synchronized(tmp_path, monkeypatch, audio_start_delay, sample_rate, fps):
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        pytest.skip('FFmpeg is required for the live-clock regression')
    # Both events occur at absolute source-clock t=14. Live audio is opened
    # later than video, as happens when their HLS playlists advance separately.
    video, audio = tmp_path / 'video.ts', tmp_path / 'audio.ts'
    ffmpeg('-copyts', '-f', 'lavfi', '-i',
           f"color=c=black:s=160x90:r={fps}:d=8,drawbox=color=white:t=fill:enable='between(t,4,4.2)',setpts=PTS+10/TB",
           '-an', '-c:v', 'libx264', '-preset', 'ultrafast', '-bf', '0', '-g', str(fps),
           '-fps_mode', 'passthrough', '-mpegts_copyts', '1', '-muxdelay', '0', video)
    beep = 4 - audio_start_delay
    ffmpeg('-copyts', '-f', 'lavfi', '-i',
           f'aevalsrc=if(between(t\\,{beep}\\,{beep + .2})\\,sin(2*PI*1000*t)\\,0):s={sample_rate}:d=8,asetpts=PTS+{10 + audio_start_delay}/TB',
           '-vn', '-c:a', 'aac', '-mpegts_copyts', '1', '-muxdelay', '0', audio)

    monkeypatch.setattr(capture, 'youtube_proxy', lambda: '')
    # Parse the production CLI and use the real yt-dlp FFmpeg merger, with
    # finite local tracks in place of the network. No API or live site is used.
    options = yt_dlp.parse_options(capture.youtube_command('https://www.youtube.com/@demo/live', '480p')[3:]).ydl_opts
    merged = tmp_path / 'merged.ts'
    info = {'url': str(video), 'ext': 'mp4', 'protocol': 'm3u8_native', 'is_live': True,
            'requested_formats': [{'url': str(p), 'protocol': 'm3u8_native', 'manifest_stream_number': 0}
                                  for p in [video, audio]]}
    with yt_dlp.YoutubeDL(options) as downloader:
        assert FFmpegFD(downloader, options)._call_downloader(str(merged), info) == 0

    def recorded_input(url, quality, *, proxy_url=None):
        assert proxy_url == ''  # This regression uses local media, never a network route.
        return [sys.executable, '-c',
                'import pathlib,sys;sys.stdout.buffer.write(pathlib.Path(sys.argv[1]).read_bytes())', str(merged)]
    monkeypatch.setattr(capture, 'youtube_command', recorded_input)
    process = capture.CaptureProcess(tmp_path / 'segments', 'https://www.youtube.com/@demo/live', segment_seconds=60)
    await process.start()
    try:
        async with asyncio.timeout(15):
            while process.running:
                await asyncio.sleep(.02)
    finally:
        await process.stop()
    segments = await process.poll()
    assert len(segments) == 1
    path = segments[0].path
    media = json.loads(subprocess.check_output([
        'ffprobe', '-v', 'error', '-show_entries', 'stream=codec_type,start_time', '-of', 'json', str(path),
    ]))
    starts = {s['codec_type']: float(s['start_time']) for s in media['streams']}
    frames = np.frombuffer(ffmpeg('-i', path, '-an', '-vf', 'scale=16:9,format=gray',
                                 '-fps_mode', 'passthrough', '-f', 'rawvideo', '-'), np.uint8).reshape(-1, 144)
    samples = np.frombuffer(ffmpeg('-i', path, '-vn', '-ac', '1', '-ar', '48000', '-f', 'f32le', '-'), np.float32)
    flash = np.flatnonzero(frames.mean(axis=1) > 150)[0] / fps + starts['video']
    sound = np.flatnonzero(np.abs(samples) > .3)[0] / 48000 + starts['audio']
    assert abs(flash - sound) < .05, f'Audio leads the visual event by {flash - sound:.3f}s'
    # ASR and clip selection use the file's zero origin too. Pad the missing
    # initial audio instead of moving its content earlier to fill that gap.
    assert abs(starts['audio'] - starts['video']) < .05
