"""Presence detection — frame-diff motion detector with a stillness latch.

Moved here (2026-07-06) from src/lumi/vision/presence.py: the worker
process is the only place a real camera frame ever exists, so this is
where the real detector belongs. The Protocol/mock scaffolding from the
original location doesn't carry over — the worker only ever runs the
real detector (mocking, if ever needed, happens at the test boundary by
calling is_present() directly with synthetic arrays, same as
tests/test_presence.py already does).

**Latch added 2026-08-05, fixing a live flicker bug.** The original
detector answered "was there motion between the last two frames?" and
main.py pushed /api/presence on every change of that answer. A person
sitting still read as *absent* one frame later, so the answer oscillated
frame-to-frame and the Pi's journal showed bursts of ~6 POST /api/presence
per second. Each of those is an HTTP round-trip plus a DeviceBus publish,
and DeviceBus rebroadcasts the FULL merged snapshot to every SSE
subscriber — so the kiosk was re-rendering constantly, and App.tsx's
`sleeping` flag (which reads presence raw, no debounce) made the face
blink between awake and the closed-eyes/"Zzz" treatment while the user
sat right in front of it. Exactly the opposite of the calm the sleep
treatment is for.

The fix is deliberately asymmetric, because the two failure directions
are not equally bad:

  - Falsely *absent* — Lumi dozes off in your face. Very visible, and the
    bug we had. Guarded by `absent_after_s`: motion latches "present" and
    it takes a sustained run of stillness to clear.
  - Falsely *present* — Lumi stays awake when the desk is empty. Nearly
    invisible (App.tsx already treats "no reading yet" as present so a
    fresh boot doesn't start asleep), and self-corrects the moment the
    stillness window elapses.

So the present side stays instant and the absent side is slow. The
default 20s is generous on purpose: someone who has genuinely walked away
is away for minutes, so there is no cost to being slow to sleep, while
being quick to sleep is precisely what looked broken. It also has to
clear a person reading their screen without moving much, which is easily
5-10s of near-stillness.

The window is time-based (a monotonic clock passed in by the caller), not
frame-counted, so it behaves the same at the 16 fps the Pi actually holds
as it would at 30. Same explicit-`t` convention as wave.py's push().
"""

from __future__ import annotations

import numpy as np


class MotionPresenceDetector:
    """Frame-diff motion detector with a stillness latch: any motion means
    present immediately, and it takes `absent_after_s` of continuous
    stillness to fall back to absent. See the module docstring for why the
    two directions are deliberately asymmetric."""

    def __init__(
        self,
        threshold: float = 25.0,
        min_area: int = 5000,
        absent_after_s: float = 20.0,
    ) -> None:
        self._threshold = threshold
        self._min_area = min_area
        self._absent_after_s = absent_after_s
        self._prev: np.ndarray | None = None
        self._last_motion_at: float | None = None
        self._present = False
        # Raw (unlatched) motion from the most recent is_present() call.
        # Read-only for callers — exposed as an attribute rather than a
        # second method on purpose: _had_motion() consumes the previous
        # frame to diff against, so a separate public accessor would
        # diff a frame against itself when called alongside is_present()
        # on the same frame and always report False.
        self.last_frame_had_motion = False

    def is_present(self, t: float, frame: np.ndarray) -> bool:
        """Call once per frame with the frame's monotonic timestamp.
        Returns the latched presence state, not this frame's raw motion —
        read `last_frame_had_motion` for the unlatched signal."""
        self.last_frame_had_motion = self._had_motion(frame)
        if self.last_frame_had_motion:
            self._last_motion_at = t
            self._present = True
        elif (
            self._present
            and self._last_motion_at is not None
            and t - self._last_motion_at >= self._absent_after_s
        ):
            self._present = False
        return self._present

    def _had_motion(self, frame: np.ndarray) -> bool:
        gray = self._to_gray(frame)
        if self._prev is None:
            # No prior frame to diff against — can't claim motion yet.
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
