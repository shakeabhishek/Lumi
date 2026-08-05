"""Tests for the capture-path resampler.

Why it exists: Lumi's mic moved to USB (2026-08-05) and that device rejects
16 kHz outright, while openwakeword and Whisper both require exactly 16 kHz.
See audio/resample.py.
"""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import numpy as np
import pytest

from lumi.audio.resample import (
    TARGET_RATE,
    StreamResampler,
    pick_capture_rate,
    resample_to_target,
)


def _tone(freq_hz: float, rate: int, duration_s: float = 0.25) -> np.ndarray:
    t = np.arange(int(rate * duration_s), dtype=np.float32) / rate
    return np.sin(2 * np.pi * freq_hz * t).astype(np.float32)


def _dominant_freq(samples: np.ndarray, rate: int) -> float:
    spectrum = np.abs(np.fft.rfft(samples.astype(np.float64)))
    return float(np.fft.rfftfreq(samples.size, d=1.0 / rate)[int(np.argmax(spectrum))])


def test_passthrough_when_rates_match() -> None:
    """Wiring this in unconditionally must cost nothing on hardware that
    already captures at 16 kHz (the old ReSpeaker path, and most laptops)."""
    samples = _tone(440, TARGET_RATE)
    out = resample_to_target(samples, TARGET_RATE, TARGET_RATE)
    assert np.array_equal(out, samples)


def test_48k_to_16k_length_is_exactly_one_third() -> None:
    out = resample_to_target(_tone(440, 48000, 0.5), 48000, TARGET_RATE)
    assert out.size == 48000 // 3 * 0.5 * 2 // 2 or abs(out.size - 8000) <= 1
    assert abs(out.size - 8000) <= 1


def test_48k_to_16k_preserves_an_in_band_tone() -> None:
    """A 440 Hz tone is well inside the 8 kHz output Nyquist, so it must come
    through at 440 Hz — not shifted, not attenuated away."""
    out = resample_to_target(_tone(440, 48000), 48000, TARGET_RATE)
    assert abs(_dominant_freq(out, TARGET_RATE) - 440) < 25


def test_48k_to_16k_rejects_out_of_band_tone_instead_of_aliasing_it() -> None:
    """The reason a naive `samples[::3]` is wrong, made concrete.

    A 12 kHz tone is above the 8 kHz output Nyquist. Plain decimation folds it
    to |16000 - 12000| = 4 kHz — a loud, entirely fabricated 4 kHz tone in the
    output. On a wake-word frontend that reads as a mysterious accuracy
    regression rather than an obvious bug, which is exactly why the
    anti-aliasing low-pass isn't optional polish.
    """
    source = _tone(12000, 48000)

    naive = source[::3]
    assert abs(_dominant_freq(naive, TARGET_RATE) - 4000) < 60, (
        "sanity check: naive decimation really does alias 12k down to 4k"
    )

    filtered = resample_to_target(source, 48000, TARGET_RATE)
    # Measured away from the ends: the one-shot path uses mode="same", whose
    # zero-padded edges are a step transient, not steady-state filter response.
    # (Those edges are exactly why the streaming path uses StreamResampler
    # instead — see test_stream_has_no_block_boundary_artifact.)
    steady = filtered[100:-100]
    assert np.max(np.abs(steady)) < 0.1 * np.max(np.abs(naive)), (
        "out-of-band energy should be filtered out, not aliased into the band"
    )


def test_unity_gain_so_loudness_is_unchanged() -> None:
    """A resampler that quietly halved the level would look like a broken mic
    and send someone hunting through the ALSA gain stages instead."""
    source = _tone(300, 48000)
    out = resample_to_target(source, 48000, TARGET_RATE)
    src_rms = float(np.sqrt(np.mean(source**2)))
    out_rms = float(np.sqrt(np.mean(out**2)))
    assert 0.8 < out_rms / src_rms < 1.2


