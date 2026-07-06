"""Tests for the ALSA mixer wrapper backing the device-display's on-screen
volume slider and mic-mute button. All `amixer` calls are mocked — these
tests run on a laptop with no ReSpeaker card present."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

from lumi.hardware import audio_mixer


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
    sget_output = (
        "Simple mixer control 'PCM',0\n"
        "  Front Left: Playback 71 [56%] [-27.50dB]\n"
        "  Front Right: Playback 71 [56%] [-27.50dB]\n"
    )
    with patch("subprocess.run", return_value=_fake_run(0, sget_output)):
        assert audio_mixer.get_volume() == 56


def test_get_volume_defaults_to_50_when_unavailable() -> None:
    with patch("subprocess.run", side_effect=FileNotFoundError):
        assert audio_mixer.get_volume() == 50


def test_set_volume_clamps_range() -> None:
    with patch("subprocess.run", return_value=_fake_run(0)) as mock_run:
        audio_mixer.set_volume(150)
        args = mock_run.call_args[0][0]
        assert args[-1] == "100%"

        audio_mixer.set_volume(-10)
        args = mock_run.call_args[0][0]
        assert args[-1] == "0%"


def test_set_volume_targets_pcm_control_on_named_card() -> None:
    """Regression test for the real "volume controls don't work" bug
    found on the Pi (2026-07-06): the slider used to target "HP", whose
    entire range is only 0dB to +9dB — even at its lowest setting, HP
    still passes signal at unity gain, not silence, so the slider's full
    travel was a barely-audible 9dB swing. "PCM" spans a real -63.5dB to
    0dB, confirmed directly on the card — that's the control that
    actually behaves like a volume knob."""
    with patch("subprocess.run", return_value=_fake_run(0)) as mock_run:
        audio_mixer.set_volume(42)
        args = mock_run.call_args[0][0]
        assert args == ["amixer", "-c", "seeed2micvoicec", "sset", "PCM", "42%"]


def test_set_volume_also_maxes_hp_boost() -> None:
    """HP is left as a fixed +9dB headroom boost, not user-adjustable —
    set_volume() must keep it maxed on every call as insurance against
    it drifting down and silently re-capping PCM's effective range,
    which is exactly the bug this whole fix addresses."""
    with patch("subprocess.run", return_value=_fake_run(0)) as mock_run:
        audio_mixer.set_volume(42)
        all_calls = [c.args[0] for c in mock_run.call_args_list]
        assert ["amixer", "-c", "seeed2micvoicec", "sset", "HP", "100%"] in all_calls


def test_get_mic_muted_true_when_switch_off() -> None:
    sget_output = (
        "Simple mixer control 'PGA',0\n"
        "  Front Left: Capture 0 [0%] [0.00dB] [off]\n"
    )
    with patch("subprocess.run", return_value=_fake_run(0, sget_output)):
        assert audio_mixer.get_mic_muted() is True


def test_get_mic_muted_false_when_switch_on() -> None:
    sget_output = (
        "Simple mixer control 'PGA',0\n"
        "  Front Left: Capture 60 [50%] [10.00dB] [on]\n"
    )
    with patch("subprocess.run", return_value=_fake_run(0, sget_output)):
        assert audio_mixer.get_mic_muted() is False


def test_get_mic_muted_false_when_card_unavailable() -> None:
    with patch("subprocess.run", side_effect=FileNotFoundError):
        assert audio_mixer.get_mic_muted() is False


def test_set_mic_muted_targets_pga_control() -> None:
    """PGA is a *capture*-type switch (cswitch), not a playback switch —
    amixer rejects `mute`/`unmute` on it ("Invalid command!"); the correct
    keywords for a capture switch are `nocap` (mute) / `cap` (unmute),
    confirmed against the real card."""
    with patch("subprocess.run", return_value=_fake_run(0)) as mock_run:
        audio_mixer.set_mic_muted(True)
        args = mock_run.call_args[0][0]
        assert args == ["amixer", "-c", "seeed2micvoicec", "sset", "PGA", "nocap"]

        audio_mixer.set_mic_muted(False)
        args = mock_run.call_args[0][0]
        assert args == ["amixer", "-c", "seeed2micvoicec", "sset", "PGA", "cap"]


def test_set_mic_muted_also_disables_agc() -> None:
    """Regression test for a real bug found on the Pi (2026-07-05): PGA's
    own mute switch alone did NOT silence the capture stream — AGC
    (Automatic Gain Control) kept cranking gain trying to hit its target
    level against near-silence, regardless of PGA's mute state. Directly
    measured: muting PGA alone still left the capture stream at 33% of
    samples above 0.9 amplitude; disabling AGC together with PGA's mute
    produced true silence (peak=0.0, rms=0.0). set_mic_muted() must
    disable AGC on every call, whether muting or unmuting — it's cheap
    insurance against AGC being re-enabled by some other path, not
    conditional on the mute direction."""
    with patch("subprocess.run", return_value=_fake_run(0)) as mock_run:
        audio_mixer.set_mic_muted(True)
        all_calls = [c.args[0] for c in mock_run.call_args_list]
        assert ["amixer", "-c", "seeed2micvoicec", "sset", "AGC", "off"] in all_calls

        mock_run.reset_mock()
        audio_mixer.set_mic_muted(False)
        all_calls = [c.args[0] for c in mock_run.call_args_list]
        assert ["amixer", "-c", "seeed2micvoicec", "sset", "AGC", "off"] in all_calls


def test_amixer_timeout_returns_none() -> None:
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="amixer", timeout=3)):
        assert audio_mixer.set_volume(50) is False
        assert audio_mixer.get_volume() == 50
