"""Backlight control for the Touch Display 2 — real hardware brightness
backing the device-display's on-screen brightness slider.

The panel exposes a standard Linux backlight sysfs interface
(`/sys/class/backlight/<name>/brightness`), written directly as a plain
file — no `amixer`-style subprocess needed. `lumi-web` runs as user
`lumi`, which is in the `video` group; that group has write access to
the brightness file (confirmed: `-rw-rw-r-- root:video`), so no `sudo`
or extra systemd capability is required.

The backlight device directory name isn't stable across panel models —
found by globbing `/sys/class/backlight/*` rather than hardcoding
`panel_backlight@1`, the same "address by discoverable identity, not a
number that can shift" principle as `audio_mixer.py`'s card-by-name.

Every function no-ops safely (returns a sensible default / False) when
no backlight device is present — e.g. running on a laptop during dev.
"""

from __future__ import annotations

from pathlib import Path

from ..log import get_logger

log = get_logger(__name__)

_BACKLIGHT_ROOT = Path("/sys/class/backlight")


def _device_dir() -> Path | None:
    if not _BACKLIGHT_ROOT.is_dir():
        return None
    return next(iter(sorted(_BACKLIGHT_ROOT.iterdir())), None)


def _max_brightness(device: Path) -> int:
    try:
        return int((device / "max_brightness").read_text().strip())
    except (OSError, ValueError):
        return 0


def is_available() -> bool:
    """True iff a backlight device is present."""
    return _device_dir() is not None


def get_brightness() -> int:
    """Current brightness, 0-100. Returns 100 if no backlight device
    is present (dev laptop, or a non-dimmable display)."""
    device = _device_dir()
    if device is None:
        return 100
    max_raw = _max_brightness(device)
    if max_raw <= 0:
        return 100
    try:
        raw = int((device / "actual_brightness").read_text().strip())
    except (OSError, ValueError):
        return 100
    return round(raw / max_raw * 100)


def set_brightness(level: int) -> bool:
    """Set brightness, 0-100. Returns False if no backlight device is
    present or the write fails (e.g. permissions)."""
    device = _device_dir()
    if device is None:
        return False
    max_raw = _max_brightness(device)
    if max_raw <= 0:
        return False
    level = max(0, min(100, level))
    raw = round(level / 100 * max_raw)
    try:
        (device / "brightness").write_text(str(raw))
    except OSError as exc:
        log.warning("display_backlight.set_failed", error=str(exc))
        return False
    return True
