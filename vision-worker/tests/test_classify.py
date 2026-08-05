"""Synthetic-landmark tests for classify.py — no camera, no Pi, no
mediapipe needed. Runs in milliseconds."""

from __future__ import annotations

from lumi_vision_worker.classify import GestureType, Hand, classify_static_pose


def _straight_finger(x: float, base_y: float) -> list[tuple[float, float, float]]:
    """mcp, pip, dip, tip on a straight line pointing "up" (smaller y) —
    extended. Four points, matching MediaPipe's real per-finger layout
    (mcp/pip/dip/tip) even though classify.py's angle test only reads
    mcp/pip/tip — dip still needs to occupy the correct index slot."""
    return [
        (x, base_y, 0.0),
        (x, base_y - 1.0, 0.0),
        (x, base_y - 1.5, 0.0),
        (x, base_y - 2.0, 0.0),
    ]


def _curled_finger(x: float, base_y: float) -> list[tuple[float, float, float]]:
    """mcp, pip, dip, tip folded back toward the palm — curled."""
    return [
        (x, base_y, 0.0),
        (x, base_y - 1.0, 0.0),
        (x, base_y - 0.95, 0.0),
        (x, base_y - 0.9, 0.0),
    ]


def _make_hand(
    *,
    fingers_extended: bool,
    thumb_offset: float = 0.0,
) -> Hand:
    """Build a full 21-point hand. fingers_extended controls index/middle/
    ring/pinky (all four together, matching classify_static_pose's
    all-or-nothing check). thumb_offset is added to the thumb tip's y,
    scaled the same way _thumb_vertical_offset expects (negative = up)."""
    # base_y=1.0 puts MCPs at y=1.0, so hand_size (wrist->mcp[9] distance) is exactly 1.0.
    wrist = (0.5, 2.0, 0.0)

    finger_builder = _straight_finger if fingers_extended else _curled_finger
    index = finger_builder(0.45, 1.0)
    middle = finger_builder(0.5, 1.0)
    ring = finger_builder(0.55, 1.0)
    pinky = finger_builder(0.6, 1.0)

    palm_cy = 1.0  # all four MCPs share y=1.0 above, so centroid is exactly 1.0
    hand_size = 1.0  # wrist.y (2.0) - mcp[9].y (1.0) = 1.0, by construction
    thumb_tip_y = palm_cy + thumb_offset * hand_size
    thumb = [(0.3, 1.8, 0.0), (0.25, 1.6, 0.0), (0.2, 1.4, 0.0), (0.2, thumb_tip_y, 0.0)]

    hand: Hand = [wrist, *thumb, *index, *middle, *ring, *pinky]
    mediapipe_landmark_count = 21
    assert len(hand) == mediapipe_landmark_count
    return hand


def test_open_palm() -> None:
    hand = _make_hand(fingers_extended=True)
    assert classify_static_pose(hand) == GestureType.OPEN_PALM


def test_fist() -> None:
    hand = _make_hand(fingers_extended=False, thumb_offset=0.0)
    assert classify_static_pose(hand) == GestureType.FIST


def test_thumbs_up() -> None:
    hand = _make_hand(fingers_extended=False, thumb_offset=-0.6)
    assert classify_static_pose(hand) == GestureType.THUMBS_UP


def test_thumbs_down() -> None:
    hand = _make_hand(fingers_extended=False, thumb_offset=0.6)
    assert classify_static_pose(hand) == GestureType.THUMBS_DOWN


def test_mixed_fingers_is_none() -> None:
    """Not all curled, not all extended — no confident classification."""
    wrist = (0.5, 2.0, 0.0)
    index = _straight_finger(0.45, 1.0)
    middle = _curled_finger(0.5, 1.0)
    ring = _straight_finger(0.55, 1.0)
    pinky = _curled_finger(0.6, 1.0)
    thumb = [(0.3, 1.8, 0.0), (0.25, 1.6, 0.0), (0.2, 1.4, 0.0), (0.2, 1.0, 0.0)]
    hand: Hand = [wrist, *thumb, *index, *middle, *ring, *pinky]
    assert classify_static_pose(hand) == GestureType.NONE
