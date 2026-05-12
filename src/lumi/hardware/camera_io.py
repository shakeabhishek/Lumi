"""Camera implementations.

V1 hardware is the Pi Camera Module 3 Wide on CSI. For laptop dev we'd plug in a
webcam via OpenCV, but vision isn't on the Week 1 critical path — so this ships
as a `NullCamera` stub. Drop in a `WebcamCamera` (cv2.VideoCapture) when ready.
"""

from __future__ import annotations

import numpy as np

from .base import Camera


class NullCamera(Camera):
    """Always returns None. Vision pipeline treats this as 'camera disabled'."""

    def capture(self) -> np.ndarray | None:
        return None

    def close(self) -> None:
        return None
