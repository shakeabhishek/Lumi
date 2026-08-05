"""Sample-rate conversion for the capture path.

Why this exists: Lumi's mic moved to a **USB mic** (2026-08-05), and it does
not support 16 kHz — only 44.1 and 48 kHz (probed directly on the device:
`sd.check_input_settings(samplerate=16000)` raises `Invalid sample rate
[PaErrorCode -9997]`). Both consumers downstream require exactly 16 kHz:

  - **openwakeword** — hard requirement. Its melspectrogram frontend is
    trained at 16 kHz and takes 1280-sample (80 ms) frames. Feeding it 48 kHz
    audio doesn't error, it just quietly destroys accuracy.
  - **Whisper** — expects 16 kHz; faster-whisper resamples internally but
    only if it's told the true rate, which the old code wasn't doing.

The previous ReSpeaker path never needed this because the HAT's codec ran
natively at 16 kHz. (That HAT now reports `max_input_channels=0` — it's
output-only in the current build, which is why the USB mic exists at all.)

**Naive decimation is wrong here** and worth being explicit about: taking
every 3rd sample of a 48 kHz stream folds everything above 8 kHz back down
into the audible band as alias garbage. On a wake-word frontend that reads as
a mysterious accuracy regression rather than an obvious bug, so the
anti-aliasing low-pass below is not optional polish.

Deliberately no new dependency. 48 kHz → 16 kHz is an exact 3:1 integer
ratio, handled with a numpy-only windowed-sinc FIR, which is the path the
device actually runs. scipy's `resample_poly` is used when the ratio isn't
an integer (e.g. 44.1 kHz) and scipy happens to be installed — it is on the
Pi today, but nothing here requires it, so no lockfile churn (see AGENTS.md
on the protobuf/opentelemetry lesson about touching the lock).
"""

from __future__ import annotations

from math import gcd

import numpy as np

from ..log import get_logger

log = get_logger(__name__)

TARGET_RATE = 16000

# Odd length so the filter is symmetric with an integer group delay. 63 taps
# at 48 kHz is ~1.3 ms of delay — irrelevant against openwakeword's 80 ms
# frame, and cheap enough to run per-frame on the Pi's CPU (63 multiplies per
# output sample, ~1M/sec at 16 kHz out).
_FIR_TAPS = 63


def _lowpass_kernel(cutoff_normalized: float, taps: int = _FIR_TAPS) -> np.ndarray:
    """Windowed-sinc low-pass FIR. `cutoff_normalized` is the cutoff as a
    fraction of the INPUT sample rate (so 1/6 for 8 kHz out of 48 kHz)."""
    n = np.arange(taps, dtype=np.float64) - (taps - 1) / 2.0
    # sinc already carries the 1/pi normalisation; np.sinc(x) == sin(pi x)/(pi x)
    kernel = 2.0 * cutoff_normalized * np.sinc(2.0 * cutoff_normalized * n)
    kernel *= np.hamming(taps)
    total = kernel.sum()
    if total != 0:
        kernel /= total  # unity DC gain, so loudness is unchanged
    return kernel.astype(np.float32)


def _decimation_kernel(factor: int) -> np.ndarray:
    # Cutoff just under Nyquist of the OUTPUT rate, with a little margin so
    # the transition band lands below fold-over rather than straddling it.
    return _lowpass_kernel(0.5 / factor * 0.9)


def _decimate_integer(samples: np.ndarray, factor: int) -> np.ndarray:
    """Anti-aliased integer-ratio decimation, numpy only. One-shot: the
    zero-padded edges of `mode="same"` are a negligible fraction of a
    multi-second clip. For a continuous block-wise stream use StreamResampler,
    which carries filter state instead."""
    filtered = np.convolve(samples, _decimation_kernel(factor), mode="same")
    return filtered[::factor].astype(np.float32)


