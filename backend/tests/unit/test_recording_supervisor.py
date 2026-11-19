"""Host configuration and durable recovery boundaries."""
import json
import os
import time

import pytest

from src.workers.recording_supervisor import RuntimeSettings, atomic_json, healthy, load_epoch


def test_defaults_use_persistent_capture_volume(monkeypatch):
    monkeypatch.delenv("CAPTURE_ROOT", raising=False)
    settings = RuntimeSettings.from_env()
    assert str(settings.root) == "/data/recordings"
    assert settings.min_free_bytes >= 1024 ** 3
    assert settings.max_channels >= 1


@pytest.mark.parametrize("key,value", [("RECORDING_MAX_CHANNELS", "0"), ("RECORDING_MIN_FREE_GB", "-1"), ("RECORDING_MAX_BACKLOG", "0"), ("CAPTURE_ROOT", "relative")])
def test_invalid_runtime_settings_fail_fast(monkeypatch, key, value):
    monkeypatch.setenv(key, value)
    with pytest.raises(ValueError):
        RuntimeSettings.from_env()


def test_epoch_manifest_is_durable_and_rejects_foreign_paths(tmp_path):
    target = tmp_path / "epoch" / "epoch.json"
    atomic_json(target, {"session_id": "s", "epoch": "e", "policy": {}})
    assert load_epoch(target)["session_id"] == "s"
    assert not target.with_suffix(".tmp").exists()
    target.write_text('{"session_id":"../../foreign","epoch":"e","policy":{}}')
    with pytest.raises(ValueError):
        load_epoch(target)


def test_health_requires_recent_main_loop_progress(tmp_path):
    assert not healthy(tmp_path)
    heartbeat = tmp_path / ".supervisor-heartbeat"
    heartbeat.touch()
    assert healthy(tmp_path)
    old = time.time() - 121
    os.utime(heartbeat, (old, old))
    assert not healthy(tmp_path)
