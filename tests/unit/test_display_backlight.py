"""Tests for the backlight sysfs wrapper backing the device-display's
on-screen brightness slider. Uses a fake sysfs tree under tmp_path rather
than mocking file I/O directly, so the real read/write logic is exercised."""

from __future__ import annotations

from pathlib import Path

import pytest

from lumi.hardware import display_backlight


def _fake_backlight(tmp_path: Path, max_brightness: int = 31, actual: int = 31) -> Path:
    root = tmp_path / "backlight"
    device = root / "panel_backlight@1"
    device.mkdir(parents=True)
    (device / "max_brightness").write_text(str(max_brightness))
    (device / "brightness").write_text(str(actual))
    (device / "actual_brightness").write_text(str(actual))
    return root


@pytest.fixture(autouse=True)
def _no_real_sysfs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Every test gets an empty fake root by default (no backlight device)
    unless it calls _fake_backlight() and points _BACKLIGHT_ROOT there."""
    monkeypatch.setattr(display_backlight, "_BACKLIGHT_ROOT", tmp_path / "empty")


def test_is_available_false_with_no_device() -> None:
    assert display_backlight.is_available() is False


def test_is_available_true_with_device(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root = _fake_backlight(tmp_path)
    monkeypatch.setattr(display_backlight, "_BACKLIGHT_ROOT", root)
    assert display_backlight.is_available() is True


def test_get_brightness_defaults_to_100_with_no_device() -> None:
    assert display_backlight.get_brightness() == 100


def test_get_brightness_scales_raw_to_percent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = _fake_backlight(tmp_path, max_brightness=31, actual=16)
    monkeypatch.setattr(display_backlight, "_BACKLIGHT_ROOT", root)
    # 16/31 = 51.6% -> rounds to 52
    assert display_backlight.get_brightness() == 52


def test_set_brightness_false_with_no_device() -> None:
    assert display_backlight.set_brightness(50) is False


def test_set_brightness_writes_scaled_raw_value(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = _fake_backlight(tmp_path, max_brightness=31, actual=31)
    monkeypatch.setattr(display_backlight, "_BACKLIGHT_ROOT", root)

    ok = display_backlight.set_brightness(50)
    assert ok is True
    device = root / "panel_backlight@1"
    # 50% of 31 = 15.5 -> rounds to 16
    assert (device / "brightness").read_text() == "16"


def test_set_brightness_clamps_out_of_range(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = _fake_backlight(tmp_path, max_brightness=31, actual=31)
    monkeypatch.setattr(display_backlight, "_BACKLIGHT_ROOT", root)
    device = root / "panel_backlight@1"

    display_backlight.set_brightness(200)
    assert (device / "brightness").read_text() == "31"

    display_backlight.set_brightness(-50)
    assert (device / "brightness").read_text() == "0"


def test_set_brightness_false_on_permission_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = _fake_backlight(tmp_path)
    monkeypatch.setattr(display_backlight, "_BACKLIGHT_ROOT", root)
    device = root / "panel_backlight@1" / "brightness"
    device.chmod(0o444)  # read-only, like a permission-denied real device
    try:
        assert display_backlight.set_brightness(50) is False
    finally:
        device.chmod(0o644)  # restore so pytest's tmp_path cleanup can delete it
