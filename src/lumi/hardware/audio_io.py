"""Audio I/O implementations using `sounddevice` (PortAudio).

Works identically on macOS / Linux laptops and on the Pi once ALSA is configured
for the ReSpeaker HAT. No code change needed for the hardware swap — just pick
the right device via env / settings.
"""

from __future__ import annotations

import numpy as np

from ..log import get_logger
from .base import AudioInput, AudioOutput

log = get_logger(__name__)


class SoundDeviceInput(AudioInput):
    def __init__(self, sample_rate: int = 16000, device: str | None = None) -> None:
        self._sample_rate = sample_rate
        self._device = device

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    def record(self, duration_s: float) -> np.ndarray:
        import sounddevice as sd  # noqa: PLC0415

        log.debug("recording", duration_s=duration_s, sr=self._sample_rate)
        samples = sd.rec(
            int(duration_s * self._sample_rate),
            samplerate=self._sample_rate,
            channels=1,
            dtype="float32",
            device=self._device,
        )
        sd.wait()
        return samples.flatten()


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
