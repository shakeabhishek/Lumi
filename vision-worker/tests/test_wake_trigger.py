"""Tests for write_wake_trigger — no camera/mediapipe needed."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from lumi_vision_worker.wake_trigger import write_wake_trigger


def test_writes_valid_json_with_source_and_recent_timestamp(tmp_path: Path) -> None:
    write_wake_trigger(tmp_path, source="gesture:wave")

    path = tmp_path / ".wake_trigger.json"
    assert path.exists()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["source"] == "gesture:wave"

    ts = datetime.fromisoformat(payload["ts"])
    age = (datetime.now(UTC) - ts).total_seconds()
    max_fresh_age_s = 2.0
    assert age < max_fresh_age_s, "timestamp should be freshly written, not stale"


def test_no_leftover_temp_file(tmp_path: Path) -> None:
    write_wake_trigger(tmp_path, source="presence")
    remaining = list(tmp_path.iterdir())
    expected = [tmp_path / ".wake_trigger.json"]
    assert remaining == expected, "no .tmp file should survive a successful write"


def test_overwrites_existing_trigger(tmp_path: Path) -> None:
    write_wake_trigger(tmp_path, source="presence")
    write_wake_trigger(tmp_path, source="gesture:wave")

    payload = json.loads((tmp_path / ".wake_trigger.json").read_text(encoding="utf-8"))
    assert payload["source"] == "gesture:wave"