def test_44100_to_16000_non_integer_ratio() -> None:
    """44.1 kHz is the other rate Lumi's USB mic offers. Needs scipy; skip
    rather than fail where it isn't installed, since the deployed path uses
    48 kHz precisely to avoid depending on it."""
    pytest.importorskip("scipy")
    out = resample_to_target(_tone(440, 44100), 44100, TARGET_RATE)
    assert abs(out.size - 4000) <= 2
    assert abs(_dominant_freq(out, TARGET_RATE) - 440) < 30


def test_silence_stays_silent() -> None:
    out = resample_to_target(np.zeros(4800, dtype=np.float32), 48000, TARGET_RATE)
    assert out.size > 0
    assert np.allclose(out, 0.0)


def test_output_is_float32() -> None:
    """Whisper and the int16 cast in the wake path both assume this."""
    assert resample_to_target(_tone(440, 48000), 48000, TARGET_RATE).dtype == np.float32


def test_upsampling_is_refused_rather_than_faked() -> None:
    """Upsampling can't add the detail a 16 kHz-hungry model needs, so a
    device that only does 8 kHz should surface as an error, not as quietly
    degraded wake-word accuracy."""
    with pytest.raises(ValueError, match="below the required"):
        resample_to_target(_tone(440, 8000), 8000, TARGET_RATE)


def test_accepts_a_2d_mono_block_from_sounddevice() -> None:
    """sd.rec() hands back shape (n, 1); the wake path also flattens, but the
    resampler shouldn't care either way."""
    block = _tone(440, 48000, 0.1).reshape(-1, 1)
    out = resample_to_target(block, 48000, TARGET_RATE)
    assert out.ndim == 1


# ── StreamResampler (the continuous wake-word path) ──────────────────────


def test_stream_output_is_independent_of_how_the_audio_is_chunked() -> None:
    """The defining property of correct overlap-save: the result must depend
    only on the audio, not on the block size PortAudio happens to hand us.

    Compared against a single big block rather than against resample_to_target,
    because the one-shot path uses mode="same" while streaming uses valid
    convolution over carried history — a constant ~31-input-sample group delay
    apart. That offset is inherent to streaming (and harmless at 0.65 ms), so
    an equality test against one-shot would only be asserting a convention.
    """
    source = _tone(440, 48000, 0.5)

    whole = StreamResampler(48000, TARGET_RATE).process(source)

    chunked = StreamResampler(48000, TARGET_RATE)
    block_len = 3840  # what the wake path reads per frame at 48 kHz
    pieces = [
        chunked.process(source[i:i + block_len])
        for i in range(0, len(source) - block_len + 1, block_len)
    ]
    streamed = np.concatenate(pieces)

    assert np.allclose(streamed, whole[: len(streamed)], atol=1e-6)


def test_stream_rejects_out_of_band_energy_too() -> None:
    """The anti-aliasing guarantee has to hold on the streaming path, not just
    the one-shot one — the streaming path is what the wake word actually uses."""
    source = _tone(12000, 48000, 0.5)
    streamer = StreamResampler(48000, TARGET_RATE)
    out = np.concatenate([
        streamer.process(source[i:i + 3840])
        for i in range(0, len(source) - 3839, 3840)
    ])
    # Skip the first block, which starts from zero filter history.
    assert np.max(np.abs(out[1280:])) < 0.1


def test_stream_preserves_an_in_band_tone_at_unity_gain() -> None:
    source = _tone(440, 48000, 0.5)
    streamer = StreamResampler(48000, TARGET_RATE)
    out = np.concatenate([
        streamer.process(source[i:i + 3840])
        for i in range(0, len(source) - 3839, 3840)
    ])
    steady = out[1280:]
    assert abs(_dominant_freq(steady, TARGET_RATE) - 440) < 25
    ratio = float(np.sqrt(np.mean(steady**2))) / float(np.sqrt(np.mean(source**2)))
    assert 0.8 < ratio < 1.2


