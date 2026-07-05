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
  PGA's mute switch alone is NOT sufficient, though — "AGC" (Automatic
  Gain Control) actively fights it, cranking gain against near-silence
  regardless of PGA's mute state (found live on the Pi, 2026-07-05;
  see set_mic_muted/_disable_agc). Every mute call also force-disables
  AGC for this reason.

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
_AGC_CONTROL = "AGC"


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

    Also force-disables AGC (see _disable_agc's docstring) on every
    call, muted or not — found live on the Pi (2026-07-05) that PGA's
    own mute switch alone did NOT silence the capture stream; AGC kept
    fighting it. Redundant with the one-time fix applied at deploy time
    (`alsactl store`), but cheap insurance against AGC getting
    re-enabled by some other path (a factory reset, a driver reload).
    """
    _disable_agc()
    return _amixer("sset", _MIC_CONTROL, "nocap" if muted else "cap") is not None


def _disable_agc() -> None:
    """AGC (Automatic Gain Control) actively fights PGA's own mute and
    gain settings — found live on the Pi (2026-07-05): muting PGA alone
    left the capture stream receiving heavily saturated "audio" (33% of
    samples above 0.9 amplitude, sustained through multi-second clips),
    because AGC kept cranking gain trying to hit its own target level
    against near-silence, regardless of PGA's mute state. Confirmed:
    disabling AGC together with PGA's mute produced true silence
    (peak=0.0, rms=0.0 measured directly). AGC fighting the manually-
    tuned PGA gain level is also a plausible contributor to the mic
    pickup/STT quality issues seen earlier in the same session, even
    when NOT muted — so this is called unconditionally, not gated on
    the mute state itself.
    """
    _amixer("sset", _AGC_CONTROL, "off")
