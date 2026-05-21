"""Cross-platform clipboard reading.

No third-party deps required:
  macOS  — subprocess pbpaste
  Windows — ctypes win32 API
  Linux  — subprocess xclip or xsel
"""

from __future__ import annotations

import subprocess
import sys


def read() -> str | None:
    """Return current clipboard text, or None on failure / unsupported."""
    try:
        match sys.platform:
            case "darwin":
                return _read_macos()
            case "win32":
                return _read_win32()
            case _:
                return _read_linux()
    except Exception:
        return None


def write(text: str) -> bool:
    """Replace clipboard contents with `text`. Returns True on success."""
    try:
        match sys.platform:
            case "darwin":
                return _write_macos(text)
            case "win32":
                return _write_win32(text)
            case _:
                return _write_linux(text)
    except Exception:
        return False


def _write_macos(text: str) -> bool:
    r = subprocess.run(
        ["pbcopy"], input=text, text=True, timeout=2, check=False,
    )
    return r.returncode == 0


def _write_win32(text: str) -> bool:
    import ctypes  # noqa: PLC0415

    CF_UNICODETEXT = 13
    GMEM_MOVEABLE = 0x0002
    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    if not user32.OpenClipboard(None):
        return False
    try:
        user32.EmptyClipboard()
        # Allocate a global buffer for the wide string (UTF-16) plus terminator.
        size = (len(text) + 1) * ctypes.sizeof(ctypes.c_wchar)
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, size)
        if not handle:
            return False
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            kernel32.GlobalFree(handle)
            return False
        try:
            ctypes.memmove(ptr, ctypes.create_unicode_buffer(text), size)
        finally:
            kernel32.GlobalUnlock(handle)
        if not user32.SetClipboardData(CF_UNICODETEXT, handle):
            kernel32.GlobalFree(handle)
            return False
        return True
    finally:
        user32.CloseClipboard()


def _write_linux(text: str) -> bool:
    for cmd in (
        ["xclip", "-selection", "clipboard"],
        ["xsel", "--input", "--clipboard"],
        ["wl-copy"],
    ):
        try:
            r = subprocess.run(cmd, input=text, text=True, timeout=2, check=False)
            if r.returncode == 0:
                return True
        except FileNotFoundError:
            continue
    return False


def _read_macos() -> str | None:
    r = subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=2)
    return r.stdout if r.returncode == 0 else None


def _read_win32() -> str | None:
    import ctypes  # noqa: PLC0415

    CF_UNICODETEXT = 13
    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    if not user32.OpenClipboard(None):
        return None
    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return None
        ptr = kernel32.GlobalLock(handle)
        try:
            return ctypes.wstring_at(ptr)
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def _read_linux() -> str | None:
    for cmd in (
        ["xclip", "-o", "-selection", "clipboard"],
        ["xsel", "--output", "--clipboard"],
        ["wl-paste"],  # Wayland
    ):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=2)
            if r.returncode == 0:
                return r.stdout
        except FileNotFoundError:
            continue
    return None
