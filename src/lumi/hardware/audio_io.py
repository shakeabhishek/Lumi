"""Audio I/O implementations using `sounddevice` (PortAudio).

Works identically on macOS / Linux laptops and on the Pi once ALSA is configured
for the ReSpeaker HAT. No code change needed for the hardware swap — just pick
the right device via env / settings.
"""

from __future__ import annotations

import numpy as np

from ..audio.resample import pick_capture_rate, resample_to_target
from ..log import get_logger
from .base import AudioInput, AudioOutput

log = get_logger(__name__)


class SoundDeviceInput(AudioInput):
    """Mic capture, always returning audio at `sample_rate` regardless of what
    the hardware can actually do.

    The indirection earns its keep since the mic moved to USB (2026-08-05):
    that device rejects 16 kHz outright, and both Whisper and openwakeword
    require exactly 16 kHz. So the stream is opened at whatever rate the
    device accepts and converted down — see audio/resample.py, including why
    naive decimation would quietly wreck wake-word accuracy.

    The capture rate is probed once and cached, not per-record: probing opens
    and closes a PortAudio stream, which on ALSA is slow enough to notice at
    the front of every turn.
    """

    def __init__(self, sample_rate: int = 16000, device: str | None = None) -> None:
        self._sample_rate = sample_rate
        self._device = device
        self._capture_rate: int | None = None

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    def _resolve_capture_rate(self) -> int:
        if self._capture_rate is None:
            self._capture_rate = pick_capture_rate(self._device, self._sample_rate)
        return self._capture_rate

    def record(self, duration_s: float) -> np.ndarray:
        import sounddevice as sd  # noqa: PLC0415

        capture_rate = self._resolve_capture_rate()
        log.debug(
            "recording", duration_s=duration_s, sr=self._sample_rate,
            capture_sr=capture_rate,
        )
        try:
            samples = sd.rec(
                int(duration_s * capture_rate),
                samplerate=capture_rate,
                channels=1,
                dtype="float32",
                device=self._device,
            )
            sd.wait()
        except Exception:
            # Drop the cached rate so the next attempt re-probes.
            #
            # This matters because an ALSA `hw:` device that's currently held
            # by another process doesn't just refuse to open — it disappears
            # from PortAudio's device list entirely (observed on the Pi
            # 2026-08-05: the USB mic vanished while lumi-voice held the wake
            # stream). pick_capture_rate() then finds nothing to probe and
            # falls back to the target rate, which is precisely the rate this
            # mic can't do. Caching that would wedge capture permanently on a
            # transient conflict.
            self._capture_rate = None
            raise
        return resample_to_target(samples.flatten(), capture_rate, self._sample_rate)


class SoundDeviceOutput(AudioOutput):
    def __init__(self, device: str | None = None) -> None:
        self._device = device

    def play(self, audio: np.ndarray, sample_rate: int) -> None:
        import sounddevice as sd  # noqa: PLC0415

        if audio.dtype != np.float32:
            audio = audio.astype(np.float32)
        sd.play(audio, samplerate=sample_rate, device=self._device)
        sd.wait()


def list_devices() -> str:
    """Pretty-printed list of available audio devices. Helpful for setup."""
    import sounddevice as sd  # noqa: PLC0415

    return str(sd.query_devices())
