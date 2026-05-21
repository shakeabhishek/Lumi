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


def test_capture_restores_original_clipboard_after_selection_grab() -> None:
    """When the user has a selection AND something already on the clipboard,
    the hotkey shouldn't trash the existing clipboard. Capture the selection,
    then write the original back so paste-elsewhere still works."""
    reads = iter(["important previous clipboard", "the user's selection"])
    fake_controller_mod = MagicMock()
    with (
        patch("lumi.host_helper.send_to_lumi.clip.read", side_effect=lambda: next(reads)),
        patch("lumi.host_helper.send_to_lumi.clip.write") as mock_write,
        patch.dict("sys.modules", {"pynput.keyboard": fake_controller_mod}),
    ):
        result = capture_selected_text(simulate_copy=True)

    assert result is not None
    assert result.source == "selection"
    assert result.text == "the user's selection"
    mock_write.assert_called_once_with("important previous clipboard")


def test_capture_does_not_restore_when_no_selection_was_taken() -> None:
    """If the simulated copy didn't change the clipboard (no selection),
    we never wrote to the clipboard — so no restore is needed and we
    shouldn't call clip.write at all."""
    fake_controller_mod = MagicMock()
    with (
        patch("lumi.host_helper.send_to_lumi.clip.read", return_value="static-clip"),
        patch("lumi.host_helper.send_to_lumi.clip.write") as mock_write,
        patch.dict("sys.modules", {"pynput.keyboard": fake_controller_mod}),
    ):
        capture_selected_text(simulate_copy=True)

    mock_write.assert_not_called()


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


def test_consume_treats_stale_pending_as_absent(tmp_path: Path) -> None:
    """Audit #22 — a pending context older than the staleness cap is treated
    as missing, so an ancient hotkey press doesn't surprise a later turn."""
    import json  # noqa: PLC0415
    from datetime import datetime, timedelta, timezone  # noqa: PLC0415

    from lumi.host_helper.send_to_lumi import _PENDING_FILENAME, consume_pending  # noqa: PLC0415

    stale_ts = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    (tmp_path / _PENDING_FILENAME).write_text(json.dumps({
        "text": "ancient", "source": "selection", "ts": stale_ts,
    }))

    result = consume_pending(tmp_path)
    assert result is None
    # File must still be consumed (deleted) so the next fresh press is clean.
    assert not (tmp_path / _PENDING_FILENAME).exists()


def test_consume_keeps_fresh_pending(tmp_path: Path) -> None:
    """The negative case for staleness: a recent press is still delivered."""
    import json  # noqa: PLC0415
    from datetime import datetime, timezone  # noqa: PLC0415

    from lumi.host_helper.send_to_lumi import _PENDING_FILENAME, consume_pending  # noqa: PLC0415

    fresh_ts = datetime.now(timezone.utc).isoformat()
    (tmp_path / _PENDING_FILENAME).write_text(json.dumps({
        "text": "fresh content", "source": "selection", "ts": fresh_ts,
    }))

    result = consume_pending(tmp_path)
    assert result is not None
    assert result["text"] == "fresh content"


def test_consume_with_malformed_ts_does_not_drop_payload(tmp_path: Path) -> None:
    """If the ts field is garbage (corrupt file or older payload format),
    don't punish the user for our bug — treat as fresh, deliver."""
    import json  # noqa: PLC0415

    from lumi.host_helper.send_to_lumi import _PENDING_FILENAME, consume_pending  # noqa: PLC0415

    (tmp_path / _PENDING_FILENAME).write_text(json.dumps({
        "text": "deliver me", "source": "selection", "ts": "garbage",
    }))

    result = consume_pending(tmp_path)
    assert result is not None
    assert result["text"] == "deliver me"


def test_consume_returns_none_when_no_pending(tmp_path: Path) -> None:
    assert consume_pending(tmp_path) is None


