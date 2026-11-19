from datetime import datetime, timezone
from pathlib import Path
import shutil
import subprocess

import pytest

from src.services.social_publication_policy import SchedulePattern, next_publication_time, local_publication_time, validate_youtube_short

UTC = timezone.utc


def test_six_hour_intervals_retain_their_anchor():
    pattern = SchedulePattern(kind="interval", interval_minutes=360, anchor_at="2026-11-20T00:00:00Z")
    assert next_publication_time(pattern, "Europe/Bucharest", datetime(2026, 11, 20, 0, 15, tzinfo=UTC)) == datetime(2026, 11, 20, 6, tzinfo=UTC)
    assert next_publication_time(pattern, "UTC", datetime(2026, 11, 20, 12, tzinfo=UTC)) == datetime(2026, 11, 20, 12, tzinfo=UTC)


def test_weekly_times_follow_local_clock_and_weekdays():
    pattern = SchedulePattern(kind="weekly", weekdays=[0, 4], times=["09:00", "15:00"])
    assert next_publication_time(pattern, "Europe/Bucharest", datetime(2026, 11, 20, 9, tzinfo=UTC)) == datetime(2026, 11, 20, 13, tzinfo=UTC)
    assert next_publication_time(pattern, "Europe/Bucharest", datetime(2026, 11, 20, 16, tzinfo=UTC)) == datetime(2026, 11, 23, 7, tzinfo=UTC)


def test_nonexistent_weekly_time_is_skipped_on_spring_transition():
    pattern = SchedulePattern(kind="weekly", weekdays=[6], times=["03:30"])
    assert next_publication_time(pattern, "Europe/Bucharest", datetime(2026, 3, 28, 22, tzinfo=UTC)) == datetime(2026, 4, 5, 0, 30, tzinfo=UTC)


def test_ambiguous_weekly_time_is_used_once_on_autumn_transition():
    pattern = SchedulePattern(kind="weekly", weekdays=[6], times=["03:30"])
    assert next_publication_time(pattern, "Europe/Bucharest", datetime(2026, 10, 24, 23, tzinfo=UTC)) == datetime(2026, 10, 25, 0, 30, tzinfo=UTC)
    assert next_publication_time(pattern, "Europe/Bucharest", datetime(2026, 10, 25, 0, 31, tzinfo=UTC)) == datetime(2026, 11, 1, 1, 30, tzinfo=UTC)


def test_custom_time_is_explicitly_local_and_cannot_be_past_or_nonexistent():
    now = datetime(2026, 11, 20, 6, tzinfo=UTC)
    assert local_publication_time("2026-11-20T12:00", "Europe/Bucharest", now) == datetime(2026, 11, 20, 10, tzinfo=UTC)
    with pytest.raises(ValueError):
        local_publication_time("2026-11-20T07:00", "Europe/Bucharest", now)
    with pytest.raises(ValueError):
        local_publication_time("2026-03-29T03:30", "Europe/Bucharest", datetime(2026, 3, 28, tzinfo=UTC))


@pytest.mark.parametrize("settings", [{"interval_minutes": 0}, {"kind": "weekly", "times": []},
    {"kind": "weekly", "weekdays": []}, {"times": ["25:00"]}, {"weekdays": [7]}, {"times": ["09:00", "09:00"]}])
def test_invalid_patterns_are_rejected(settings):
    with pytest.raises(ValueError):
        SchedulePattern(**settings)


@pytest.fixture
def short_file(tmp_path):
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg is required for media validation")

    def make(*, vertical=True, audio=True, duration=1):
        path = tmp_path / f"{vertical}-{audio}-{duration}.mp4"
        cmd = ["ffmpeg", "-v", "error", "-nostdin", "-y", "-f", "lavfi", "-i", f"color=c=blue:s={'90x160' if vertical else '160x90'}:r=1"]
        if audio:
            cmd += ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=16000"]
        cmd += ["-t", str(duration), "-c:v", "libx264", "-threads", "1", "-preset", "ultrafast"]
        if audio:
            cmd += ["-c:a", "aac"]
        subprocess.run([*cmd, str(path)], check=True, capture_output=True)
        return str(path)

    return make


def test_approved_short_must_be_playable_vertical_with_audio(short_file, tmp_path):
    validate_youtube_short(short_file())
    for path in [short_file(vertical=False), short_file(audio=False), short_file(duration=181)]:
        with pytest.raises(ValueError):
            validate_youtube_short(path)
    broken = tmp_path / "broken.mp4"
    broken.write_bytes(b"invalid video")
    with pytest.raises(ValueError):
        validate_youtube_short(str(broken))
