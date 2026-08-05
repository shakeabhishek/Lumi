"""Pure gesture-pose classification from MediaPipe hand landmarks.

Deliberately zero imports outside the standard library — no mediapipe, no
numpy, no cv2. This is what makes it testable with synthetic landmark
coordinates in milliseconds, no camera/Pi/vision-worker-venv required.

`GestureType` is a local duplicate of `lumi.vision.gestures.GestureType`
(the main app's trimmed-down shared vocabulary), not an import — this
package cannot depend on the `lumi` distribution at all (see the plan's
"why push_gesture doesn't live in device_display_client.py" rationale;
the same reasoning applies here). Values are kept in sync by convention;
they're validated against each other at the wire boundary (a plain string
sent over HTTP), not by sharing a Python type across the process boundary.
"""

from __future__ import annotations

import math
from enum import Enum

# (x, y, z), MediaPipe normalized image coords — y grows downward.
Landmark = tuple[float, float, float]
Hand = list[Landmark]  # exactly 21 entries, MediaPipe's fixed index layout


class GestureType(Enum):
    NONE = "none"
    WAVE = "wave"
    OPEN_PALM = "open_palm"
    THUMBS_UP = "thumbs_up"
    THUMBS_DOWN = "thumbs_down"
    FIST = "fist"


# MediaPipe's 21-point hand landmark layout:
#   wrist=0; thumb CMC/MCP/IP/TIP=1-4; index MCP/PIP/DIP/TIP=5-8;
#   middle=9-12; ring=13-16; pinky=17-20.
_FOUR_FINGERS = ((5, 6, 8), (9, 10, 12), (13, 14, 16), (17, 18, 20))  # (mcp, pip, tip) per finger

_EXTENDED_ANGLE_DEG = 160.0  # near-straight
_CURLED_ANGLE_DEG = 100.0  # sharply bent
_THUMB_UP_OFFSET = -0.35  # thumb tip clearly above the palm centroid (scale-normalized)
_THUMB_DOWN_OFFSET = 0.35  # thumb tip clearly below


def _angle(a: Landmark, b: Landmark, c: Landmark) -> float:
    """Angle at b, in degrees, between vectors b->a and b->c."""
    v1 = (a[0] - b[0], a[1] - b[1])
    v2 = (c[0] - b[0], c[1] - b[1])
    dot = v1[0] * v2[0] + v1[1] * v2[1]
    mag = (math.hypot(*v1) * math.hypot(*v2)) or 1e-9
    return math.degrees(math.acos(max(-1.0, min(1.0, dot / mag))))


def _finger_extended(hand: Hand, mcp: int, pip: int, tip: int) -> bool:
    # PIP joint (not fingertip y-position) as the angle vertex makes this
    # orientation-independent — critical because a waving or thumbs-
    # sideways hand isn't upright in frame.
    return _angle(hand[mcp], hand[pip], hand[tip]) > _EXTENDED_ANGLE_DEG


def _finger_curled(hand: Hand, mcp: int, pip: int, tip: int) -> bool:
    return _angle(hand[mcp], hand[pip], hand[tip]) < _CURLED_ANGLE_DEG


def hand_size(hand: Hand) -> float:
    """Scale-normalization reference: wrist to middle-finger MCP distance,
    so the same thresholds work regardless of how close the hand is to
    the camera. Shared with wave.py, which needs the same normalization
    for its amplitude threshold."""
    return math.hypot(hand[9][0] - hand[0][0], hand[9][1] - hand[0][1]) or 1e-9


def _thumb_vertical_offset(hand: Hand) -> float:
    """Signed, scale-normalized vertical distance from thumb tip to the
    palm centroid (mean of the four MCPs). Negative = thumb tip is above
    the palm (up, since y grows downward); positive = below."""
    palm_cy = sum(hand[i][1] for i in (5, 9, 13, 17)) / 4
    return (hand[4][1] - palm_cy) / hand_size(hand)


def classify_static_pose(hand: Hand) -> GestureType:
    """NONE | OPEN_PALM | FIST | THUMBS_UP | THUMBS_DOWN for a single frame.

    WAVE is not decided here — it needs motion history (see wave.py).
    """
    curled = [_finger_curled(hand, *f) for f in _FOUR_FINGERS]
    extended = [_finger_extended(hand, *f) for f in _FOUR_FINGERS]
    thumb_off = _thumb_vertical_offset(hand)

    if all(curled):
        if thumb_off < _THUMB_UP_OFFSET:
            return GestureType.THUMBS_UP
        if thumb_off > _THUMB_DOWN_OFFSET:
            return GestureType.THUMBS_DOWN
        return GestureType.FIST
    if all(extended):
        return GestureType.OPEN_PALM
    return GestureType.NONE