def test_consume_deletes_even_on_corrupt_file(tmp_path: Path) -> None:
    (tmp_path / ".pending_context.json").write_text("not json")
    result = consume_pending(tmp_path)
    # Returns None for corrupt content...
    assert result is None
    # ...but still cleans up the bad file so it doesn't sit around forever.
    assert not (tmp_path / ".pending_context.json").exists()


def test_notify_passes_content_via_argv_not_interpolation() -> None:
    """Audit #19 — title/body must be argv, not interpolated into the
    AppleScript source. A title containing a quote shouldn't end up
    inside the -e string at all."""
    if not _is_macos_helper():
        return            # mac-only path
    from unittest.mock import patch  # noqa: PLC0415

    with (
        patch("shutil.which", return_value="/usr/bin/osascript"),
        patch("subprocess.run") as mock_run,
    ):
        from lumi.host_helper.send_to_lumi import notify  # noqa: PLC0415
        notify(title='trick"title', body='trick"body`whoami`')

    assert mock_run.called
    args, _kwargs = mock_run.call_args
    cmd = args[0]
    # The user-controlled strings are argv positions 3 and 4 (after
    # ["osascript", "-e", <script>]).
    assert cmd[0] == "osascript"
    assert cmd[1] == "-e"
    script_text = cmd[2]
    # The script never contains the user content.
    assert 'trick"title' not in script_text
    assert 'whoami' not in script_text
    # They're in argv where AppleScript treats them as opaque strings.
    assert 'trick"title' in cmd[3:]
    assert 'trick"body`whoami`' in cmd[3:]


def _is_macos_helper() -> bool:
    """Inline import-guard so the patched test runs on CI's mac runners only."""
    import sys  # noqa: PLC0415
    return sys.platform == "darwin"


def test_format_hint_includes_text_and_source() -> None:
    hint = format_hint({"text": "x = 42", "source": "selection"})
    assert "x = 42" in hint
    assert "selection" in hint


# ── combo handling ──────────────────────────────────────────────────────────


def test_default_combo_per_platform() -> None:
    from lumi.host_helper import send_to_lumi as m

    with patch.object(m, "_is_macos", return_value=True):
        assert m.default_combo() == "cmd+alt+l"
    with patch.object(m, "_is_macos", return_value=False):
        assert m.default_combo() == "ctrl+alt+l"


def test_to_pynput_combo_wraps_modifiers() -> None:
    from lumi.host_helper.send_to_lumi import to_pynput_combo

    with patch("lumi.host_helper.send_to_lumi._is_macos", return_value=True):
        assert to_pynput_combo("cmd+shift+l") == "<cmd>+<shift>+l"
        assert to_pynput_combo("alt+k") == "<alt>+k"


def test_to_pynput_combo_normalizes_cmd_on_linux() -> None:
    """On non-macOS, `cmd` should become `<ctrl>` since pynput's <cmd> doesn't carry."""
    from lumi.host_helper.send_to_lumi import to_pynput_combo

    with patch("lumi.host_helper.send_to_lumi._is_macos", return_value=False):
        assert to_pynput_combo("cmd+shift+l") == "<ctrl>+<shift>+l"


def test_display_combo_capitalizes() -> None:
    from lumi.host_helper.send_to_lumi import display_combo

    assert display_combo("cmd+shift+l") == "Cmd+Shift+L"


def test_hotkey_daemon_uses_explicit_combo() -> None:
    from pathlib import Path as _Path
    from lumi.host_helper.send_to_lumi import HotkeyDaemon

    d = HotkeyDaemon(data_dir=_Path("/tmp/x"), combo="alt+space")
    assert d._combo == "alt+space"


def test_hotkey_daemon_empty_combo_falls_back_to_default() -> None:
    from pathlib import Path as _Path
    from lumi.host_helper.send_to_lumi import HotkeyDaemon, default_combo

    d = HotkeyDaemon(data_dir=_Path("/tmp/x"), combo="")
    assert d._combo == default_combo()
