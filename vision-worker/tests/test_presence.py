"""Tests for MotionPresenceDetector, originally moved verbatim from
tests/unit/test_vision_stubs.py (src/lumi/vision/presence.py) when the
real detector relocated into the vision-worker process (2026-07-06) —
the worker is the only place a real camera frame ever exists.

Extended 2026-08-05 for the stillness latch (see presence.py's module
docstring for the flicker bug it fixes). Time is passed in explicitly, so
the latch is testable without sleeping.
"""

from __future__ import annotations

import numpy as np
from lumi_vision_worker.presence import MotionPresenceDetector

_STILL = np.zeros((240, 320, 3), dtype=np.uint8)
_MOVED = np.full((240, 320, 3), 200, dtype=np.uint8)


def test_motion_presence_no_motion() -> None:
    detector = MotionPresenceDetector()
    # Two identical frames → no motion
    detector.is_present(0.0, _STILL)
    result = detector.is_present(0.1, _STILL)
    assert result is False


def test_motion_presence_detects_change() -> None:
    # Use min_area=1 so any pixel change counts as presence
    detector = MotionPresenceDetector(min_area=1)
    detector.is_present(0.0, _STILL)
    result = detector.is_present(0.1, _MOVED)
    assert result is True


def test_motion_presence_first_frame_returns_false() -> None:
    # First call: no prior frame to compare → not present yet
    detector = MotionPresenceDetector()
    result = detector.is_present(0.0, _STILL)
    assert result is False


# ── The stillness latch ─────────────────────────────────────────────────


def test_stillness_shorter_than_window_stays_present() -> None:
    """The actual flicker bug: someone sitting still must NOT read as
    absent one frame after they stop moving."""
    detector = MotionPresenceDetector(min_area=1, absent_after_s=20.0)
    detector.is_present(0.0, _STILL)
    assert detector.is_present(0.1, _MOVED) is True

    # 19s of dead-still frames — one frame short of the window. Before the
    # latch this flipped to False on the very first still frame.
    t = 0.2
    while t < 19.0:
        assert detector.is_present(t, _MOVED) is True, f"went absent at t={t}"
        t += 0.0625  # ~16 fps, the rate the Pi actually holds


def test_goes_absent_after_sustained_stillness() -> None:
    detector = MotionPresenceDetector(min_area=1, absent_after_s=5.0)
    detector.is_present(0.0, _STILL)
    assert detector.is_present(1.0, _MOVED) is True  # motion at t=1.0

    assert detector.is_present(5.9, _MOVED) is True   # 4.9s still — not yet
    assert detector.is_present(6.0, _MOVED) is False  # 5.0s still — absent


def test_motion_relatches_present_immediately() -> None:
    """Present is instant, absent is slow — the asymmetry is the point."""
    detector = MotionPresenceDetector(min_area=1, absent_after_s=5.0)
    detector.is_present(0.0, _STILL)
    detector.is_present(1.0, _MOVED)
    assert detector.is_present(6.5, _MOVED) is False  # dozed off

    # Any single frame of motion wakes it back up with no delay.
    assert detector.is_present(7.0, _STILL) is True


def test_motion_resets_the_stillness_clock() -> None:
    """Stillness must be *continuous* — intermittent motion keeps Lumi
    awake indefinitely, which is the safe failure direction."""
    detector = MotionPresenceDetector(min_area=1, absent_after_s=5.0)
    detector.is_present(0.0, _STILL)

    # A twitch every 4s, forever — never 5s of continuous stillness.
    frame = _MOVED
    for i in range(1, 20):
        t = float(i) * 4.0
        assert detector.is_present(t, frame) is True, f"went absent at t={t}"
        frame = _STILL if frame is _MOVED else _MOVED


def test_latch_is_frame_rate_independent() -> None:
    """The window is wall-clock, not frame-counted, so a slow frame rate
    doesn't make Lumi doze off sooner."""
    for fps in (5.0, 16.0, 30.0):
        detector = MotionPresenceDetector(min_area=1, absent_after_s=5.0)
        detector.is_present(0.0, _STILL)
        detector.is_present(0.5, _MOVED)  # motion at t=0.5

        step = 1.0 / fps
        t = 0.5 + step
        while t < 5.4:  # still inside the window at every frame rate
            assert detector.is_present(t, _MOVED) is True, f"absent at {fps}fps, t={t}"
            t += step


def test_last_frame_had_motion_exposes_unlatched_signal() -> None:
    detector = MotionPresenceDetector(min_area=1, absent_after_s=20.0)
    detector.is_present(0.0, _STILL)

    detector.is_present(0.1, _MOVED)
    assert detector.last_frame_had_motion is True

    # Latched present, but this frame itself had no motion.
    assert detector.is_present(0.2, _MOVED) is True
    assert detector.last_frame_had_motion is False
