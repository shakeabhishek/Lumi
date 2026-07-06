"""ALSA mixer control for the ReSpeaker card — real hardware volume/mute
backing the device-display's on-screen audio controls.

Two separate knobs, deliberately not conflated:

  Speaker output volume  -> the "PCM" (digital playback) control, which
  spans a real -63.5dB to 0dB range. The on-screen volume slider drives
  this, NOT "HP" — found live on the Pi (2026-07-06) that "HP" (the
  headphone-out analog stage) only spans 0dB to +9dB: at its lowest
  setting, HP still passes the signal at unity gain (0dB), not silence.
  Dragging the slider across HP's entire range was a barely-audible 9dB
  swing, which read as "the volume controls don't work" — moving the
  slider really did change the hardware value (confirmed directly), it
  just never had enough range to produce an audible difference. PCM's
  63.5dB span is what actually gives a slider from-near-silent-to-full
  behavior. HP is left fixed at maximum (see _ensure_hp_maxed) as a
  constant headroom boost rather than exposed to the user, since
  stacking two independently-adjustable gain stages for one "volume"
  concept would be confusing for no benefit — the wide PCM range alone
  is enough control.

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
_SPEAKER_CONTROL = "PCM"
_SPEAKER_BOOST_CONTROL = "HP"
_MIC_CONTROL = "PGA"
_AGC_CONTROL = "AGC"

# PCM's raw dB scale is roughly LINEAR in dB (confirmed directly: 0%→
# -63.5dB, 50%→-31.5dB, 100%→0dB) — but human hearing perceives loudness
# roughly logarithmically, so a naive 0-100 slider mapped straight onto
# that linear-dB range crams nearly all the audible range into the top
# sliver. Found live on the Pi (2026-07-06): user reported anything
# below ~90% slider position was inaudible — at PCM's own linear
# mapping, 90% is only about -6.5dB, meaning this speaker/room's usable
# dynamic range is much narrower than PCM's full 63.5dB span. Below
# this floor, the on-screen slider now clamps to it instead of
# continuing to sweep the practically-silent-anyway remainder of PCM's
# range — the whole 0-100 slider maps onto PCM's [floor, 100] sub-range.
_PCM_FLOOR_PERCENT = 75


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


def _slider_to_pcm_percent(level: int) -> int:
    """Map the user-facing 0-100 slider onto PCM's [_PCM_FLOOR_PERCENT, 100]
    sub-range, so the slider's full travel stays within the range that's
    actually audible on this hardware instead of spending most of its
    range on PCM settings quiet enough to be inaudible anyway."""
    level = max(0, min(100, level))
    span = 100 - _PCM_FLOOR_PERCENT
    return round(_PCM_FLOOR_PERCENT + span * level / 100)


def _pcm_percent_to_slider(pcm_percent: int) -> int:
    """Inverse of _slider_to_pcm_percent, for reporting the slider's
    position back from PCM's raw percentage."""
    span = 100 - _PCM_FLOOR_PERCENT
    if pcm_percent <= _PCM_FLOOR_PERCENT:
        return 0
    return round((pcm_percent - _PCM_FLOOR_PERCENT) * 100 / span)


def get_volume() -> int:
    """Current speaker volume, 0-100 (slider-space, not raw PCM). Returns
    50 if the card is unavailable."""
    out = _amixer("sget", _SPEAKER_CONTROL)
    if not out:
        return 50
    match = re.search(r"\[(\d{1,3})%\]", out)
    if not match:
        return 50
    return _pcm_percent_to_slider(int(match.group(1)))


def set_volume(level: int) -> bool:
    """Set speaker volume, 0-100 (slider-space, remapped onto PCM's
    audible sub-range — see _slider_to_pcm_percent). Returns False if
    the card is unavailable."""
    _ensure_hp_maxed()
    pcm_percent = _slider_to_pcm_percent(level)
    return _amixer("sset", _SPEAKER_CONTROL, f"{pcm_percent}%") is not None


def _ensure_hp_maxed() -> None:
    """HP is a fixed headroom boost (0dB to +9dB), not the user-facing
    volume control — see the module docstring for why PCM (63.5dB range)
    is the real "volume" knob instead. Called on every set_volume() as
    cheap insurance against HP drifting down from something else (e.g.
    a stray alsactl restore) and silently capping PCM's effective range
    again, the same way the original HP-as-volume bug did."""
    _amixer("sset", _SPEAKER_BOOST_CONTROL, "100%")


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
