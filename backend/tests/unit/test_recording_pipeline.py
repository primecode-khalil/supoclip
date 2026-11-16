"""Autonomous decisions must be deterministic and conservative."""
from pathlib import Path

import pytest
import httpx

from src.recording.pipeline import NativeClient, PipelineBlocked, choose_clips, contained_path, retry_delay, overlaps_reserved


def clip(identity, start, end, score):
    return {"id": identity, "start_time": start, "end_time": end, "virality_score": score}


def test_candidate_selection_discards_repeated_overlap_and_low_scores():
    clips = [clip("repeat", "00:10", "00:50", 99), clip("boundary", "00:50", "01:20", 90), clip("dud", "02:00", "02:30", 50)]
    assert [c["id"] for c in choose_clips(clips, overlap=60, min_score=75, limit=3)] == ["boundary"]


def test_overlapping_candidates_are_deduplicated_by_best_score():
    clips = [clip("weaker", "01:15", "02:00", 80), clip("best", "01:20", "02:00", 95), clip("other", "04:00", "04:30", 85)]
    assert [c["id"] for c in choose_clips(clips, overlap=0, min_score=75, limit=2)] == ["best", "other"]


@pytest.mark.parametrize("bad", ["../secret", "/etc/passwd", "a/../../secret", "https://example.com/a", "a\\secret"])
def test_capture_paths_cannot_escape_volume(tmp_path, bad):
    with pytest.raises(PipelineBlocked):
        contained_path(tmp_path, bad)


def test_capture_paths_reject_symlink_escape(tmp_path):
    (tmp_path / "outside").symlink_to(Path("/tmp"), target_is_directory=True)
    with pytest.raises(PipelineBlocked):
        contained_path(tmp_path, "outside/secret")


def test_retry_backoff_is_bounded():
    assert retry_delay(0) == 15
    assert retry_delay(2) == 60
    assert retry_delay(100) == 3600


def test_adjacent_windows_deduplicate_the_same_source_event_per_account():
    reservations = [{"account_id": "youtube", "start": 570, "end": 599}]
    assert overlaps_reserved(565, 605, "youtube", reservations)
    assert not overlaps_reserved(565, 605, "instagram", reservations)
    assert not overlaps_reserved(610, 650, "youtube", reservations)


async def test_native_requests_are_signed_and_post_keys_remain_stable():
    seen = []

    async def endpoint(request):
        seen.append(request)
        return httpx.Response(200, json={"post": {"id": "persisted"}})

    async with NativeClient("http://backend:8000", "server-secret", transport=httpx.MockTransport(endpoint)) as native:
        for _ in range(2):
            assert (await native.request("owner", "POST", "/social/posts", key="recording:stable", json={"clip_id": "clip"}))["post"]["id"] == "persisted"
    assert all(r.headers["x-supoclip-user-id"] == "owner" and r.headers["x-supoclip-signature"] for r in seen)
    assert {r.headers["idempotency-key"] for r in seen} == {"recording:stable"}


async def test_native_auth_failure_blocks_instead_of_blind_retry():
    async with NativeClient("http://backend", "secret", transport=httpx.MockTransport(lambda r: httpx.Response(401))) as native:
        with pytest.raises(PipelineBlocked):
            await native.request("owner", "GET", "/tasks/id")
