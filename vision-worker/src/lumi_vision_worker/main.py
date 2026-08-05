"""Vision worker entrypoint: capture loop -> classify -> presence -> push.

Privacy: frames are never written to disk anywhere in this loop. Each
frame is used to (a) get hand landmarks — landmarks.py converts
MediaPipe's result to plain (x, y, z) tuples immediately, the raw frame
array is not retained past that call — and (b) presence's frame-diff,
which only ever keeps the single previous frame it needs for the diff,
never a longer history or a persisted copy.

On camera_enabled: checked directly from data_dir/user_settings.json (a
bare JSON read of one key, no `lumi` package import — see the plan's
§1.3/§7 reasoning for why this venv stays fully independent of the main
app's). When disabled, the camera is released and capture stops
entirely — a real privacy behavior, not just "ignore what it captures."

On wake: only a WAVE gesture writes the cross-process wake trigger
(user decision, 2026-07-06) — presence sitting-down does NOT wake Lumi
on its own, only the display's ambient dim/sleep treatment. The only
ways to wake Lumi are a wave gesture or the voice wake word; presence
here exists purely to drive `/api/presence` for the on-screen sleep
visual (closed eyes + "Zzz", see PixelFace.tsx).
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from . import client, wake_trigger
from .camera import PiCamera
from .classify import GestureType, classify_static_pose
from .config import Config, load_config
from .landmarks import HandLandmarkDetector
from .presence import MotionPresenceDetector
from .wave import WaveDetector

log = logging.getLogger(__name__)

_MODEL_PATH = Path(__file__).parent / "hand_landmarker.task"
_N_CONSECUTIVE = 3  # frames a candidate gesture must hold before "detected" (~180ms at 16fps)
_COOLDOWN_S = 1.5  # per-gesture-type suppression after firing (mirrors OpenWakeWordWake's cooldown)


def _camera_enabled(data_dir: Path) -> bool:
    try:
        raw = json.loads((data_dir / "user_settings.json").read_text(encoding="utf-8"))
        return bool(raw.get("camera_enabled", False))
    except (OSError, ValueError, json.JSONDecodeError):
        return False


def run() -> None:
    logging.basicConfig(level=logging.INFO)
    cfg = load_config()
    log.info(
        "vision_worker.starting",
        extra={"data_dir": str(cfg.data_dir), "web_base_url": cfg.web_base_url},
    )

    while True:
        if not _camera_enabled(cfg.data_dir):
            time.sleep(cfg.settings_poll_s)
            continue
        _run_capture_session(cfg)


def _run_capture_session(cfg: Config) -> None:
    """Runs capture+detect+push until camera_enabled flips off, then
    releases the camera and returns to run()'s settings-poll loop."""
    camera = PiCamera()
    detector = HandLandmarkDetector(_MODEL_PATH)
    presence = MotionPresenceDetector()
    wave_detector = WaveDetector()

    candidate: GestureType | None = None
    candidate_streak = 0
    last_fired_at: dict[GestureType, float] = {}
    last_present: bool | None = None
    last_presence_push = 0.0

    log.info("vision_worker.capture_session_started")
    try:
        while _camera_enabled(cfg.data_dir):
            frame = camera.capture()
            now = time.monotonic()
            timestamp_ms = int(now * 1000)

            hands = detector.detect(frame, timestamp_ms)
            effective = GestureType.NONE
            if hands:
                hand = hands[0]
                pose = classify_static_pose(hand)
                effective = GestureType.WAVE if wave_detector.push(now, hand, pose) else pose

            if effective != GestureType.NONE and effective == candidate:
                candidate_streak += 1
            else:
                candidate = effective
                candidate_streak = 1

            if (
                effective != GestureType.NONE
                and candidate_streak >= _N_CONSECUTIVE
                and now - last_fired_at.get(effective, 0.0) >= _COOLDOWN_S
            ):
                last_fired_at[effective] = now
                client.push_gesture(effective.value, base_url=cfg.web_base_url)
                if effective == GestureType.WAVE:
                    wake_trigger.write_wake_trigger(cfg.data_dir, source="gesture:wave")
                elif effective == GestureType.OPEN_PALM:
                    # "Stop talking." Written unconditionally — this process
                    # has no idea whether Lumi is mid-reply, and the main app
                    # ignores the trigger unless she's speaking. See
                    # wake_trigger.py's module docstring.
                    wake_trigger.write_barge_in_trigger(
                        cfg.data_dir, source="gesture:open_palm",
                    )
                log.info("vision_worker.gesture_fired", extra={"gesture": effective.value})

            # Presence only drives the display's ambient dim/sleep
            # treatment (client.push_presence) — it deliberately never
            # writes a wake trigger. Only a wave gesture (above) or the
            # voice wake word can wake Lumi.
            is_present = presence.is_present(now, frame)
            if last_present is None:
                last_present = is_present
            elif is_present != last_present:
                client.push_presence(is_present, base_url=cfg.web_base_url)
                last_present = is_present
                last_presence_push = now
            elif now - last_presence_push >= cfg.presence_heartbeat_s:
                client.push_presence(is_present, base_url=cfg.web_base_url)
                last_presence_push = now
    finally:
        detector.close()
        camera.close()
        log.info("vision_worker.capture_session_stopped")
