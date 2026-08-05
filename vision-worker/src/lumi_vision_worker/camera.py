"""Camera frame reader — NOT a direct picamera2 wrapper.

Discovered on real Pi hardware (2026-07-06): picamera2/libcamera's Python
bindings are apt-installed and compiled specifically against the Pi OS's
system Python (3.13), but mediapipe has no wheel for Python 3.13 on any
platform (its newest aarch64 Linux wheel at all, 0.10.18, is capped at
cp312). The two can't share this venv's interpreter, so a separate tiny
process (../capture_shim/capture_shim.py) runs under the system Python,
captures frames via Picamera2, and publishes them into POSIX shared
memory. This module just reads from that segment.

See capture_shim.py's own docstring for the exact wire protocol — the
constants below duplicate it by convention (the two processes can't
share a Python import across the version boundary).
"""

from __future__ import annotations

import struct
import time
from multiprocessing import resource_tracker, shared_memory

import numpy as np

WIDTH = 640
HEIGHT = 480
_FRAME_BYTES = WIDTH * HEIGHT * 3
_HEADER_BYTES = 8
_SHM_NAME = "lumi_vision_frame"


class PiCamera:
    """capture() returns one HxWx3 uint8 RGB frame, read from the shared-
    memory segment capture_shim.py maintains. No frame is ever written to
    disk or retained past the caller's use of the returned array
    (privacy requirement — see main.py's comment banner)."""

    def __init__(
        self,
        width: int = WIDTH,
        height: int = HEIGHT,
        poll_s: float = 0.01,
        attach_timeout_s: float = 5.0,
    ) -> None:
        if (width, height) != (WIDTH, HEIGHT):
            raise ValueError(
                f"PiCamera only supports {WIDTH}x{HEIGHT} today — the shared-memory "
                "protocol with capture_shim.py is fixed-size."
            )
        self._poll_s = poll_s
        self._last_seq = 0
        self._shm = self._attach(attach_timeout_s)

    @staticmethod
    def _attach(timeout_s: float) -> shared_memory.SharedMemory:
        deadline = time.monotonic() + timeout_s
        while True:
            try:
                shm = shared_memory.SharedMemory(name=_SHM_NAME, create=False)
                # Python's resource_tracker treats every SharedMemory
                # handle as something IT owns and unlinks on process
                # exit — even one attached with create=False (a known
                # multiprocessing gotcha, cpython bpo-38119). Only
                # capture_shim.py (the actual creator) should ever
                # unlink this segment; without unregistering here, this
                # reader exiting would delete the segment out from under
                # the still-running writer (reproduced directly:
                # capture worked, a second reader process started and
                # exited, and the segment vanished from /dev/shm while
                # capture_shim.py was still alive).
                resource_tracker.unregister(shm._name, "shared_memory")
                return shm
            except FileNotFoundError:
                if time.monotonic() > deadline:
                    raise RuntimeError(
                        f"capture_shim.py isn't running (no shared memory segment "
                        f"'{_SHM_NAME}' found after {timeout_s}s) — start it under the "
                        "system Python first. See vision-worker/capture_shim/README.md."
                    ) from None
                time.sleep(0.2)

    def capture(self) -> np.ndarray:
        """Blocks until a fresh frame is available. Discards and retries
        on a torn read (writer started the next frame mid-read) rather
        than locking — see capture_shim.py's docstring for why that's an
        acceptable tradeoff here."""
        while True:
            seq_before = struct.unpack_from("<Q", self._shm.buf, 0)[0]
            if seq_before != self._last_seq:
                frame_bytes = bytes(self._shm.buf[_HEADER_BYTES : _HEADER_BYTES + _FRAME_BYTES])
                seq_after = struct.unpack_from("<Q", self._shm.buf, 0)[0]
                if seq_after == seq_before:
                    self._last_seq = seq_before
                    return np.frombuffer(frame_bytes, dtype=np.uint8).reshape(HEIGHT, WIDTH, 3)
            time.sleep(self._poll_s)

    def close(self) -> None:
        self._shm.close()
