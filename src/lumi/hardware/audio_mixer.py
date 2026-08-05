"""ALSA mixer control — real hardware volume/mute backing the device-display's
on-screen audio controls.

Speaker output is the ReSpeaker HAT; mic capture is whatever mic is connected
(discovered — see the note on split cards further down).

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
  behavior. HP is left fixed at maximum (see _ensure_boost_controls_maxed)
  as a constant headroom boost rather than exposed to the user, since
  stacking two independently-adjustable gain stages for one "volume"
  concept would be confusing for no benefit — the wide PCM range alone
  is enough control.

  A THIRD stage, "HP DAC", was found sitting at 55% (-26.5dB) the whole
  time (2026-07-06) — a completely separate gain control between the
  DAC and the HP analog stage that had never been touched or maxed,
  silently capping overall loudness by ~26.5dB regardless of what PCM
  or HP were set to. This is why "max volume is too low" persisted even
  with PCM and HP both already at their ceiling. Maxed alongside HP.

  Mic privacy mute       -> the capture control's hardware mute switch,
  which silences audio at the ALSA capture stage itself — not just an
  app-level flag. This matches the smart-speaker convention the on-screen
  mic button's icon implies (a mic-mute, not a speaker mute), and holds
  true even before a voice loop consumes the mic. The mute switch alone is
  NOT sufficient, though: every mic has an automatic-gain-control sibling
  that actively fights it, cranking gain against near-silence regardless
  of the mute state (found live on the Pi, 2026-07-05 with the ReSpeaker's
  "AGC"; the USB mic's is "Auto Gain Control"). Every mute call also
  force-disables it for this reason. See set_mic_muted/_disable_agc.

**Playback and capture are on different cards** as of 2026-08-05. The mic
moved to a USB mic, and the ReSpeaker now reports `max_input_channels=0` —
it's output-only in this build, and its bare `PGA` capture control is gone
(only `Line PGA Bypass`/`HP PGA Bypass` remain). So the old mic-mute pointed
at a control that no longer exists, meaning the on-screen mic button silently
stopped muting anything. Speaker volume still belongs to the ReSpeaker.

Rather than hardcode the new card, the capture side is **discovered** at first
use from `_CAPTURE_PROFILES`, probing for a control that actually exists and
is capture-capable. The user has now swapped mic hardware twice; a table plus
a probe survives the third time, and a wrong guess surfaces as "unavailable"
rather than as a mute button that quietly does nothing.

Cards are addressed by name, not numeric index, since card ordering can shift
(e.g. relative to the HDMI audio outputs) but the name is stable. Every
function no-ops safely (returns a sensible default / False) when the card or
`amixer` isn't present — e.g. running on a laptop during dev, where these
controls are simply unavailable.
"""

from __future__ import annotations

import re
import subprocess

from ..log import get_logger

log = get_logger(__name__)

_PLAYBACK_CARD = "seeed2micvoicec"
_SPEAKER_CONTROL = "PCM"
_SPEAKER_BOOST_CONTROLS = ("HP", "HP DAC")

# Ordered candidates for the capture side: (card, mute control, AGC control).
# First one whose mute control actually exists on the box wins.
_CAPTURE_PROFILES: tuple[tuple[str, str, str | None], ...] = (
    # The USB mic, Lumi's current input. ALSA gives it the unhelpfully
    # generic card id "Device" (confirmed via /proc/asound/card1/id); its
    # controls are 'Mic' (cvolume + cswitch) and 'Auto Gain Control'.
    # Listed first because it's what's plugged in today.
    ("Device", "Mic", "Auto Gain Control"),
    # The ReSpeaker HAT's own mics — kept so reverting the hardware needs no
    # code change. PGA is its capture switch, and AGC actively fights it.
    (_PLAYBACK_CARD, "PGA", "AGC"),
)

# Resolved lazily by _capture_profile(); None means "not looked up yet",
# and a cached () sentinel would be less readable than a separate flag.
_capture_cache: tuple[str, str, str | None] | None = None
_capture_probed = False

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


def _amixer_on(card: str, *args: str) -> str | None:
    try:
        r = subprocess.run(
            ["amixer", "-c", card, *args],
            capture_output=True, text=True, timeout=3, check=False,
        )
        if r.returncode != 0:
            return None
        return r.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


