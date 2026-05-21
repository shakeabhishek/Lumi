"""HID text injection — types keystrokes into the host as if from a keyboard.

On laptop (dev): uses pynput (requires [host] optional extra).
On Pi hardware: will write directly to /dev/hidg0 (USB HID gadget).
"""

from __future__ import annotations

from pathlib import Path

from ..log import get_logger

log = get_logger(__name__)

# Path to USB HID gadget device on Pi. Not present on laptop.
_HID_DEVICE = Path("/dev/hidg0")


def type_text(text: str) -> bool:
    """Inject text as keyboard events. Returns True on success."""
    if _HID_DEVICE.exists():
        return _type_hid_gadget(text)
    return _type_pynput(text)


def press_hotkey(*keys: str) -> bool:
    """Press a key combination, e.g. press_hotkey('ctrl', 'c'). Returns True on success."""
    try:
        from pynput.keyboard import Controller, Key  # noqa: PLC0415

        _KEY_MAP = {
            "ctrl": Key.ctrl, "alt": Key.alt, "shift": Key.shift,
            "cmd": Key.cmd, "enter": Key.enter, "tab": Key.tab,
            "esc": Key.esc, "space": Key.space, "backspace": Key.backspace,
        }
        kb = Controller()
        resolved = [_KEY_MAP.get(k.lower(), k) for k in keys]
        with kb.pressed(*resolved[:-1]):
            kb.press(resolved[-1])
            kb.release(resolved[-1])
        return True
    except ImportError:
        log.warning("hid_inject.pynput_missing")
        return False
    except Exception as exc:
        log.warning("hid_inject.hotkey_error", error=str(exc))
        return False


def is_available() -> bool:
    """True if any injection method is available on this system."""
    if _HID_DEVICE.exists():
        return True
    try:
        import pynput  # noqa: F401, PLC0415

        return True
    except ImportError:
        return False


def _type_pynput(text: str) -> bool:
    try:
        from pynput.keyboard import Controller  # noqa: PLC0415

        kb = Controller()
        kb.type(text)
        log.info("hid_inject.pynput_ok", chars=len(text))
        return True
    except ImportError:
        log.warning("hid_inject.pynput_missing", hint="uv pip install -e '.[host]'")
        return False
    except Exception as exc:
        log.warning("hid_inject.pynput_error", error=str(exc))
        return False


# ---------------------------------------------------------------------------
# Pi HID gadget path (stubbed — wired up in Phase 5)
# ---------------------------------------------------------------------------

# HID keyboard report: modifier(1) + reserved(1) + keycodes(6)
_MOD_NONE = 0x00
_MOD_SHIFT = 0x02

# Basic US ASCII → HID keycode table (printable range only)
_ASCII_TO_HID: dict[str, tuple[int, int]] = {}


def _build_hid_table() -> None:

    _lower = "abcdefghijklmnopqrstuvwxyz"
    for i, c in enumerate(_lower):
        _ASCII_TO_HID[c] = (_MOD_NONE, 0x04 + i)
        _ASCII_TO_HID[c.upper()] = (_MOD_SHIFT, 0x04 + i)
    _digits = "1234567890"
    _digit_codes = [0x1E, 0x1F, 0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27]
    _shift_digits = "!@#$%^&*()"
    for c, code, shifted in zip(_digits, _digit_codes, _shift_digits, strict=True):
        _ASCII_TO_HID[c] = (_MOD_NONE, code)
        _ASCII_TO_HID[shifted] = (_MOD_SHIFT, code)
    _ASCII_TO_HID[" "] = (_MOD_NONE, 0x2C)
    _ASCII_TO_HID["\n"] = (_MOD_NONE, 0x28)
    _ASCII_TO_HID["\t"] = (_MOD_NONE, 0x2B)


_build_hid_table()


def _type_hid_gadget(text: str) -> bool:
    """Write HID keyboard reports directly to /dev/hidg0 on Pi."""
    try:
        with _HID_DEVICE.open("wb") as hid:
            for char in text:
                entry = _ASCII_TO_HID.get(char)
                if entry is None:
                    continue
                mod, keycode = entry
                # Key press
                hid.write(bytes([mod, 0x00, keycode, 0x00, 0x00, 0x00, 0x00, 0x00]))
                # Key release
                hid.write(bytes([0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]))
        log.info("hid_inject.gadget_ok", chars=len(text))
        return True
    except Exception as exc:
        log.warning("hid_inject.gadget_error", error=str(exc))
        return False