def test_stream_has_no_block_boundary_artifact() -> None:
    """The bug StreamResampler exists to prevent. Filtering each block
    independently zero-pads both ends, putting a step discontinuity at every
    frame boundary — on the wake stream that's ~12.5 broadband clicks a second
    fed into the model. Carried filter state removes it.

    Checked on a steady tone: sample-to-sample deltas must stay smooth ACROSS
    a boundary, not spike there.
    """
    source = _tone(440, 48000, 0.5)
    block_len = 3840
    out_per_block = block_len // 3

    streamer = StreamResampler(48000, TARGET_RATE)
    streamed = np.concatenate([
        streamer.process(source[i:i + block_len])
        for i in range(0, len(source) - block_len + 1, block_len)
    ])

    deltas = np.abs(np.diff(streamed))
    typical = float(np.median(deltas))
    # Deltas straddling each internal block boundary.
    boundaries = [
        float(deltas[b - 1])
        for b in range(out_per_block, len(streamed), out_per_block)
        if b - 1 < len(deltas)
    ]
    assert boundaries, "expected at least one internal block boundary"
    assert max(boundaries) < typical * 4, (
        f"discontinuity at a block boundary: {max(boundaries):.5f} vs "
        f"typical {typical:.5f} — filter state isn't carrying across blocks"
    )


def test_stream_passthrough_when_rates_match() -> None:
    streamer = StreamResampler(TARGET_RATE, TARGET_RATE)
    block = _tone(440, TARGET_RATE, 0.08)
    assert np.array_equal(streamer.process(block), block)


def test_stream_block_yields_exactly_one_wake_frame() -> None:
    """openwakeword wants exactly 1280 samples per predict() call, and the
    wake path sizes its reads so one block in == one frame out."""
    streamer = StreamResampler(48000, TARGET_RATE)
    for _ in range(4):
        out = streamer.process(_tone(440, 48000, 3840 / 48000))
        assert out.size == 1280


def test_stream_reset_clears_history() -> None:
    """The wake stream stops and restarts once per turn (to free the mic for
    recording); stale audio from before the gap shouldn't bleed into the first
    block after it."""
    streamer = StreamResampler(48000, TARGET_RATE)
    streamer.process(_tone(440, 48000, 0.08) * 10.0)  # loud
    streamer.reset()
    out = streamer.process(np.zeros(3840, dtype=np.float32))
    assert np.allclose(out, 0.0, atol=1e-6)


# ── pick_capture_rate ────────────────────────────────────────────────────


def _fake_sd(accepted: set[int]):
    module = types.ModuleType("sounddevice")

    def check_input_settings(device=None, samplerate=None, channels=None, dtype=None):
        if samplerate not in accepted:
            raise ValueError(f"Invalid sample rate {samplerate}")

    module.check_input_settings = check_input_settings  # type: ignore[attr-defined]
    module.rec = MagicMock()  # type: ignore[attr-defined]
    return sys, module


def test_prefers_the_target_rate_when_the_device_supports_it(monkeypatch) -> None:
    sys, fake = _fake_sd({16000, 48000})
    monkeypatch.setitem(sys.modules, "sounddevice", fake)
    assert pick_capture_rate("anything") == 16000


def test_prefers_48k_over_44k_to_stay_on_the_scipy_free_path(monkeypatch) -> None:
    """48000 is an exact 3x of 16000, so integer decimation covers it with
    numpy alone. 44100 needs scipy. Order matters for that reason, not taste."""
    sys, fake = _fake_sd({44100, 48000})
    monkeypatch.setitem(sys.modules, "sounddevice", fake)
    assert pick_capture_rate("usb-mic") == 48000


def test_falls_back_to_44100_when_thats_all_there_is(monkeypatch) -> None:
    sys, fake = _fake_sd({44100})
    monkeypatch.setitem(sys.modules, "sounddevice", fake)
    assert pick_capture_rate("usb-mic") == 44100


def test_unprobeable_device_falls_back_to_target_rate(monkeypatch) -> None:
    """Laptops and tests must keep behaving exactly as before."""
    sys, fake = _fake_sd(set())
    monkeypatch.setitem(sys.modules, "sounddevice", fake)
    assert pick_capture_rate(None) == TARGET_RATE