class StreamResampler:
    """Stateful resampler for a continuous, block-at-a-time capture stream.

    Exists because the one-shot path is subtly wrong for streaming. Convolving
    each block independently with `mode="same"` zero-pads both ends, so every
    block boundary gets a step discontinuity. On the wake-word stream that's a
    click at every 80 ms frame — 12.5 clicks a second of broadband energy fed
    straight into a model whose whole job is spotting a short acoustic pattern.
    It wouldn't look like a bug, just an unexplained accuracy drop.

    So filter state carries across blocks (overlap-save): the tail of the
    previous input is prepended and the convolution runs `mode="valid"`, which
    is mathematically identical to filtering one unbroken stream.

    Only integer ratios are stateful. The fractional path (44.1 kHz) defers to
    scipy per block and keeps the boundary caveat — acceptable because the
    device is configured to 48 kHz precisely so the integer path is what runs;
    see pick_capture_rate's ordering.

    Output carries a constant group delay of (taps-1)/2 input samples relative
    to the one-shot `resample_to_target` (~0.65 ms at 48 kHz), because valid
    convolution over history can't peek at future samples the way centred
    `mode="same"` does. Removing it would cost a full block of latency for no
    benefit: a fixed sub-millisecond offset is invisible to both the wake-word
    frontend and Whisper, neither of which cares about absolute alignment.
    """

    def __init__(self, source_rate: int, target_rate: int = TARGET_RATE) -> None:
        self.source_rate = source_rate
        self.target_rate = target_rate
        self._passthrough = source_rate == target_rate
        self._factor = source_rate // target_rate if source_rate % target_rate == 0 else 0
        self._kernel = _decimation_kernel(self._factor) if self._factor else None
        # (taps - 1) samples of history is exactly what 'valid' convolution
        # needs to produce len(block) outputs with no zero-padding.
        self._history = (
            np.zeros(len(self._kernel) - 1, dtype=np.float32)
            if self._kernel is not None
            else np.zeros(0, dtype=np.float32)
        )

    def process(self, block: np.ndarray) -> np.ndarray:
        """Resample one captured block. Block length should be a multiple of
        the decimation factor so the output stride stays phase-continuous
        across calls — 3840 at 48 kHz gives exactly 1280 out, which is what
        openwakeword wants per frame."""
        if self._passthrough:
            return np.asarray(block, dtype=np.float32).flatten()

        samples = np.asarray(block, dtype=np.float32).flatten()
        if self._kernel is None:
            # Fractional ratio — stateless per block, boundary caveat above.
            return resample_to_target(samples, self.source_rate, self.target_rate)

        padded = np.concatenate((self._history, samples))
        filtered = np.convolve(padded, self._kernel, mode="valid")
        self._history = padded[-(len(self._kernel) - 1):]
        return filtered[:: self._factor].astype(np.float32)

    def reset(self) -> None:
        """Drop filter history — call when the stream restarts, so stale audio
        from before the gap doesn't bleed into the first new block."""
        self._history = np.zeros_like(self._history)


def resample_to_target(
    samples: np.ndarray, source_rate: int, target_rate: int = TARGET_RATE,
) -> np.ndarray:
    """Convert mono float32 `samples` from `source_rate` to `target_rate`.

    Passthrough when the rates already match, so callers can wire this in
    unconditionally without paying for it on hardware that captures at 16 kHz
    natively (the old ReSpeaker path, and most laptops).
    """
    if source_rate == target_rate:
        return samples.astype(np.float32, copy=False)
    if source_rate < target_rate:
        # Upsampling a mic is never what we want — it can't add detail a
        # 16 kHz-hungry model needs, and silently pretending otherwise would
        # hide a misconfigured device.
        raise ValueError(
            f"capture rate {source_rate} Hz is below the required "
            f"{target_rate} Hz; pick a device that supports at least that",
        )

    samples = np.asarray(samples, dtype=np.float32).flatten()

    if source_rate % target_rate == 0:
        return _decimate_integer(samples, source_rate // target_rate)

    # Non-integer ratio (44.1 kHz being the realistic case). scipy's
    # polyphase resampler handles the fractional rate properly.
    divisor = gcd(source_rate, target_rate)
    up, down = target_rate // divisor, source_rate // divisor
    try:
        from scipy.signal import resample_poly  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - scipy present on the Pi
        raise RuntimeError(
            f"resampling {source_rate} Hz -> {target_rate} Hz needs a "
            f"non-integer ratio ({up}/{down}), which requires scipy. Either "
            f"install scipy or configure the device to capture at a multiple "
            f"of {target_rate} Hz (48000 works and needs no scipy).",
        ) from exc
    return np.asarray(resample_poly(samples, up, down), dtype=np.float32)


def pick_capture_rate(
    device: str | int | None, target_rate: int = TARGET_RATE,
) -> int:
    """Choose the rate to actually open the input stream at.

    Prefers `target_rate` (no conversion at all), then exact multiples of it
    (integer decimation, no scipy needed), then anything the device accepts.
    Falls back to `target_rate` if the device can't be probed, so laptops and
    tests behave as before.
    """
    import sounddevice as sd  # noqa: PLC0415

    # 48000 before 44100 on purpose: it's an exact 3x of 16 kHz, so it stays
    # on the dependency-free integer path.
    for rate in (target_rate, 48000, 44100, 32000, 96000):
        try:
            sd.check_input_settings(
                device=device, samplerate=rate, channels=1, dtype="float32",
            )
        except Exception:  # PortAudio raises several unrelated types here
            continue
        if rate != target_rate:
            log.info(
                "audio.capture_rate_selected",
                device=str(device),
                capture_rate=rate,
                target_rate=target_rate,
                reason=f"device rejected {target_rate} Hz",
            )
        return rate

    log.warning(
        "audio.capture_rate_probe_failed",
        device=str(device),
        falling_back_to=target_rate,
    )
    return target_rate
