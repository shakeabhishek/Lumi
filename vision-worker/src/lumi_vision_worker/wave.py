"""Stateful WAVE gesture detector.

Wave = "hand held roughly open, wrist oscillating side to side" — needs a
short rolling history, so unlike classify.py's per-frame poses, this
cannot be a pure stateless function. Still zero imports outside the
standard library (plus classify.py, itself stdlib-only).
"""

from __future__ import annotations

from collections import deque

from .classify import GestureType, Hand, hand_size

# Need enough samples for a reversal-count/amplitude check to be meaningful.
_MIN_HISTORY_FOR_REVERSAL_CHECK = 6


class WaveDetector:
    """Feed one frame at a time via push(); returns True the frame a wave
    should fire. Call classify_static_pose() first and pass its result in
    — a wave is a more specific, intentional signal than a held-open palm,
    so when this returns True the caller should treat the frame's
    *effective* gesture as WAVE, overriding OPEN_PALM."""

    def __init__(
        self,
        window_s: float = 1.2,
        min_reversals: int = 2,
        min_amplitude_hand_size_mult: float = 0.6,
    ) -> None:
        self._window_s = window_s
        self._min_reversals = min_reversals
        self._min_amp = min_amplitude_hand_size_mult
        self._history: deque[tuple[float, float, float]] = deque()  # (t, wrist_x, hand_size)

    def push(self, t: float, hand: Hand, static_pose: GestureType) -> bool:
        """Call once per frame with the frame timestamp, the 21
        landmarks, and this frame's classify_static_pose() result."""
        size = hand_size(hand)
        self._history.append((t, hand[0][0], size))
        while self._history and t - self._history[0][0] > self._window_s:
            self._history.popleft()

        if static_pose not in (GestureType.OPEN_PALM, GestureType.NONE):
            # A fist/thumb mid-wave shouldn't suppress it, but a
            # differently-curled pose doesn't count as wave motion.
            return False
        if len(self._history) < _MIN_HISTORY_FOR_REVERSAL_CHECK:
            return False

        xs = [x for _, x, _ in self._history]
        reversals = sum(
            1
            for i in range(1, len(xs) - 1)
            if (xs[i] - xs[i - 1]) * (xs[i + 1] - xs[i]) < 0
        )
        amplitude = (max(xs) - min(xs)) / size
        return reversals >= self._min_reversals and amplitude >= self._min_amp
