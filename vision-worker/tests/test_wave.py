"""Synthetic tests for the stateful WaveDetector — no camera/mediapipe needed."""

from __future__ import annotations

from lumi_vision_worker.classify import GestureType, Hand
from lumi_vision_worker.wave import WaveDetector


def _hand_at(wrist_x: float) -> Hand:
    """A minimal 21-point hand — only wrist (index 0) and middle MCP
    (index 9) matter for WaveDetector (wrist_x for oscillation, the
    wrist-to-mcp[9] distance for hand_size normalization). The rest of
    the points are irrelevant filler since WaveDetector never inspects
    them directly (only classify.py's hand_size/static_pose do, and
    static_pose is passed in pre-computed here)."""
    hand: Hand = [(wrist_x, 1.0, 0.0)] + [(0.5, 0.5, 0.0)] * 20
    return hand


def test_wave_fires_on_oscillating_open_palm() -> None:
    detector = WaveDetector(window_s=2.0, min_reversals=2, min_amplitude_hand_size_mult=0.6)
    # Oscillate wrist_x back and forth with amplitude well above the
    # hand_size (0.5, per _hand_at's fixed wrist/mcp[9] positions —
    # hypot(0, 0.5) = 0.5) threshold of 0.6 * 0.5 = 0.3.
    xs = [0.5, 0.9, 0.5, 0.1, 0.5, 0.9, 0.5]
    fired = False
    for i, x in enumerate(xs):
        fired = detector.push(t=i * 0.1, hand=_hand_at(x), static_pose=GestureType.OPEN_PALM)
    assert fired, "wave should have fired after enough oscillation"


def test_wave_does_not_fire_on_still_hand() -> None:
    detector = WaveDetector(window_s=2.0)
    fired = False
    for i in range(10):
        fired = detector.push(t=i * 0.1, hand=_hand_at(0.5), static_pose=GestureType.OPEN_PALM)
    assert not fired


def test_wave_does_not_fire_on_fist() -> None:
    """Oscillating motion alone isn't enough — a curled fist waving
    around must not trigger WAVE (only OPEN_PALM/NONE count)."""
    detector = WaveDetector(window_s=2.0)
    xs = [0.5, 0.9, 0.5, 0.1, 0.5, 0.9, 0.5]
    fired = False
    for i, x in enumerate(xs):
        fired = detector.push(t=i * 0.1, hand=_hand_at(x), static_pose=GestureType.FIST)
    assert not fired


def test_wave_requires_minimum_history() -> None:
    """Too few frames (< 6) never fires, even with big oscillation."""
    detector = WaveDetector(window_s=2.0)
    fired = detector.push(t=0.0, hand=_hand_at(0.9), static_pose=GestureType.OPEN_PALM)
    assert not fired


def test_wave_history_expires_outside_window() -> None:
    """Old samples fall out of the rolling window — a wave that happened
    long ago shouldn't keep contributing reversals/amplitude forever."""
    detector = WaveDetector(window_s=0.5, min_reversals=2, min_amplitude_hand_size_mult=0.6)
    # Oscillate quickly within the window, then go still for longer than
    # window_s, then check a single still frame doesn't fire.
    xs = [0.5, 0.9, 0.5, 0.1, 0.5, 0.9, 0.5]
    for i, x in enumerate(xs):
        detector.push(t=i * 0.05, hand=_hand_at(x), static_pose=GestureType.OPEN_PALM)
    fired_later = detector.push(t=5.0, hand=_hand_at(0.5), static_pose=GestureType.OPEN_PALM)
    assert not fired_later, "stale oscillation history outside the window must not still count"
