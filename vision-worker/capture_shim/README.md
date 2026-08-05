# capture_shim

A tiny bridge process, discovered necessary on real Pi hardware
(2026-07-06): `picamera2`/`libcamera`'s Python bindings are apt-installed
and compiled specifically against the Pi OS's **system** Python (3.13 on
the current image) — but `mediapipe` has never published a `cp313` wheel
on any platform, and its newest aarch64 Linux wheel at all (`0.10.18`) is
capped at `cp312`. The two libraries can't share one Python interpreter.

This script runs under the **system** Python (where `picamera2` lives),
captures frames via `Picamera2`, and publishes them into a POSIX shared-
memory segment. `vision-worker`'s own `camera.py` (running in its normal
Python 3.12 venv, alongside mediapipe) reads frames from that segment
instead of importing `picamera2` directly.

## Setup

Needs the apt packages (not pip-installable across this version gap):

```bash
sudo apt-get install -y python3-picamera2 libcap-dev
```

No venv of its own — it deliberately runs against the system Python
site-packages, since that's where the matching-ABI `picamera2`/
`libcamera` bindings live.

## Running

```bash
python3 capture_shim.py --data-dir /home/lumi/lumi/data
```

Respects the same `camera_enabled` flag in `user_settings.json` as the
main vision-worker — when off, it releases the camera and parks in a
settings-poll loop, same privacy behavior as the rest of the pipeline.

## Why not just build libcamera's bindings for Python 3.12?

Considered and rejected for now: libcamera's Python bindings are built
via meson/pybind11 against the full libcamera C++ source tree — a
multi-hour build with real risk of failing partway on version mismatches
between the system's installed `libcamera0.7` and whatever headers a
from-source build would need. The shared-memory shim is a well-worn
pattern for exactly this kind of hardware-binding-vs-Python-version
conflict, ships today, and adds sub-millisecond latency (a memcpy of a
few hundred KB) against MediaPipe's own ~60ms/frame inference budget at
16fps — not a meaningfully different tradeoff than building bindings
would have been, without the build risk.
