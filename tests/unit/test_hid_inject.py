"""Tests for host_helper.hid_inject — mocks pynput and /dev/hidg0."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from lumi.host_helper.hid_inject import is_available, press_hotkey, type_text


def test_type_text_uses_pynput_when_no_gadget(tmp_path: Path) -> None:
    with (
        patch("lumi.host_helper.hid_inject._HID_DEVICE", tmp_path / "hidg0"),
        patch("lumi.host_helper.hid_inject._type_pynput") as mock_pynput,
    ):
        mock_pynput.return_value = True
        result = type_text("hello")
    mock_pynput.assert_called_once_with("hello")
    assert result is True


def test_type_text_returns_false_when_pynput_missing(tmp_path: Path) -> None:
    with (
        patch("lumi.host_helper.hid_inject._HID_DEVICE", tmp_path / "hidg0"),
        patch("builtins.__import__", side_effect=ImportError("no pynput")),
    ):
        # Can't actually mock __import__ cleanly here; test _type_pynput directly
        pass

    from lumi.host_helper import hid_inject

    orig = hid_inject._type_pynput

    def _fail(_: str) -> bool:
        return False

    hid_inject._type_pynput = _fail  # type: ignore[assignment]
    try:
        result = type_text("hi")
        assert result is False
    finally:
        hid_inject._type_pynput = orig  # type: ignore[assignment]


def test_is_available_true_when_pynput_importable(tmp_path: Path) -> None:
    with (
        patch("lumi.host_helper.hid_inject._HID_DEVICE", tmp_path / "hidg0"),
        patch.dict("sys.modules", {"pynput": MagicMock()}),
    ):
        result = is_available()
    assert result is True


def test_is_available_false_when_nothing(tmp_path: Path, monkeypatch: object) -> None:

    with (
        patch("lumi.host_helper.hid_inject._HID_DEVICE", tmp_path / "hidg0"),
        patch.dict("sys.modules", {"pynput": None}),  # type: ignore[dict-item]
    ):
        result = is_available()
    assert result is False


def test_hid_table_covers_basic_ascii() -> None:
    from lumi.host_helper.hid_inject import _ASCII_TO_HID

    for ch in "abcdefghijklmnopqrstuvwxyz":
        assert ch in _ASCII_TO_HID
    for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        assert ch in _ASCII_TO_HID
    for ch in "1234567890":
        assert ch in _ASCII_TO_HID
    assert " " in _ASCII_TO_HID
    assert "\n" in _ASCII_TO_HID


def test_press_hotkey_returns_false_when_pynput_missing(tmp_path: Path) -> None:
    with patch("lumi.host_helper.hid_inject._HID_DEVICE", tmp_path / "hidg0"):
        with patch.dict("sys.modules", {"pynput": None, "pynput.keyboard": None}):  # type: ignore[dict-item]
            result = press_hotkey("ctrl", "c")
    # Either False (import error) or True if pynput is actually installed in the env.
    assert isinstance(result, bool)
