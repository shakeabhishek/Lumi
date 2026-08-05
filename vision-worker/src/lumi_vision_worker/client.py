"""Fire-and-forget HTTP push to the main app's /api/gesture and
/api/presence routes.

Mirrors src/lumi/runtime/device_display_client.py's SHAPE exactly (single-
worker ThreadPoolExecutor so ordering is preserved, short timeout, silent
drop on failure — the next push/heartbeat self-heals) — but is a
deliberate, separate, from-scratch implementation with zero imports from
the `lumi` package. See the plan's §1.3: installing the `lumi` package
into this venv just to reuse ~15 lines of httpx.post boilerplate would
double this venv's footprint (numpy/pydantic/etc.) and create exactly the
kind of cross-venv coupling the whole separate-process design exists to
avoid.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

import httpx

log = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="lumi-vision-worker")


def push_gesture(gesture_type: str, base_url: str) -> None:
    _executor.submit(_send_gesture, gesture_type, base_url)


def _send_gesture(gesture_type: str, base_url: str) -> None:
    try:
        httpx.post(f"{base_url.rstrip('/')}/api/gesture", data={"type": gesture_type}, timeout=1.5)
    except (httpx.HTTPError, httpx.TimeoutException) as exc:
        log.info("vision_worker.gesture_push_failed", exc_info=exc)


def push_presence(present: bool, base_url: str) -> None:
    _executor.submit(_send_presence, present, base_url)


def _send_presence(present: bool, base_url: str) -> None:
    try:
        httpx.post(
            f"{base_url.rstrip('/')}/api/presence",
            data={"present": str(present)},
            timeout=1.5,
        )
    except (httpx.HTTPError, httpx.TimeoutException) as exc:
        log.info("vision_worker.presence_push_failed", exc_info=exc)
