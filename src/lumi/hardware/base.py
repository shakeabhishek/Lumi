"""Abstract hardware interfaces.

The whole point of this layer: the runtime is written against these interfaces
only. Laptop dev plugs in `pygame`/`sounddevice` implementations; the Pi build
plugs in SPI/ALSA/libcamera/libcomposite implementations. Swap == driver change,
not a rewrite.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Protocol

import numpy as np


@dataclass(frozen=True)
class Frame:
    """A rendered face frame, ready to display.

    `pixels` is HxWx3 uint8 RGB. Resolution matches the target display
    (480x320 for V1 Waveshare 3.5" SPI).
    """

    pixels: np.ndarray


class Display(ABC):
    """Surface Lumi's face is shown on."""

    @property
    @abstractmethod
    def size(self) -> tuple[int, int]:
        """(width, height) in pixels."""

    @abstractmethod
    def show(self, frame: Frame) -> None: ...

    @abstractmethod
    def close(self) -> None: ...


class AudioInput(ABC):
    """Microphone input."""

    @property
    @abstractmethod
    def sample_rate(self) -> int: ...

    @abstractmethod
    def record(self, duration_s: float) -> np.ndarray:
        """Block, return a (samples,) float32 array in [-1, 1]."""


class AudioOutput(ABC):
    """Speaker output."""

    @abstractmethod
    def play(self, audio: np.ndarray, sample_rate: int) -> None:
        """Block until audio is done playing."""


class Camera(ABC):
    """Vision input."""

    @abstractmethod
    def capture(self) -> np.ndarray | None:
        """Return one HxWx3 uint8 RGB frame, or None if the camera is unavailable."""

    @abstractmethod
    def close(self) -> None: ...


class GPIO(Protocol):
    """Minimal GPIO surface — buttons + LEDs. No-op on laptop."""

    def set(self, pin: int, value: bool) -> None: ...
    def get(self, pin: int) -> bool: ...


class USBGadget(Protocol):
    """USB composite device — HID + Mass Storage + CDC. Real impl is libcomposite on Pi."""

    def setup(self) -> None: ...
    def teardown(self) -> None: ...
    def send_text(self, text: str) -> None: ...
