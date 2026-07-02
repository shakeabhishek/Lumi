"""Minimal HTTP client the voice loop uses to push face-state changes
to the device display.

The voice loop (`lumi run`) is a separate OS process from the FastAPI
server (`lumi web`) — they share state via HTTP. Whenever the voice
loop's StateMachine transitions, we fire-and-forget a POST to
`/api/state`; the server's DeviceBus relays it to every connected
device-display subscriber. The Chromium kiosk on the Pi sees the face
animate in real time.

Why fire-and-forget + thread pool: the voice loop is doing real-time
audio work. We do NOT want a network request from the state callback
to block recording / STT / TTS for even a hundred milliseconds. The
helper hands off to a small worker thread and never awaits.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

import httpx

from ..log import get_logger
from .state_machine import LumiState

log = get_logger(__name__)

# Single-thread executor: lossy by design. If the queue backs up we'd
# rather drop a face transition than back-pressure the audio loop.
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="lumi-device-display")
_seen_failure = threading.Event()


def _state_value(state: LumiState) -> str:
    return state.value if isinstance(state, LumiState) else str(state)


def push_state(state: LumiState, base_url: str = "http://127.0.0.1:8080") -> None:
    """Schedule a fire-and-forget POST. Returns immediately."""
    value = _state_value(state)
    _executor.submit(_send, value, base_url)


def _send(state: str, base_url: str) -> None:
    try:
        httpx.post(
            f"{base_url.rstrip('/')}/api/state",
            data={"state": state},
            timeout=1.5,        # short — if `lumi web` isn't running we drop the frame
        )
        # If we'd previously logged a failure, log the recovery once.
        if _seen_failure.is_set():
            log.info("device_display_client.recovered", base_url=base_url)
            _seen_failure.clear()
    except (httpx.HTTPError, httpx.TimeoutException) as exc:
        # One-time warning when the dashboard isn't reachable. Subsequent
        # failures are silent so we don't spam logs during normal
        # "voice loop running without dashboard" use.
        if not _seen_failure.is_set():
            log.info(
                "device_display_client.unreachable",
                hint="run `lumi web` to see the face on the device display",
                error=str(exc),
            )
            _seen_failure.set()


def state_callback(base_url: str = "http://127.0.0.1:8080") -> Callable[[LumiState], None]:
    """Return a callable suitable for `StateMachine.on_state_change()`."""
    def _on_change(state: LumiState) -> None:
        push_state(state, base_url=base_url)
    return _on_change


# ── Live captions ─────────────────────────────────────────────────────────
#
# Separate from push_state/state_callback on purpose — captions carry text,
# StateMachine stays a bare enum (see runtime/state_machine.py). Routed
# through the SAME single-thread _executor as push_state so caption pushes
# can't reorder relative to state-transition pushes from the same turn.


def push_caption(
    speaker: str, text: str, final: bool, base_url: str = "http://127.0.0.1:8080",
) -> None:
    """Schedule a fire-and-forget caption POST. Returns immediately."""
    _executor.submit(_send_caption, speaker, text, final, base_url)


def _send_caption(speaker: str, text: str, final: bool, base_url: str) -> None:
    try:
        httpx.post(
            f"{base_url.rstrip('/')}/api/caption",
            data={"speaker": speaker, "text": text, "final": str(final)},
            timeout=1.5,
        )
    except (httpx.HTTPError, httpx.TimeoutException):
        pass  # silent drop, same philosophy as _send() — a caption is not worth retrying


def clear_caption(base_url: str = "http://127.0.0.1:8080") -> None:
    """Schedule a fire-and-forget caption-clear POST. Returns immediately."""
    _executor.submit(_send_clear_caption, base_url)


def _send_clear_caption(base_url: str) -> None:
    try:
        httpx.post(f"{base_url.rstrip('/')}/api/caption/clear", timeout=1.5)
    except (httpx.HTTPError, httpx.TimeoutException):
        pass
