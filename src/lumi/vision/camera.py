"""Camera abstraction — protocol + mock for laptop dev, real implementation in Phase 5."""

from __future__ import annotations

from typing import Protocol

import numpy as np


class Camera(Protocol):
    def capture_frame(self) -> np.ndarray:
        """Capture one frame. Returns HxWx3 uint8 RGB array."""
        ...

    def start(self) -> None:
        """Begin streaming frames."""
        ...

    def stop(self) -> None:
        """Release camera resources."""
        ...

    @property
    def resolution(self) -> tuple[int, int]:
        """(width, height) in pixels."""
        ...


class MockCamera:
    """Returns blank frames. Used on laptop before real hardware arrives."""

    def __init__(self, width: int = 480, height: int = 320) -> None:
        self._w = width
        self._h = height
        self._running = False

    def start(self) -> None:
        self._running = True

    def stop(self) -> None:
        self._running = False

    @property
    def resolution(self) -> tuple[int, int]:
        return self._w, self._h

    def capture_frame(self) -> np.ndarray:
        return np.zeros((self._h, self._w, 3), dtype=np.uint8)


class LibCameraCamera:
    """Pi Camera Module 3 via libcamera-still/libcamera-vid.

    Stubbed — wired up in Phase 5 when the Pi and Camera Module 3 arrive.
    """

    def __init__(self, width: int = 1536, height: int = 864) -> None:
        self._w = width
        self._h = height

    def start(self) -> None:
        raise NotImplementedError("LibCameraCamera — implement in Phase 5")

    def stop(self) -> None:
        pass

    @property
    def resolution(self) -> tuple[int, int]:
        return self._w, self._h

    def capture_frame(self) -> np.ndarray:
        raise NotImplementedError("LibCameraCamera — implement in Phase 5")


def make_camera(mock: bool = True) -> Camera:
    if mock:
        return MockCamera()
    return LibCameraCamera()
