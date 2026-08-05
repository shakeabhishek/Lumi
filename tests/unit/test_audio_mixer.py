"""Tests for the ALSA mixer wrapper backing the device-display's on-screen
volume slider and mic-mute button. All `amixer` calls are mocked — these
tests run on a laptop with no ReSpeaker card present."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from lumi.hardware import audio_mixer


@pytest.fixture(autouse=True)
def _reset_capture_profile_cache():
    """The capture-card probe is cached module-wide (deliberately — see
    test_capture_probe_is_cached), so it has to be cleared between tests or
    the first one to run decides the mic for all the others."""
    audio_mixer.reset_capture_profile_cache()
    yield
    audio_mixer.reset_capture_profile_cache()


def _fake_run(returncode: int = 0, stdout: str = "") -> object:
    result = subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout)
    return result


def test_is_available_true_when_amixer_succeeds() -> None:
    with patch("subprocess.run", return_value=_fake_run(0, "Simple mixer control 'HP',0\n")):
        assert audio_mixer.is_available() is True


def test_is_available_false_when_amixer_missing() -> None:
    with patch("subprocess.run", side_effect=FileNotFoundError):
        assert audio_mixer.is_available() is False


def test_get_volume_parses_percent() -> None:
    """Raw PCM percentage from amixer must come back through the
    slider-space remapping (see _pcm_percent_to_slider), not the raw
    PCM percentage directly — 88% raw PCM (above the audible floor of
    75%) is slider position 52."""
    sget_output = (
        "Simple mixer control 'PCM',0\n"
        "  Front Left: Playback 111 [88%] [-7.50dB]\n"
        "  Front Right: Playback 111 [88%] [-7.50dB]\n"
    )
    with patch("subprocess.run", return_value=_fake_run(0, sget_output)):
        assert audio_mixer.get_volume() == 52


def test_get_volume_defaults_to_50_when_unavailable() -> None:
    with patch("subprocess.run", side_effect=FileNotFoundError):
        assert audio_mixer.get_volume() == 50


def test_set_volume_clamps_range() -> None:
    """0-100 slider input clamps before remapping onto PCM's [75, 100]
    audible sub-range — slider 0 maps to PCM's floor (75%), not raw 0%,
    since raw 0% (-63.5dB) was found to be inaudible on this hardware."""
    with patch("subprocess.run", return_value=_fake_run(0)) as mock_run:
        audio_mixer.set_volume(150)
        args = mock_run.call_args[0][0]
        assert args[-1] == "100%"

        audio_mixer.set_volume(-10)
        args = mock_run.call_args[0][0]
        assert args[-1] == "75%"


def test_set_volume_targets_pcm_control_on_named_card() -> None:
    """Regression test for the real "volume controls don't work" bug
    found on the Pi (2026-07-06): the slider used to target "HP", whose
    entire range is only 0dB to +9dB — even at its lowest setting, HP
    still passes signal at unity gain, not silence, so the slider's full
    travel was a barely-audible 9dB swing. "PCM" spans a real -63.5dB to
    0dB, confirmed directly on the card — that's the control that
    actually behaves like a volume knob. Slider position 50 maps to raw
    PCM 88% (75-floor sub-range, not a direct 1:1 percentage)."""
    with patch("subprocess.run", return_value=_fake_run(0)) as mock_run:
        audio_mixer.set_volume(50)
        args = mock_run.call_args[0][0]
        assert args == ["amixer", "-c", "seeed2micvoicec", "sset", "PCM", "88%"]


def test_slider_to_pcm_percent_stays_within_audible_floor() -> None:
    """Regression test for the real "anything below 90% is inaudible"
    bug found on the Pi (2026-07-06): PCM's raw scale is roughly linear
    in dB, not perceived loudness, so a naive 1:1 slider-to-PCM mapping
    crammed nearly all the audible range into the last ~10% of slider
    travel. The slider's full 0-100 range must now map onto PCM's
    [_PCM_FLOOR_PERCENT, 100] sub-range instead, so even slider position
    0 stays at the empirically-found audible floor rather than
    continuing down into PCM's practically-silent territory."""
    assert audio_mixer._slider_to_pcm_percent(0) == audio_mixer._PCM_FLOOR_PERCENT
    assert audio_mixer._slider_to_pcm_percent(100) == 100
    # Monotonic — a higher slider position must never map to a lower
    # (quieter) PCM percentage.
    values = [audio_mixer._slider_to_pcm_percent(s) for s in range(0, 101, 10)]
    assert values == sorted(values)


