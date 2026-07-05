"""Tests for PiperTTS.speak() — persistent PiperVoice, not a subprocess.

`piper-tts` isn't installed in this dev environment (pyproject.toml
deliberately skips it on Apple Silicon — spotty wheel availability,
degrades to MacSayTTS instead) — so these tests inject a fake `piper`
module into sys.modules rather than importing the real package, the
same pattern test_wake_word.py uses for openwakeword.

Regression coverage for three real bugs found on the Pi (2026-07-05):
1. Playing back through a separate `aplay` process after any prior
   sounddevice/PortAudio capture in the same process caused "audio open
   error" and then hung the whole voice loop waiting on the wedged
   player. Fixed by routing playback through sounddevice (the same
   library used for capture) instead.
2. Even at 100% hardware volume, speech sounded "very low" — Piper's
   peak amplitude was already at full scale but RMS (average loudness)
   was much lower. Fixed with a loudness normalization step
   (_boost_loudness) that raises the average level to a target RMS,
   softly saturating any overflowing peaks via tanh.
3. "Sound starts 4-5s after the animation/caption." Measured: spawning a
   fresh `piper` CLI subprocess per sentence paid ~3.5s+ of process-
   startup + ONNX-model-load overhead on EVERY sentence — a 4x longer
   sentence only took 1.5x longer, ruling out per-character cost as the
   bottleneck. Fixed by loading the model ONCE via PiperVoice.load()
   (lazily, on first speak()) and reusing it for the rest of the
   process's lifetime — measured per-call time dropped from ~4s to
   ~0.4-0.7s once the model was already resident.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from lumi.audio.tts import PiperTTS


@pytest.fixture
def voice_dir(tmp_path: Path) -> Path:
    (tmp_path / "test-voice.onnx").write_bytes(b"fake-onnx-content")
    return tmp_path


@dataclass
class _FakeChunk:
    """Stand-in for piper.AudioChunk — just the fields PiperTTS reads."""

    audio_float_array: np.ndarray
    sample_rate: int = 22050


def _fake_piper_module(fake_voice: MagicMock) -> MagicMock:
    """A fake `piper` module whose PiperVoice.load() returns fake_voice."""
    fake_module = MagicMock()
    fake_module.PiperVoice.load.return_value = fake_voice
    return fake_module


def _fake_voice(chunks: list[_FakeChunk]) -> MagicMock:
    voice = MagicMock()
    voice.synthesize.return_value = chunks
    return voice


def test_speak_empty_text_is_noop(voice_dir: Path) -> None:
    fake_module = _fake_piper_module(_fake_voice([]))
    with patch.dict(sys.modules, {"piper": fake_module}):
        tts = PiperTTS("test-voice", voice_dir)
        tts.speak("")
    fake_module.PiperVoice.load.assert_not_called()


def test_speak_missing_model_raises(tmp_path: Path) -> None:
    tts = PiperTTS("nonexistent-voice", tmp_path)
    with pytest.raises(FileNotFoundError, match="Piper voice not found"):
        tts.speak("hello")


def test_speak_plays_via_sounddevice(voice_dir: Path) -> None:
    chunk = _FakeChunk(audio_float_array=np.array([0.0, 0.5, -0.5], dtype=np.float32))
    fake_voice = _fake_voice([chunk])
    fake_module = _fake_piper_module(fake_voice)

    with patch.dict(sys.modules, {"piper": fake_module}), \
         patch("sounddevice.play") as mock_play, \
         patch("sounddevice.wait") as mock_wait:
        tts = PiperTTS("test-voice", voice_dir, output_device="seeed2micvoicec")
        tts.speak("hello world")

    fake_module.PiperVoice.load.assert_called_once_with(str(voice_dir / "test-voice.onnx"))
    fake_voice.synthesize.assert_called_once_with("hello world")

    mock_play.assert_called_once()
    played_samples, kwargs = mock_play.call_args
    assert played_samples[0].dtype == np.float32
    assert kwargs["samplerate"] == 22050
    assert kwargs["device"] == "seeed2micvoicec"
    mock_wait.assert_called_once()


def test_speak_no_chunks_does_not_call_play(voice_dir: Path) -> None:
    fake_module = _fake_piper_module(_fake_voice([]))
    with patch.dict(sys.modules, {"piper": fake_module}), \
         patch("sounddevice.play") as mock_play:
        tts = PiperTTS("test-voice", voice_dir)
        tts.speak("hello")
    mock_play.assert_not_called()


def test_model_loaded_once_and_reused_across_speak_calls(voice_dir: Path) -> None:
    """The whole point of the 2026-07-05 fix: PiperVoice.load() must be
    called at most once per PiperTTS instance, not once per sentence —
    that fixed load cost is exactly what was causing the 4-5s delay."""
    chunk = _FakeChunk(audio_float_array=np.array([0.1], dtype=np.float32))
    fake_voice = _fake_voice([chunk])
    fake_module = _fake_piper_module(fake_voice)

    with patch.dict(sys.modules, {"piper": fake_module}), \
         patch("sounddevice.play"), patch("sounddevice.wait"):
        tts = PiperTTS("test-voice", voice_dir)
        tts.speak("first sentence")
        tts.speak("second sentence")
        tts.speak("third sentence")

    fake_module.PiperVoice.load.assert_called_once()
    assert fake_voice.synthesize.call_count == 3


def test_speak_concatenates_multiple_chunks(voice_dir: Path) -> None:
    """synthesize() can yield one chunk per sentence within a single
    speak() call (Piper's own internal sentence splitting) — all chunks
    for that call must be concatenated into one continuous playback."""
    chunks = [
        _FakeChunk(audio_float_array=np.array([0.1, 0.2], dtype=np.float32)),
        _FakeChunk(audio_float_array=np.array([0.3, 0.4], dtype=np.float32)),
    ]
    fake_module = _fake_piper_module(_fake_voice(chunks))

    with patch.dict(sys.modules, {"piper": fake_module}), \
         patch("sounddevice.play") as mock_play, patch("sounddevice.wait"):
        tts = PiperTTS("test-voice", voice_dir)
        tts.speak("two sentences here")

    played_samples = mock_play.call_args[0][0]
    assert len(played_samples) == 4


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


def test_boost_loudness_does_not_amplify_near_silence() -> None:
    """A window at/below the silence floor (e.g. the gap between words)
    must NOT get gained up toward the target RMS — otherwise the noise
    floor between words would get boosted into audible hiss. Left
    essentially unchanged instead."""
    near_silence = np.full(4096, 0.005, dtype=np.float32)
    boosted = PiperTTS._boost_loudness(near_silence)
    np.testing.assert_allclose(boosted, near_silence, atol=1e-3)


def test_boost_loudness_boosts_quiet_windows_more_than_loud_ones() -> None:
    """Core behavior of the windowed compressor: a quiet-but-real-speech
    segment (above the silence floor) must get a LARGER gain applied
    than an already-loud segment — a single static gain for the whole
    clip can't do this, which is why the first two passes at this fix
    still sounded "very low" even after raising the target repeatedly."""
    quiet_segment = np.full(2048, 0.05, dtype=np.float32)
    loud_segment = np.full(2048, 0.5, dtype=np.float32)
    samples = np.concatenate([quiet_segment, loud_segment])

    boosted = PiperTTS._boost_loudness(samples)
    quiet_out_rms = np.sqrt(np.mean(boosted[:2048] ** 2))
    loud_out_rms = np.sqrt(np.mean(boosted[2048:] ** 2))
    quiet_gain = quiet_out_rms / 0.05
    loud_gain = loud_out_rms / 0.5

    assert quiet_gain > loud_gain, "quiet window should receive more gain than the loud one"


def test_boost_loudness_leaves_silence_untouched() -> None:
    """Silence (RMS ~0) must not trigger a divide-by-zero / huge gain blowup."""
    silence = np.zeros(1000, dtype=np.float32)
    boosted = PiperTTS._boost_loudness(silence)
    np.testing.assert_array_equal(boosted, silence)


def test_speak_applies_loudness_boost_before_playback(voice_dir: Path) -> None:
    """End-to-end: speak() must run Piper's raw output through the
    loudness boost, not play the (quiet) synthesized samples directly."""
    quiet = np.full(1000, 0.03, dtype=np.float32)
    chunk = _FakeChunk(audio_float_array=quiet)
    fake_module = _fake_piper_module(_fake_voice([chunk]))

    with patch.dict(sys.modules, {"piper": fake_module}), \
         patch("sounddevice.play") as mock_play, patch("sounddevice.wait"):
        tts = PiperTTS("test-voice", voice_dir)
        tts.speak("quiet")

    original_rms = np.sqrt(np.mean(quiet**2))
    played_samples = mock_play.call_args[0][0]
    played_rms = np.sqrt(np.mean(played_samples**2))
    assert played_rms > original_rms * 10, "quiet speech should be boosted substantially"