def _amixer(*args: str) -> str | None:
    """Playback card — speaker volume and its boost stages."""
    return _amixer_on(_PLAYBACK_CARD, *args)


def _capture_profile() -> tuple[str, str, str | None] | None:
    """Resolve (card, mute control, AGC control) for whatever mic is actually
    connected, probing once and caching. Returns None if no candidate has a
    usable capture switch — e.g. on a dev laptop."""
    global _capture_cache, _capture_probed  # noqa: PLW0603
    if _capture_probed:
        return _capture_cache

    _capture_probed = True
    for card, mute_control, agc_control in _CAPTURE_PROFILES:
        out = _amixer_on(card, "sget", mute_control)
        # 'cswitch' is what makes cap/nocap valid; a control that only has
        # cvolume can't be muted, and asserting otherwise would give us a
        # button that appears to work and doesn't.
        if out and "cswitch" in out:
            _capture_cache = (card, mute_control, agc_control)
            log.info(
                "audio.capture_mixer_resolved",
                card=card, control=mute_control, agc=agc_control,
            )
            return _capture_cache

    log.info("audio.capture_mixer_unavailable", probed=[p[0] for p in _CAPTURE_PROFILES])
    _capture_cache = None
    return None


def reset_capture_profile_cache() -> None:
    """Force re-probing — for tests, and for a mic hot-swap without a restart."""
    global _capture_cache, _capture_probed  # noqa: PLW0603
    _capture_cache = None
    _capture_probed = False


def is_available() -> bool:
    """True iff the playback card is present and `amixer` works."""
    return _amixer("scontrols") is not None


def is_mic_control_available() -> bool:
    """True iff a mutable capture control was found on some card."""
    return _capture_profile() is not None


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
    _ensure_boost_controls_maxed()
    pcm_percent = _slider_to_pcm_percent(level)
    return _amixer("sset", _SPEAKER_CONTROL, f"{pcm_percent}%") is not None


def _ensure_boost_controls_maxed() -> None:
    """HP and HP DAC are fixed headroom boosts (0dB to +9dB, and 0dB
    ceiling respectively), not the user-facing volume control — see the
    module docstring for why PCM (63.5dB range) is the real "volume"
    knob instead. Called on every set_volume() as cheap insurance
    against either drifting down from something else (e.g. a stray
    alsactl restore) and silently capping PCM's effective range again —
    HP DAC sitting at 55% (-26.5dB) undiscovered was exactly this
    failure mode, just never previously set at all rather than having
    drifted."""
    for control in _SPEAKER_BOOST_CONTROLS:
        _amixer("sset", control, "100%")


def get_mic_muted() -> bool:
    """True iff the mic capture path is hardware-muted."""
    profile = _capture_profile()
    if profile is None:
        return False
    card, control, _ = profile
    out = _amixer_on(card, "sget", control)
    return bool(out) and "[off]" in out


def set_mic_muted(muted: bool) -> bool:
    """Mute/unmute the mic capture path at the hardware level, on whichever
    card the mic actually lives on (see _capture_profile).

    These are *capture*-type switches (`cswitch`), not playback switches —
    amixer rejects `mute`/`unmute` on them ("Invalid command!"); the
    correct keywords for a capture switch are `nocap` (mute) / `cap`
    (unmute), confirmed against the real cards.

    Also force-disables AGC (see _disable_agc's docstring) on every
    call, muted or not — found live on the Pi (2026-07-05) that PGA's
    own mute switch alone did NOT silence the capture stream; AGC kept
    fighting it. Redundant with the one-time fix applied at deploy time
    (`alsactl store`), but cheap insurance against AGC getting
    re-enabled by some other path (a factory reset, a driver reload).
    The USB mic has its own 'Auto Gain Control' that behaves the same way.
    """
    profile = _capture_profile()
    if profile is None:
        return False
    card, control, agc_control = profile
    _disable_agc(card, agc_control)
    return _amixer_on(card, "sset", control, "nocap" if muted else "cap") is not None


def _disable_agc(card: str, agc_control: str | None) -> None:
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
    if agc_control is None:
        return
    _amixer_on(card, "sset", agc_control, "off")
