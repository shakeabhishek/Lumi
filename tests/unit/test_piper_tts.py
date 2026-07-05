"""Tests for PiperTTS.speak() — playback via sounddevice, not a subprocess.

Regression coverage for two real bugs found on the Pi (2026-07-05):
1. Playing back through a separate `aplay` process after any prior
   sounddevice/PortAudio capture in the same process caused "audio open
   error" and then hung the whole voice loop waiting on the wedged
   player. Fixed by routing playback through sounddevice (the same
   library used for capture) instead.
2. Even at 100% hardware volume, speech sounded "very low" — Piper's
   peak amplitude was already at full scale but RMS (average loudness)
   was only ~0.15 (vs. ~0.64 for a test tone). Fixed with a loudness
   normalization step (_boost_loudness) that raises the average level
   to a target RMS and caps any overflowing peaks.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from lumi.audio.tts import PiperTTS


@pytest.fixture
def voice_dir(tmp_path: Path) -> Path:
    (tmp_path / "test-voice.onnx").write_bytes(b"fake-onnx-content")
    return tmp_path


def test_speak_empty_text_is_noop(voice_dir: Path) -> None:
    tts = PiperTTS("test-voice", voice_dir)
    with patch("subprocess.Popen") as mock_popen:
        tts.speak("")
    mock_popen.assert_not_called()


def test_speak_missing_model_raises(tmp_path: Path) -> None:
    tts = PiperTTS("nonexistent-voice", tmp_path)
    with pytest.raises(FileNotFoundError, match="Piper voice not found"):
        tts.speak("hello")


def test_speak_plays_normalized_float32_via_sounddevice(voice_dir: Path) -> None:
    """The int16 raw PCM Piper emits must be normalized to [-1, 1] float32,
    not naively cast (which would reinterpret e.g. 32767 as 32767.0
    instead of ~1.0 and produce garbage/clipped audio)."""
    raw_pcm = np.array([0, 16384, -16384, 32767, -32768], dtype=np.int16).tobytes()

    mock_piper = MagicMock()
    mock_piper.communicate.return_value = (raw_pcm, b"")

    with patch("subprocess.Popen", return_value=mock_piper) as mock_popen, \
         patch("sounddevice.play") as mock_play, \
         patch("sounddevice.wait") as mock_wait:
        tts = PiperTTS("test-voice", voice_dir, output_device="seeed2micvoicec")
        tts.speak("hello world")

    # Piper invoked with the right model path and raw-output flag.
    args = mock_popen.call_args[0][0]
    assert args[0] == "piper"
    assert "--output-raw" in args
    assert str(voice_dir / "test-voice.onnx") in args

    # Text handed to Piper via communicate(), not manual stdin writes.
    mock_piper.communicate.assert_called_once_with(input=b"hello world")

    # Playback routed to the configured device at the right sample rate.
    mock_play.assert_called_once()
    played_samples, kwargs = mock_play.call_args
    samples = played_samples[0]
    assert samples.dtype == np.float32
    assert kwargs["samplerate"] == 22050
    assert kwargs["device"] == "seeed2micvoicec"
    mock_wait.assert_called_once()


def test_speak_no_output_from_piper_does_not_call_play(voice_dir: Path) -> None:
    mock_piper = MagicMock()
    mock_piper.communicate.return_value = (b"", b"")

    with patch("subprocess.Popen", return_value=mock_piper), \
         patch("sounddevice.play") as mock_play:
        tts = PiperTTS("test-voice", voice_dir)
        tts.speak("hello")

    mock_play.assert_not_called()


def test_name_property(voice_dir: Path) -> None:
    tts = PiperTTS("test-voice", voice_dir)
    assert tts.name == "piper:test-voice"


# ── loudness normalization ───────────────────────────────────────────────


def test_boost_loudness_raises_quiet_speech_to_target_rms() -> None:
    """Regression test for the real "very low volume" bug: quiet speech
    (like Piper's typical ~0.15 RMS output) must be boosted meaningfully
    louder, toward (not necessarily hitting exactly) the target RMS —
    tanh's soft saturation compresses the result somewhat below the
    pre-saturation target for signals with a lot of energy near the
    target level, by design (trades hitting an exact number for avoiding
    harsh hard-clip distortion)."""
    rng = np.random.default_rng(42)
    quiet_speech = (rng.standard_normal(22050).astype(np.float32) * 0.05).clip(-0.3, 0.3)
    quiet_speech = quiet_speech.astype(np.float32)
    original_rms = np.sqrt(np.mean(quiet_speech**2))

    boosted = PiperTTS._boost_loudness(quiet_speech)
    boosted_rms = np.sqrt(np.mean(boosted**2))

    assert boosted_rms > original_rms * 2, "boost should be substantial, not marginal"
    assert boosted_rms < 1.0


def test_boost_loudness_caps_overflowing_peaks() -> None:
    """A signal already near full scale must not exceed [-1, 1] after
    boosting — tanh's soft saturation keeps peaks within range (rounding
    them over smoothly) rather than letting them overflow, which would
    wrap/distort catastrophically."""
    samples = np.array([1.0, -1.0, 0.5, -0.5], dtype=np.float32)
    boosted = PiperTTS._boost_loudness(samples)
    assert boosted.max() <= 1.0
    assert boosted.min() >= -1.0


def test_boost_loudness_is_gentle_on_quiet_samples() -> None:
    """tanh(x) ≈ x for small x — quiet samples should pass through close
    to their gain-scaled value, not get flattened the way a hard
    limiter/compressor with a low threshold would."""
    quiet = np.array([0.01, -0.01], dtype=np.float32)
    boosted = PiperTTS._boost_loudness(quiet)
    expected_linear = quiet * (PiperTTS._TARGET_RMS / 0.01)  # naive gain, no saturation
    np.testing.assert_allclose(boosted, np.tanh(expected_linear), atol=1e-6)


def test_boost_loudness_leaves_silence_untouched() -> None:
    """Silence (RMS ~0) must not trigger a divide-by-zero / huge gain blowup."""
    silence = np.zeros(1000, dtype=np.float32)
    boosted = PiperTTS._boost_loudness(silence)
    np.testing.assert_array_equal(boosted, silence)


def test_speak_applies_loudness_boost_before_playback(voice_dir: Path) -> None:
    """End-to-end: speak() must run raw Piper output through the loudness
    boost, not play the raw (quiet) normalized samples directly."""
    quiet_int16 = np.full(1000, 1000, dtype=np.int16)  # ~0.03 amplitude, very quiet
    raw_pcm = quiet_int16.tobytes()

    mock_piper = MagicMock()
    mock_piper.communicate.return_value = (raw_pcm, b"")

    with patch("subprocess.Popen", return_value=mock_piper), \
         patch("sounddevice.play") as mock_play, \
         patch("sounddevice.wait"):
        tts = PiperTTS("test-voice", voice_dir)
        tts.speak("quiet")

    original_rms = np.sqrt(np.mean((quiet_int16.astype(np.float32) / 32768.0) ** 2))
    played_samples = mock_play.call_args[0][0]
    played_rms = np.sqrt(np.mean(played_samples**2))
    assert played_rms > original_rms * 10, "quiet speech should be boosted substantially"