def test_pcm_percent_to_slider_is_inverse_of_slider_to_pcm() -> None:
    """Approximate, not exact — two independent integer roundings (one
    per direction) can compound to an off-by-one, which is an
    acceptable, expected characteristic of a quantized percentage
    round-trip, not a real bug."""
    for slider in (0, 25, 50, 75, 100):
        pcm = audio_mixer._slider_to_pcm_percent(slider)
        assert abs(audio_mixer._pcm_percent_to_slider(pcm) - slider) <= 2


def test_pcm_percent_below_floor_maps_to_slider_zero() -> None:
    """Raw PCM percentages below the audible floor (e.g. read from a
    stale/manually-set hardware value) must clamp to slider 0, not go
    negative."""
    assert audio_mixer._pcm_percent_to_slider(10) == 0


def test_set_volume_also_maxes_boost_controls() -> None:
    """HP and HP DAC are left as fixed headroom boosts, not user-
    adjustable — set_volume() must keep both maxed on every call.
    Regression test for a real bug found on the Pi (2026-07-06): "HP
    DAC" was discovered sitting at 55% (-26.5dB) the whole time, a
    completely separate gain stage nobody had ever touched, silently
    capping overall loudness regardless of what PCM or HP were set to
    — exactly the kind of hidden-control bug this maxing sweep guards
    against for both controls, not just HP."""
    with patch("subprocess.run", return_value=_fake_run(0)) as mock_run:
        audio_mixer.set_volume(42)
        all_calls = [c.args[0] for c in mock_run.call_args_list]
        assert ["amixer", "-c", "seeed2micvoicec", "sset", "HP", "100%"] in all_calls
        assert ["amixer", "-c", "seeed2micvoicec", "sset", "HP DAC", "100%"] in all_calls


# ── Mic mute: capture card is DISCOVERED, not hardcoded ──────────────────
#
# Playback and capture live on different cards since 2026-08-05: the mic moved
# to USB and the ReSpeaker went output-only (max_input_channels=0, bare PGA
# control gone). The old hardcoded PGA path pointed at a control that no longer
# exists, so the on-screen mic button silently stopped muting anything. See
# audio_mixer's _CAPTURE_PROFILES.

_USB_MIC_SGET = (
    "Simple mixer control 'Mic',0\n"
    "  Capabilities: cvolume cvolume-joined cswitch cswitch-joined\n"
    "  Mono: Capture 27 [90%] [28.50dB] [on]\n"
)
_USB_MIC_SGET_MUTED = (
    "Simple mixer control 'Mic',0\n"
    "  Capabilities: cvolume cvolume-joined cswitch cswitch-joined\n"
    "  Mono: Capture 0 [0%] [0.00dB] [off]\n"
)
_RESPEAKER_PGA_SGET = (
    "Simple mixer control 'PGA',0\n"
    "  Capabilities: cvolume cswitch\n"
    "  Front Left: Capture 60 [50%] [10.00dB] [on]\n"
)
# What amixer prints for a control with no capture switch — can't be muted.
_PLAYBACK_ONLY_SGET = (
    "Simple mixer control 'PCM',0\n"
    "  Capabilities: pvolume\n"
    "  Front Left: Playback 111 [88%] [-7.50dB]\n"
)


def _route(**by_control: str):
    """Fake subprocess.run that answers `sget <control>` per control name and
    succeeds silently for everything else, so discovery can be steered."""
    def run(cmd, *a, **kw):
        if "sget" in cmd:
            control = cmd[cmd.index("sget") + 1]
            if control in by_control:
                return _fake_run(0, by_control[control])
            return _fake_run(1, "")  # control absent on this card
        return _fake_run(0)
    return run


def test_discovers_the_usb_mic_when_present() -> None:
    with patch("subprocess.run", side_effect=_route(Mic=_USB_MIC_SGET)):
        assert audio_mixer.is_mic_control_available() is True
        audio_mixer.set_mic_muted(True)


