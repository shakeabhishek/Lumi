"""Tests for the shared gesture vocabulary (src/lumi/vision/gestures.py).

Detection itself moved out-of-process into vision-worker/ (see its own
tests/test_classify.py, tests/test_wave.py) — this enum is the shared
wire-format source of truth that context_api.py validates /api/gesture
payloads against.
"""

from __future__ import annotations

from lumi.vision.gestures import GestureType


def test_gesture_type_values() -> None:
    assert GestureType.NONE.value == "none"
    assert GestureType.WAVE.value == "wave"
    assert GestureType.OPEN_PALM.value == "open_palm"
    assert GestureType.THUMBS_UP.value == "thumbs_up"
    assert GestureType.THUMBS_DOWN.value == "thumbs_down"
    assert GestureType.FIST.value == "fist"
