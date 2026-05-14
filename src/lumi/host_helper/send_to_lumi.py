"""Global-hotkey "Send to Lumi" daemon.

Press Cmd+Shift+L (macOS) / Ctrl+Shift+L (Linux/Windows) from anywhere on the
desktop. The daemon:
  1. Simulates a copy keystroke so the currently-*selected* text lands on the
     clipboard (Tier 2). If nothing is selected, the clipboard stays the same
     and we fall back to whatever's already on it (Tier 1).
  2. Reads the clipboard.
  3. Writes the captured text to `data_dir/.pending_context.json` — the voice
     loop picks this up at the top of its next turn and injects it into the
     system prompt via ConversationManager.set_context_hint().

Permissions:
  - `cfg.clipboard_enabled` must be true (the daemon refuses to run otherwise).
  - On macOS, simulating keystrokes requires Accessibility permission for the
    terminal/iTerm/whatever launched the daemon. macOS pops the grant dialog
    on first use; subsequent runs are silent.

Privacy:
  - The captured text never leaves the device.
  - We write only the pending file; the voice loop consumes + deletes it.
  - The audit log records "context_injected" with the length, not the content.
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..log import get_logger
from . import clipboard as clip

log = get_logger(__name__)

_PENDING_FILENAME = ".pending_context.json"
_RELEASE_WAIT_S = 0.15       # let the user release their hotkey modifiers first
_COPY_WAIT_S = 0.25          # then wait for the OS clipboard to settle after simulated Cmd+C
_MAX_TEXT_CHARS = 4000       # truncate runaway selections


@dataclass
class CaptureResult:
    """What the hotkey grabbed. `source` is "selection" or "clipboard"."""

    text: str
    source: str


def _is_macos() -> bool:
    return sys.platform == "darwin"


# ── hotkey combo handling ───────────────────────────────────────────────────

_MOD_TOKENS = {"cmd", "ctrl", "alt", "shift", "meta", "super", "win"}


def default_combo() -> str:
    """Platform-appropriate default combo, in the user-facing dotted form."""
    return "cmd+shift+l" if _is_macos() else "ctrl+shift+l"


def to_pynput_combo(combo: str) -> str:
    """Translate `cmd+shift+l` to `<cmd>+<shift>+l` for pynput.GlobalHotKeys.

    Modifier tokens get wrapped in angle brackets; the final key is left bare.
    On non-macOS, `cmd` is normalized to `ctrl` since pynput's <cmd> doesn't
    map cleanly outside macOS.
    """
    parts = [p.strip().lower() for p in combo.split("+") if p.strip()]
    if not _is_macos():
        parts = ["ctrl" if p == "cmd" else p for p in parts]
    out = []
    for p in parts:
        if p in _MOD_TOKENS:
            out.append(f"<{p}>")
        else:
            out.append(p)
    return "+".join(out)


def display_combo(combo: str) -> str:
    """Pretty-print a combo for terminal banners (Cmd+Shift+L)."""
    return "+".join(p.strip().capitalize() for p in combo.split("+") if p.strip())


def capture_selected_text(simulate_copy: bool = True) -> CaptureResult | None:
    """Try to grab the user's current selection, falling back to clipboard.

    With simulate_copy=True (default): we send Cmd+C / Ctrl+C, wait briefly,
    then read the clipboard. If the clipboard changed, that's the selection.
    If it didn't change, no text was selected — return what was on the
    clipboard already (so the hotkey still does something useful).
    """
    original = clip.read() or ""
    if not simulate_copy:
        text = original.strip()
        return CaptureResult(text=text, source="clipboard") if text else None

    try:
        from pynput.keyboard import Controller, Key  # noqa: PLC0415
    except ImportError:
        log.warning("send_to_lumi.no_pynput", hint="install pynput")
        text = original.strip()
        return CaptureResult(text=text, source="clipboard") if text else None

    # Wait for the user to release their hotkey modifiers — otherwise macOS
    # sees Cmd+Shift+L+Cmd+C as a garbage combination and ignores the copy.
    time.sleep(_RELEASE_WAIT_S)

    kb = Controller()
    modifier = Key.cmd if _is_macos() else Key.ctrl
    with kb.pressed(modifier):
        kb.press("c")
        kb.release("c")
    time.sleep(_COPY_WAIT_S)
    after = clip.read() or ""
    log.debug(
        "send_to_lumi.capture", original_len=len(original),
        after_len=len(after), changed=after != original,
    )

    if after and after != original:
        return CaptureResult(text=after.strip()[:_MAX_TEXT_CHARS], source="selection")
    text = original.strip()
    if not text:
        return None
    return CaptureResult(text=text[:_MAX_TEXT_CHARS], source="clipboard")


def write_pending(data_dir: Path, result: CaptureResult) -> Path:
    """Drop the captured text where the voice loop will find it."""
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / _PENDING_FILENAME
    payload = {
        "text": result.text,
        "source": result.source,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def consume_pending(data_dir: Path) -> dict | None:
    """Voice loop call: read + delete the pending context file, if any."""
    path = data_dir / _PENDING_FILENAME
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = None
    path.unlink(missing_ok=True)
    return payload


def format_hint(payload: dict) -> str:
    """Turn a pending-context payload into a system-prompt addendum."""
    text = payload.get("text", "")
    source = payload.get("source", "clipboard")
    return (
        f"The user has sent you the following {source} via hotkey. "
        f"Use it as context for whatever they ask next:\n\n{text}"
    )


class HotkeyDaemon:
    """Foreground process that listens for the global hotkey.

    Blocks on `run()`. Stop with Ctrl-C. Designed to run in its own terminal
    tab alongside the Lumi voice loop and web UI.
    """

    def __init__(
        self,
        data_dir: Path,
        simulate_copy: bool = True,
        combo: str | None = None,
    ) -> None:
        self._data_dir = data_dir
        self._simulate_copy = simulate_copy
        # Empty string and None both mean "use platform default".
        self._combo = combo.strip() if combo else default_combo()

    def run(self) -> None:
        try:
            from pynput import keyboard  # noqa: PLC0415
        except ImportError as exc:
            raise RuntimeError(
                "pynput not installed — install with: uv pip install -e '.[host]'"
            ) from exc

        pynput_combo = to_pynput_combo(self._combo)
        log.info("send_to_lumi.daemon_start", combo=pynput_combo, data_dir=str(self._data_dir))
        print(f"\n  ✦  Send-to-Lumi listening. Press {display_combo(self._combo)} from anywhere.\n")

        def _on_hotkey() -> None:
            result = capture_selected_text(simulate_copy=self._simulate_copy)
            if result is None:
                log.info("send_to_lumi.no_text")
                print("  …  nothing to send (no selection, empty clipboard)")
                return
            write_pending(self._data_dir, result)
            log.info("send_to_lumi.captured", source=result.source, chars=len(result.text))
            preview = result.text[:60].replace("\n", " ")
            print(f"  ✦  Sent to Lumi ({result.source}, {len(result.text)} chars): {preview}…")

        with keyboard.GlobalHotKeys({pynput_combo: _on_hotkey}) as h:
            try:
                h.join()
            except KeyboardInterrupt:
                log.info("send_to_lumi.daemon_stop")
                print("\n  bye 💖")
