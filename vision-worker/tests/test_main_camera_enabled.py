"""Tests for _camera_enabled() — the one piece of main.py testable
without a real camera/mediapipe (the rest is a live capture loop)."""

from __future__ import annotations

import json
from pathlib import Path

from lumi_vision_worker.main import _camera_enabled


def test_true_when_flag_set(tmp_path: Path) -> None:
    (tmp_path / "user_settings.json").write_text(json.dumps({"camera_enabled": True}))
    assert _camera_enabled(tmp_path) is True


def test_false_when_flag_unset(tmp_path: Path) -> None:
    (tmp_path / "user_settings.json").write_text(json.dumps({"camera_enabled": False}))
    assert _camera_enabled(tmp_path) is False


def test_false_when_key_missing(tmp_path: Path) -> None:
    (tmp_path / "user_settings.json").write_text(json.dumps({"some_other_key": True}))
    assert _camera_enabled(tmp_path) is False


def test_false_when_file_missing(tmp_path: Path) -> None:
    assert _camera_enabled(tmp_path) is False


def test_false_when_file_is_invalid_json(tmp_path: Path) -> None:
    (tmp_path / "user_settings.json").write_text("{not valid json")
    assert _camera_enabled(tmp_path) is False
