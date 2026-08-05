"""Camera capture shim — bridges an ABI gap discovered on real Pi
hardware (2026-07-06): picamera2/libcamera's Python bindings are apt-
installed and compiled specifically against the Pi OS's system Python
(3.13 on this image), but mediapipe has never published a cp313 wheel
for any platform (confirmed against PyPI's full release history) — its
newest aarch64 Linux wheel at all is 0.10.18, capped at cp312. The two
libraries can't share one Python interpreter, so capture is split into
its own tiny process, running under the SYSTEM Python where picamera2
actually lives, and handed to the vision-worker (Python 3.12, mediapipe)
over POSIX shared memory instead of a direct function call.

This script is NOT part of the lumi_vision_worker package and is never
imported by it — it deliberately can't be (different Python entirely,
no shared venv). Run it with the system interpreter:

    python3 capture_shim.py

Protocol (see vision-worker/src/lumi_vision_worker/camera.py, the
reader side, which duplicates these same constants — the two processes
can't share a Python import, so the layout is fixed by convention and
comments on both ends, not by a shared module):

    shared memory segment "lumi_vision_frame", fixed size:
      bytes[0:8]   little-endian uint64 frame sequence number
      bytes[8:8+W*H*3]  most recent RGB888 frame, row-major

Single-writer/single-reader, deliberately un-locked: writes update the
frame bytes first, the sequence number last, so a reader that sees a
fresh sequence number can trust the frame it's about to read is
complete UNLESS the writer starts the *next* frame mid-read — the
reader re-checks the sequence number after reading and discards a torn
frame rather than adding a lock. Acceptable for a best-effort real-time
gesture pipeline that already averages across several frames before
acting (see main.py's debounce), not acceptable if this were ever reused
somewhere needing bit-exact frame delivery.
"""

from __future__ import annotations

import argparse
import json
import struct
import time
from multiprocessing import shared_memory
from pathlib import Path

WIDTH = 640
HEIGHT = 480
_FRAME_BYTES = WIDTH * HEIGHT * 3
_HEADER_BYTES = 8
SHM_NAME = "lumi_vision_frame"
SHM_SIZE = _HEADER_BYTES + _FRAME_BYTES

_SETTINGS_POLL_S = 2.0


def _camera_enabled(data_dir: Path) -> bool:
    try:
        raw = json.loads((data_dir / "user_settings.json").read_text(encoding="utf-8"))
        return bool(raw.get("camera_enabled", False))
    except (OSError, ValueError, json.JSONDecodeError):
        return False


def _open_shm() -> shared_memory.SharedMemory:
    try:
        return shared_memory.SharedMemory(name=SHM_NAME, create=True, size=SHM_SIZE)
    except FileExistsError:
        # A previous run didn't clean up (e.g. kill -9) — reuse it rather
        # than failing; the reader doesn't care who created the segment.
        return shared_memory.SharedMemory(name=SHM_NAME, create=False, size=SHM_SIZE)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--data-dir", required=True,
        help="Same data_dir the vision-worker uses (for camera_enabled).",
    )
    args = parser.parse_args()
    data_dir = Path(args.data_dir)

    shm = _open_shm()
    try:
        while True:
            if not _camera_enabled(data_dir):
                time.sleep(_SETTINGS_POLL_S)
                continue
            _run_capture_session(shm, data_dir)
    finally:
        shm.close()
        shm.unlink()


def _run_capture_session(shm: shared_memory.SharedMemory, data_dir: Path) -> None:
    from picamera2 import Picamera2  # noqa: PLC0415 — only importable under system Python

    picam2 = Picamera2()
    config = picam2.create_video_configuration(main={"size": (WIDTH, HEIGHT), "format": "RGB888"})
    picam2.configure(config)
    picam2.start()

    seq = 0
    try:
        while _camera_enabled(data_dir):
            frame = picam2.capture_array()
            shm.buf[_HEADER_BYTES : _HEADER_BYTES + _FRAME_BYTES] = frame.tobytes()
            seq += 1
            struct.pack_into("<Q", shm.buf, 0, seq)
    finally:
        picam2.close()


if __name__ == "__main__":
    main()
