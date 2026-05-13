"""Presence detection — auto-wake when user sits down, sleep when they leave.

Real implementation in Phase 5 uses Pi Camera Module 3 + a lightweight
motion/face detector. On laptop, MockPresenceDetector always reports present.
"""

from __future__ import annotations

from typing import Protocol

import numpy as np


class PresenceDetector(Protocol):
    def is_present(self, frame: np.ndarray) -> bool:
        """Return True if a person is detected in the frame."""
        ...


class MockPresenceDetector:
    """Always present — used on laptop before camera hardware arrives."""

    def is_present(self, frame: np.ndarray) -> bool:
        return True


class MotionPresenceDetector:
    """Frame-diff motion detector — no ML, runs on Pi CPU.

    Compares successive frames; sustained motion above threshold = present.
    Phase 5 may upgrade to a lightweight face detector for better accuracy.
    """

    def __init__(self, threshold: float = 25.0, min_area: int = 5000) -> None:
        self._threshold = threshold
        self._min_area = min_area
        self._prev: np.ndarray | None = None

    def is_present(self, frame: np.ndarray) -> bool:
        gray = self._to_gray(frame)
        if self._prev is None:
            self._prev = gray
            return False
        diff = np.abs(gray.astype(np.int16) - self._prev.astype(np.int16))
        self._prev = gray
        changed_pixels = int(np.sum(diff > self._threshold))
        return changed_pixels >= self._min_area

    @staticmethod
    def _to_gray(frame: np.ndarray) -> np.ndarray:
        # Approximate luminance: 0.299R + 0.587G + 0.114B
        return (
            frame[:, :, 0] * 0.299 + frame[:, :, 1] * 0.587 + frame[:, :, 2] * 0.114
        ).astype(np.uint8)


def make_presence_detector(mock: bool = True) -> PresenceDetector:
    if mock:
        return MockPresenceDetector()
    return MotionPresenceDetector()
