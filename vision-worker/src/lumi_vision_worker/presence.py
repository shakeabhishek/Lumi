"""Presence detection — frame-diff motion detector, no ML.

Moved here (2026-07-06) from src/lumi/vision/presence.py: the worker
process is the only place a real camera frame ever exists, so this is
where the real detector belongs. The Protocol/mock scaffolding from the
original location doesn't carry over — the worker only ever runs the
real detector (mocking, if ever needed, happens at the test boundary by
calling is_present() directly with synthetic arrays, same as
tests/test_presence.py already does).
"""

from __future__ import annotations

import numpy as np


class MotionPresenceDetector:
    """Compares successive frames; sustained motion above threshold = present."""

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
