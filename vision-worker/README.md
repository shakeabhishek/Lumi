# lumi-vision-worker

Camera-based gesture recognition + presence detection for Lumi, running as
a completely separate process from the main `lumi` app.

## Why a separate process/venv

MediaPipe requires `protobuf` 4.x. The main app's `chromadb` dependency
requires `protobuf` 7.x. These cannot coexist in one Python environment —
this package has its own `pyproject.toml`/`uv.lock`/venv, and talks to the
main app only over HTTP (`client.py`) and the filesystem
(`wake_trigger.py`), never a shared Python import.

## Setup

```bash
cd vision-worker
uv sync                    # laptop dev — classify.py/wave.py/presence.py fully testable, no camera needed
uv run pytest
```

On the Pi, also need:
1. **`picamera2`** — Raspberry Pi OS ships this as a system package
   (`sudo apt install python3-picamera2`), not really meant for generic
   pip installation (its own dependency, `python-prctl`, is Linux-only
   and doesn't build from source on other platforms — this is why it's
   NOT in this project's `pyproject.toml` as an extra). Point `uv` at the
   system site-packages, or install it into this venv directly on the Pi
   via `uv pip install picamera2` (works there since the platform matches).
2. **HandLandmarker model bundle** — not part of the `mediapipe` pip
   package:
   ```bash
   curl -L -o src/lumi_vision_worker/hand_landmarker.task \
     https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task
   ```

## Running standalone (manual, pre-systemd verification)

```bash
uv run lumi-vision-worker --data-dir /home/lumi/lumi/data --web-base-url http://127.0.0.1:8080
```
or via env vars: `LUMI_DATA_DIR`, `LUMI_WEB_BASE_URL`.

## How it talks to the main app

- **Gestures/presence → display**: fire-and-forget `POST /api/gesture`
  and `POST /api/presence` to the main app's web server (`client.py`).
  Silently drops on failure — the next detection/heartbeat self-heals,
  same philosophy as the main app's own `device_display_client.py`.
  Presence is display-only (drives the on-screen closed-eyes/"Zzz" sleep
  treatment) — it does NOT wake Lumi.
- **Wave gesture → wake**: writes `data_dir/.wake_trigger.json` directly
  to the filesystem (`wake_trigger.py`) — no HTTP hop, so gesture-
  triggered wake keeps working even if the main app's web server is
  down. Consumed by `FileTriggerWake` in the main app's
  `src/lumi/audio/wake_word.py`. Presence never writes this file (user
  decision, 2026-07-06) — the only ways to wake Lumi are a wave gesture
  or the voice wake word.

## Privacy

- Frames are never written to disk anywhere in this process.
- Only 21-point hand landmarks survive past a single loop iteration
  (`landmarks.py` converts MediaPipe's result to plain tuples
  immediately); presence detection only ever retains the single previous
  frame it needs for its own frame-diff.
- `camera_enabled` (from the main app's `user_settings.json`, checked
  directly via a bare JSON read — see `main.py:_camera_enabled`) actually
  gates capture: when off, the camera is released and the process parks
  in a settings-poll loop, not just "ignores detections."

## Module map

| Module | Purpose | Needs real hardware to test? |
|---|---|---|
| `classify.py` | Pure per-frame gesture pose classification from 21 landmarks | No |
| `wave.py` | Stateful wave-oscillation detector | No |
| `presence.py` | Frame-diff motion detector | No (synthetic arrays) |
| `wake_trigger.py` | Writes the cross-process wake file | No |
| `client.py` | Fire-and-forget push to the main app | No (mocked httpx) |
| `config.py` | argparse + env var config | No |
| `landmarks.py` | MediaPipe HandLandmarker wrapper | Yes (real model + real/synthetic frames) |
| `camera.py` | Picamera2 capture | Yes |
| `main.py` | Ties it all together in a capture loop | Yes (the loop itself; `_camera_enabled` is unit-tested) |
