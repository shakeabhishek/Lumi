"""Cross-platform active window detection.

Returns the foreground window's title and application name.
No third-party deps required:
  macOS   — osascript (AppleScript)
  Windows — ctypes win32 API
  Linux   — xdotool subprocess
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass


@dataclass
class ActiveWindow:
    title: str
    app: str

    def __str__(self) -> str:
        if self.app and self.title and self.app != self.title:
            return f"{self.title} — {self.app}"
        return self.title or self.app or "unknown"


def get() -> ActiveWindow | None:
    """Return the current foreground window, or None on failure."""
    try:
        match sys.platform:
            case "darwin":
                return _get_macos()
            case "win32":
                return _get_win32()
            case _:
                return _get_linux()
    except Exception:
        return None


def _get_macos() -> ActiveWindow | None:
    # Two separate scripts: app name never fails, window title might (e.g. no open windows)
    app_script = (
        'tell application "System Events" to '
        'return name of first application process whose frontmost is true'
    )
    r = subprocess.run(["osascript", "-e", app_script], capture_output=True, text=True, timeout=3)
    if r.returncode != 0:
        return None
    app = r.stdout.strip()

    title_script = (
        'tell application "System Events" to '
        'return name of front window of first application process whose frontmost is true'
    )
    r2 = subprocess.run(["osascript", "-e", title_script], capture_output=True, text=True, timeout=3)
    title = r2.stdout.strip() if r2.returncode == 0 else app
    return ActiveWindow(title=title, app=app)


def _get_win32() -> ActiveWindow | None:
    import ctypes  # noqa: PLC0415

    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    hwnd = user32.GetForegroundWindow()
    length = user32.GetWindowTextLengthW(hwnd)
    if length == 0:
        return None
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    title = buf.value

    # Get process name via GetWindowThreadProcessId + OpenProcess
    pid = ctypes.c_ulong()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    try:
        import psutil  # noqa: PLC0415

        proc = psutil.Process(pid.value)
        app = proc.name().replace(".exe", "")
    except Exception:
        app = title
    return ActiveWindow(title=title, app=app)


def _get_linux() -> ActiveWindow | None:
    try:
        r = subprocess.run(
            ["xdotool", "getactivewindow", "getwindowname"],
            capture_output=True, text=True, timeout=2,
        )
        if r.returncode == 0:
            title = r.stdout.strip()
            return ActiveWindow(title=title, app=title.split(" — ")[-1] if " — " in title else title)
    except FileNotFoundError:
        pass

    # Fallback: wmctrl
    try:
        r = subprocess.run(["wmctrl", "-a", ":ACTIVE:"], capture_output=True, text=True, timeout=2)
        if r.returncode == 0:
            title = r.stdout.strip()
            return ActiveWindow(title=title, app=title)
    except FileNotFoundError:
        pass
    return None
