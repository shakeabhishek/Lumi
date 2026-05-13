"""Gesture vocabulary and detector stub.

V1 gesture set (from CLAUDE.md):
  WAVE        — wake / greet
  OPEN_PALM   — pause / stop talking
  THUMBS_UP   — yes / accept
  THUMBS_DOWN — no / reject
  FIST        — cancel / dismiss

Real implementation in Phase 5 uses MediaPipe Hand Landmarks on the AI HAT+ 2.
On laptop, MockGestureDetector always returns NONE.
"""

from __future__ import annotations

from enum import Enum
from typing import Protocol

import numpy as np


class GestureType(Enum):
    NONE = "none"
    WAVE = "wave"
    OPEN_PALM = "open_palm"
    THUMBS_UP = "thumbs_up"
    THUMBS_DOWN = "thumbs_down"
    FIST = "fist"


class GestureDetector(Protocol):
    def detect(self, frame: np.ndarray) -> GestureType:
        """Infer gesture from a single RGB frame. Returns NONE if no hand visible."""
        ...


class MockGestureDetector:
    """No-op detector for laptop dev — always returns NONE."""

    def detect(self, frame: np.ndarray) -> GestureType:
        return GestureType.NONE


class MediaPipeGestureDetector:
    """MediaPipe Hand Landmarks + rule-based classifier on the AI HAT+ 2.

    Stubbed — wired up in Phase 5. Architecture:
      frame (HxWx3) → MediaPipe hand landmarks (21 keypoints) → classify() → GestureType
    """

    def __init__(self) -> None:
        raise NotImplementedError("MediaPipeGestureDetector — implement in Phase 5")

    def detect(self, frame: np.ndarray) -> GestureType:
        raise NotImplementedError

    @staticmethod
    def _classify(landmarks: list) -> GestureType:
        """Rule-based classifier from 21 hand keypoints. Implement in Phase 5."""
        raise NotImplementedError


def make_gesture_detector(mock: bool = True) -> GestureDetector:
    if mock:
        return MockGestureDetector()
    return MediaPipeGestureDetector()
