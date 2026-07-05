"""Tests for PiperTTS.speak() — playback via sounddevice, not a subprocess.

Regression coverage for a real bug found on the Pi (2026-07-05): playing
back through a separate `aplay` process after any prior sounddevice/
PortAudio capture in the same process caused "audio open error" and then
hung the whole voice loop waiting on the wedged player. Fixed by routing
playback through sounddevice (the same library used for capture) instead.
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

    # Playback normalized correctly and routed to the configured device.
    mock_play.assert_called_once()
    played_samples, kwargs = mock_play.call_args
    samples = played_samples[0]
    assert samples.dtype == np.float32
    np.testing.assert_allclose(samples, [0.0, 0.5, -0.5, 32767 / 32768, -1.0], atol=1e-4)
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
