"""Native volume control skill — adjusts system audio without network."""

from __future__ import annotations

import re
import subprocess
import sys

from ..base import NativeSkill, SkillResult

_TRIGGERS = re.compile(
    r"\b(volume|louder|quieter|softer|mute|unmute|silence)\b",
    re.IGNORECASE,
)
_LEVEL = re.compile(r"\b(\d{1,3})\s*(?:percent|%)?\b")
_STEP = 20  # % to step up/down


def _get_volume_macos() -> int | None:
    r = subprocess.run(
        ["osascript", "-e", "output volume of (get volume settings)"],
        capture_output=True, text=True, timeout=3,
    )
    if r.returncode == 0:
        try:
            return int(r.stdout.strip())
        except ValueError:
            return None
    return None


def _set_volume_macos(level: int) -> bool:
    level = max(0, min(100, level))
    r = subprocess.run(
        ["osascript", "-e", f"set volume output volume {level}"],
        capture_output=True, timeout=3,
    )
    return r.returncode == 0


def _set_mute_macos(muted: bool) -> bool:
    val = "true" if muted else "false"
    r = subprocess.run(
        ["osascript", "-e", f"set volume output muted {val}"],
        capture_output=True, timeout=3,
    )
    return r.returncode == 0


def _set_volume_linux(level: int) -> bool:
    level = max(0, min(100, level))
    for cmd in (
        ["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{level}%"],
        ["amixer", "set", "Master", f"{level}%"],
    ):
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=3)
            if r.returncode == 0:
                return True
        except FileNotFoundError:
            continue
    return False


def _adjust_volume(delta: int) -> str:
    if sys.platform == "darwin":
        current = _get_volume_macos() or 50
        new_level = max(0, min(100, current + delta))
        if _set_volume_macos(new_level):
            return f"Volume set to {new_level}%."
        return "Couldn't adjust volume."
    if _set_volume_linux(50 + delta):  # no get on linux, just set relative
        return f"Volume {'up' if delta > 0 else 'down'}."
    return "Couldn't adjust volume."


class VolumeSkill(NativeSkill):
    def matches(self, transcript: str) -> bool:
        return bool(_TRIGGERS.search(transcript))

    def execute(self, transcript: str) -> SkillResult:
        t = transcript.lower()

        if "mute" in t and "un" not in t:
            ok = _set_mute_macos(True) if sys.platform == "darwin" else False
            return SkillResult(text="Muted." if ok else "Couldn't mute.")

        if "unmute" in t:
            ok = _set_mute_macos(False) if sys.platform == "darwin" else False
            return SkillResult(text="Unmuted." if ok else "Couldn't unmute.")

        level_match = _LEVEL.search(t)
        if level_match and ("set" in t or "volume" in t):
            level = int(level_match.group(1))
            ok = (
                _set_volume_macos(level) if sys.platform == "darwin"
                else _set_volume_linux(level)
            )
            return SkillResult(text=f"Volume set to {level}%." if ok else "Couldn't set volume.")

        if any(w in t for w in ("up", "louder", "higher", "raise")):
            return SkillResult(text=_adjust_volume(+_STEP))

        if any(w in t for w in ("down", "quieter", "softer", "lower")):
            return SkillResult(text=_adjust_volume(-_STEP))

        # Generic "volume" without direction — report current level
        if sys.platform == "darwin":
            level = _get_volume_macos()
            if level is not None:
                return SkillResult(text=f"Volume is at {level}%.")
        return SkillResult(text="Say 'volume up', 'volume down', or 'set volume to 50%'.")
