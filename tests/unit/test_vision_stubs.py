"""Tests for Camera, GestureDetector, and PresenceDetector stubs."""

from __future__ import annotations

import numpy as np
import pytest

from lumi.vision.camera import MockCamera, make_camera
from lumi.vision.gestures import GestureType, MockGestureDetector, make_gesture_detector
from lumi.vision.presence import MockPresenceDetector, MotionPresenceDetector, make_presence_detector


# ---------------------------------------------------------------------------
# Camera
# ---------------------------------------------------------------------------


def test_mock_camera_returns_frame() -> None:
    cam = MockCamera(width=320, height=240)
    frame = cam.capture_frame()
    assert frame.shape == (240, 320, 3)


def test_mock_camera_frame_is_zeros() -> None:
    cam = MockCamera(width=320, height=240)
    frame = cam.capture_frame()
    assert np.all(frame == 0)


def test_make_camera_mock_flag() -> None:
    cam = make_camera(mock=True)
    assert isinstance(cam, MockCamera)


def test_mock_camera_resolution() -> None:
    cam = MockCamera(width=320, height=240)
    assert cam.resolution == (320, 240)


# ---------------------------------------------------------------------------
# GestureDetector
# ---------------------------------------------------------------------------


def test_gesture_type_values() -> None:
    assert GestureType.NONE.value == "none"
    assert GestureType.WAVE.value == "wave"
    assert GestureType.OPEN_PALM.value == "open_palm"
    assert GestureType.THUMBS_UP.value == "thumbs_up"
    assert GestureType.THUMBS_DOWN.value == "thumbs_down"
    assert GestureType.FIST.value == "fist"


def test_mock_gesture_detector_always_none() -> None:
    detector = MockGestureDetector()
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    gesture = detector.detect(frame)
    assert gesture == GestureType.NONE


def test_mock_gesture_detector_consistent() -> None:
    detector = MockGestureDetector()
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    results = [detector.detect(frame) for _ in range(5)]
    assert all(g == GestureType.NONE for g in results)


def test_make_gesture_detector_mock() -> None:
    detector = make_gesture_detector(mock=True)
    assert isinstance(detector, MockGestureDetector)


# ---------------------------------------------------------------------------
# PresenceDetector
# ---------------------------------------------------------------------------


def test_mock_presence_always_true() -> None:
    detector = MockPresenceDetector()
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    assert detector.is_present(frame) is True


def test_make_presence_detector_mock() -> None:
    detector = make_presence_detector(mock=True)
    assert isinstance(detector, MockPresenceDetector)


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
