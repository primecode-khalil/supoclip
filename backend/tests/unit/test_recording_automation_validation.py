"""Automation policies reject unsafe or ambiguous unattended settings."""
from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.recording.automation_schema import AutomationPolicy, WindowRegistration


def test_policy_defaults_require_explicit_automation_and_destinations():
    policy = AutomationPolicy()
    assert policy.enabled is False
    assert policy.social_account_ids == []
    assert policy.segment_seconds == 600 and policy.overlap_seconds == 60
    assert policy.processing_mode == "balanced" and policy.caption_template == "default"
    assert policy.min_score == 75 and policy.archive is False
    assert policy.publish_privacy == "private"


@pytest.mark.parametrize("values", [
    {"enabled": "yes"}, {"segment_seconds": 59}, {"segment_seconds": 1801},
    {"segment_seconds": 60}, {"overlap_seconds": -1}, {"overlap_seconds": 121},
    {"caption_template": "invented"}, {"clip_length": "120"}, {"processing_mode": "faster"},
    {"min_score": 101}, {"min_score": float("nan")}, {"max_posts_per_day": 0},
    {"max_clips_per_window": 11}, {"retain_days": 0}, {"archive_target": "/etc"},
    {"social_account_ids": ["../foreign"]}, {"social_account_ids": [str(uuid4())] * 2},
    {"publish_privacy": "everyone"},
])
def test_invalid_policy_rejected(values):
    with pytest.raises(ValidationError):
        AutomationPolicy(**values)


def registration(**values):
    return WindowRegistration(
        epoch="epoch-1", sequence=0, source_path="channel/session/epoch/segment_000.mkv",
        sha256="a" * 64, size_bytes=100, start_seconds=0.0, end_seconds=600.0,
        **values,
    )


def test_relative_window_identity_is_validated_without_loading_media():
    assert registration().source_path.endswith(".mkv")


@pytest.mark.parametrize("key,value", [
    ("source_path", "/etc/passwd"), ("source_path", "../a.mkv"),
    ("source_path", "x/../../a.mkv"), ("source_path", "x\\y.mkv"),
    ("source_path", "."),
    ("source_path", "x\na.mkv"), ("sha256", "bad"), ("size_bytes", 0),
    ("start_seconds", float("inf")), ("end_seconds", float("nan")),
    ("end_seconds", 0.0), ("overlap_seconds", 601.0), ("sequence", -1),
    ("epoch", "../../escape"),
])
def test_invalid_window_registration_rejected(key, value):
    values = registration().model_dump()
    values[key] = value
    with pytest.raises(ValidationError):
        WindowRegistration(**values)
