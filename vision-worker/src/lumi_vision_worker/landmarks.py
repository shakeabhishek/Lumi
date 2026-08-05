"""MediaPipe HandLandmarker (VIDEO mode) wrapper — converts a captured RGB
frame into plain (x, y, z) landmark tuples, our own Hand type from
classify.py, with no MediaPipe types leaking past this module.

Needs a HandLandmarker .task model bundle on disk (not bundled with the
`mediapipe` pip package itself) — download once per deploy:
  curl -L -o hand_landmarker.task \\
    https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task
See vision-worker/README.md for the full setup step.
"""

from __future__ import annotations

from pathlib import Path

import mediapipe as mp
import numpy as np
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python.vision import HandLandmarker, HandLandmarkerOptions, RunningMode

from .classify import Hand


class HandLandmarkDetector:
    """Wraps MediaPipe's HandLandmarker task in VIDEO mode (matches the
    on-Pi benchmark's own configuration — see the plan's §9 step 0 note
    on re-deriving those numbers against this exact setup)."""

    def __init__(self, model_path: Path, num_hands: int = 1) -> None:
        options = HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(model_path)),
            running_mode=RunningMode.VIDEO,
            num_hands=num_hands,
        )
        self._landmarker = HandLandmarker.create_from_options(options)

    def detect(self, frame_rgb: np.ndarray, timestamp_ms: int) -> list[Hand]:
        """frame_rgb must be an HxWx3 uint8 RGB array. timestamp_ms must
        be monotonically increasing across calls (VIDEO mode requirement)
        — the caller's capture loop timestamp works fine for this.

        Returns one Hand (21 landmarks) per detected hand, empty list if
        none. The raw frame is not retained by this method or by
        MediaPipe past this call — see main.py's privacy comment banner
        for why that matters."""
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame_rgb)
        result = self._landmarker.detect_for_video(image, timestamp_ms)
        return [
            [(lm.x, lm.y, lm.z) for lm in hand_landmarks]
            for hand_landmarks in result.hand_landmarks
        ]

    def close(self) -> None:
        self._landmarker.close()
