"""ALSA mixer control for the ReSpeaker card — real hardware volume/mute
backing the device-display's on-screen audio controls.

Two separate knobs, deliberately not conflated:

  Speaker output volume  -> the "HP" (headphone-out) control, which feeds
  the ReSpeaker's JST speaker via HPLOUT/HPROUT (see bom.md's ReSpeaker
  driver notes). This is what the on-screen volume slider drives.

  Mic privacy mute       -> the "PGA" (capture gain) control's hardware
  mute switch, which silences audio at the ALSA capture stage itself —
  not just an app-level flag. This matches the smart-speaker convention
  the on-screen mic button's icon implies (a mic-mute, not a speaker
  mute), and holds true even before a voice loop consumes the mic.

Card is addressed by name ("seeed2micvoicec"), not a numeric index, since
card ordering can shift (e.g. relative to the HDMI audio outputs) but the
name is stable. Every function no-ops safely (returns a sensible default /
False) when the card or `amixer` isn't present — e.g. running on a laptop
during dev, where these controls are simply unavailable.
"""

from __future__ import annotations

import re
import subprocess

from ..log import get_logger

log = get_logger(__name__)

_CARD = "seeed2micvoicec"
_SPEAKER_CONTROL = "HP"
_MIC_CONTROL = "PGA"


def _amixer(*args: str) -> str | None:
    try:
        r = subprocess.run(
            ["amixer", "-c", _CARD, *args],
            capture_output=True, text=True, timeout=3,
        )
        if r.returncode != 0:
            return None
        return r.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


def is_available() -> bool:
    """True iff the ReSpeaker card is present and `amixer` works."""
    return _amixer("scontrols") is not None


def get_volume() -> int:
    """Current speaker volume, 0-100. Returns 50 if the card is unavailable."""
    out = _amixer("sget", _SPEAKER_CONTROL)
    if not out:
        return 50
    match = re.search(r"\[(\d{1,3})%\]", out)
    return int(match.group(1)) if match else 50


def set_volume(level: int) -> bool:
    """Set speaker volume, 0-100. Returns False if the card is unavailable."""
    level = max(0, min(100, level))
    return _amixer("sset", _SPEAKER_CONTROL, f"{level}%") is not None


def get_mic_muted() -> bool:
    """True iff the mic capture path is hardware-muted."""
    out = _amixer("sget", _MIC_CONTROL)
    return bool(out) and "[off]" in out


def set_mic_muted(muted: bool) -> bool:
    """Mute/unmute the mic capture path at the hardware level.

    PGA is a *capture*-type switch (`cswitch`), not a playback switch —
    amixer rejects `mute`/`unmute` on it ("Invalid command!"); the
    correct keywords for a capture switch are `nocap` (mute) / `cap`
    (unmute), confirmed against the real card.
    """
    return _amixer("sset", _MIC_CONTROL, "nocap" if muted else "cap") is not None
