"""Tests for MotionPresenceDetector, moved verbatim from
tests/unit/test_vision_stubs.py (src/lumi/vision/presence.py) when the
real detector relocated into the vision-worker process (2026-07-06) —
the worker is the only place a real camera frame ever exists."""

from __future__ import annotations

import numpy as np
from lumi_vision_worker.presence import MotionPresenceDetector


def test_motion_presence_no_motion() -> None:
    detector = MotionPresenceDetector()
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    # Two identical frames → no motion
    detector.is_present(frame)
    result = detector.is_present(frame)
    assert result is False


def test_motion_presence_detects_change() -> None:
    # Use min_area=1 so any pixel change counts as presence
    detector = MotionPresenceDetector(min_area=1)
    frame_a = np.zeros((240, 320, 3), dtype=np.uint8)
    frame_b = np.full((240, 320, 3), 200, dtype=np.uint8)
    detector.is_present(frame_a)
    result = detector.is_present(frame_b)
    assert result is True


def test_motion_presence_first_frame_returns_false() -> None:
    # First call: no prior frame to compare → not present yet
    detector = MotionPresenceDetector()
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    result = detector.is_present(frame)
    assert result is False
