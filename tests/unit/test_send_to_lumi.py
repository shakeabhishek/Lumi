"""Tests for the global-hotkey send-to-Lumi pipeline.

Covers:
  - capture_selected_text with simulated copy (clipboard changes → selection)
  - capture_selected_text fallback (clipboard unchanged → use existing clipboard)
  - capture_selected_text with empty clipboard → None
  - write/consume_pending round-trip
  - format_hint shape

pynput is mocked so the tests don't need accessibility permission or a real
keyboard. The clipboard layer is patched to return scripted values.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from lumi.host_helper.send_to_lumi import (
    CaptureResult,
    capture_selected_text,
    consume_pending,
    format_hint,
    write_pending,
)


def test_capture_returns_selection_when_clipboard_changes() -> None:
    """Clipboard changes after the simulated Cmd+C → that's the selection."""
    reads = iter(["before-text", "newly-selected-text"])
    fake_kb = MagicMock()
    fake_kb.pressed.return_value.__enter__.return_value = None
    fake_kb.pressed.return_value.__exit__.return_value = None
    fake_controller_mod = MagicMock()
    fake_controller_mod.Controller.return_value = fake_kb
    fake_controller_mod.Key.cmd = "cmd"
    fake_controller_mod.Key.ctrl = "ctrl"

    with patch("lumi.host_helper.send_to_lumi.clip.read", side_effect=lambda: next(reads)), \
         patch.dict("sys.modules", {"pynput.keyboard": fake_controller_mod}):
        result = capture_selected_text(simulate_copy=True)

    assert result is not None
    assert result.source == "selection"
    assert result.text == "newly-selected-text"


def test_capture_falls_back_to_clipboard_when_unchanged() -> None:
    """Nothing was selected (clipboard stayed the same) → return existing clipboard."""
    fake_controller_mod = MagicMock()
    with patch("lumi.host_helper.send_to_lumi.clip.read", return_value="existing-clip"), \
         patch.dict("sys.modules", {"pynput.keyboard": fake_controller_mod}):
        result = capture_selected_text(simulate_copy=True)

    assert result is not None
    assert result.source == "clipboard"
    assert result.text == "existing-clip"


def test_capture_returns_none_when_clipboard_empty() -> None:
    fake_controller_mod = MagicMock()
    with patch("lumi.host_helper.send_to_lumi.clip.read", return_value=""), \
         patch.dict("sys.modules", {"pynput.keyboard": fake_controller_mod}):
        result = capture_selected_text(simulate_copy=True)
    assert result is None


def test_capture_no_simulate_uses_only_clipboard() -> None:
    with patch("lumi.host_helper.send_to_lumi.clip.read", return_value="just clipboard"):
        result = capture_selected_text(simulate_copy=False)
    assert result is not None
    assert result.source == "clipboard"
    assert result.text == "just clipboard"


def test_capture_truncates_huge_selection() -> None:
    big = "x" * 9999
    reads = iter(["", big])
    fake_controller_mod = MagicMock()
    with patch("lumi.host_helper.send_to_lumi.clip.read", side_effect=lambda: next(reads)), \
         patch.dict("sys.modules", {"pynput.keyboard": fake_controller_mod}):
        result = capture_selected_text(simulate_copy=True)
    assert result is not None
    assert len(result.text) == 4000  # _MAX_TEXT_CHARS


def test_write_then_consume_round_trip(tmp_path: Path) -> None:
    write_pending(tmp_path, CaptureResult(text="hello world", source="selection"))
    payload = consume_pending(tmp_path)
    assert payload is not None
    assert payload["text"] == "hello world"
    assert payload["source"] == "selection"
    assert "ts" in payload
    # File should be deleted after consume.
    assert not (tmp_path / ".pending_context.json").exists()


def test_consume_returns_none_when_no_pending(tmp_path: Path) -> None:
    assert consume_pending(tmp_path) is None


def test_consume_deletes_even_on_corrupt_file(tmp_path: Path) -> None:
    (tmp_path / ".pending_context.json").write_text("not json")
    result = consume_pending(tmp_path)
    # Returns None for corrupt content...
    assert result is None
    # ...but still cleans up the bad file so it doesn't sit around forever.
    assert not (tmp_path / ".pending_context.json").exists()


def test_format_hint_includes_text_and_source() -> None:
    hint = format_hint({"text": "x = 42", "source": "selection"})
    assert "x = 42" in hint
    assert "selection" in hint