def test_mute_targets_the_usb_mic_card_and_control() -> None:
    with patch("subprocess.run", side_effect=_route(Mic=_USB_MIC_SGET)) as mock_run:
        audio_mixer.set_mic_muted(True)
        calls = [c.args[0] for c in mock_run.call_args_list]
        assert ["amixer", "-c", "Device", "sset", "Mic", "nocap"] in calls

        audio_mixer.set_mic_muted(False)
        calls = [c.args[0] for c in mock_run.call_args_list]
        assert ["amixer", "-c", "Device", "sset", "Mic", "cap"] in calls


def test_falls_back_to_respeaker_pga_when_no_usb_mic() -> None:
    """Reverting the mic hardware must need no code change."""
    with patch("subprocess.run", side_effect=_route(PGA=_RESPEAKER_PGA_SGET)) as mock_run:
        audio_mixer.set_mic_muted(True)
        calls = [c.args[0] for c in mock_run.call_args_list]
        assert ["amixer", "-c", "seeed2micvoicec", "sset", "PGA", "nocap"] in calls


def test_ignores_a_control_that_cannot_actually_be_muted() -> None:
    """A control with no `cswitch` can't be muted. Accepting it would give us a
    mute button that appears to work and does nothing — the exact failure this
    whole discovery step exists to prevent."""
    with patch("subprocess.run", side_effect=_route(Mic=_PLAYBACK_ONLY_SGET)):
        assert audio_mixer.is_mic_control_available() is False
        assert audio_mixer.set_mic_muted(True) is False


def test_disables_agc_on_whichever_card_owns_the_mic() -> None:
    """Regression test for a real bug found on the Pi (2026-07-05): PGA's own
    mute switch alone did NOT silence the capture stream — AGC kept cranking
    gain against near-silence regardless of the mute state (33% of samples
    above 0.9 amplitude; disabling AGC alongside gave true silence, peak=0.0).
    Must fire on every call, whether muting or unmuting. The USB mic's
    equivalent is named 'Auto Gain Control'."""
    with patch("subprocess.run", side_effect=_route(Mic=_USB_MIC_SGET)) as mock_run:
        audio_mixer.set_mic_muted(True)
        calls = [c.args[0] for c in mock_run.call_args_list]
        assert ["amixer", "-c", "Device", "sset", "Auto Gain Control", "off"] in calls

        mock_run.reset_mock()
        audio_mixer.set_mic_muted(False)
        calls = [c.args[0] for c in mock_run.call_args_list]
        assert ["amixer", "-c", "Device", "sset", "Auto Gain Control", "off"] in calls


def test_get_mic_muted_true_when_switch_off() -> None:
    with patch("subprocess.run", side_effect=_route(Mic=_USB_MIC_SGET_MUTED)):
        assert audio_mixer.get_mic_muted() is True


def test_get_mic_muted_false_when_switch_on() -> None:
    with patch("subprocess.run", side_effect=_route(Mic=_USB_MIC_SGET)):
        assert audio_mixer.get_mic_muted() is False


def test_get_mic_muted_false_when_no_card_available() -> None:
    """Dev laptop: no cards at all. Must report unmuted rather than crash."""
    with patch("subprocess.run", side_effect=FileNotFoundError):
        assert audio_mixer.get_mic_muted() is False
        assert audio_mixer.is_mic_control_available() is False


def test_capture_probe_is_cached() -> None:
    """Probing shells out per candidate card; doing that on every mute toggle
    would put two subprocess spawns in the path of an on-screen button tap."""
    with patch("subprocess.run", side_effect=_route(Mic=_USB_MIC_SGET)) as mock_run:
        audio_mixer.is_mic_control_available()
        probe_calls = len([c for c in mock_run.call_args_list if "sget" in c.args[0]])
        mock_run.reset_mock()
        audio_mixer.is_mic_control_available()
        audio_mixer.is_mic_control_available()
        again = len([c for c in mock_run.call_args_list if "sget" in c.args[0]])
        assert probe_calls >= 1
        assert again == 0, "profile should be resolved once and cached"


def test_amixer_timeout_returns_none() -> None:
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="amixer", timeout=3)):
        assert audio_mixer.set_volume(50) is False
        assert audio_mixer.get_volume() == 50
