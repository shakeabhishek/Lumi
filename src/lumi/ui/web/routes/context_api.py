"""HTTP twin of the hotkey daemon: POST text → queued as next-turn context.

Useful for remote triggering (e.g. a future browser extension), for scripts,
and for testing the consume_pending() loop without needing a real hotkey.
Gated on `clipboard_enabled` like the daemon.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request

from ....host_helper.send_to_lumi import CaptureResult, write_pending
from ..persistence import load_settings

router = APIRouter()


@router.post("/context")
async def post_context(
    request: Request,
    text: Annotated[str, Form()],
    source: Annotated[str, Form()] = "api",
) -> dict[str, object]:
    data_dir = request.app.state.data_dir
    settings = load_settings(data_dir)
    if not settings.clipboard_enabled:
        raise HTTPException(status_code=403, detail="clipboard_enabled is off")
    text = text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="empty text")
    write_pending(data_dir, CaptureResult(text=text, source=source))
    return {"ok": True, "chars": len(text), "source": source}


# ── Device-state push ──────────────────────────────────────────────────────
#
# The voice loop (`lumi run`) is a separate OS process from the FastAPI
# app (`lumi web`). It can't directly call into the DeviceBus, so it
# pushes state transitions here via HTTP and we relay to subscribers.
# Same-machine traffic only — bypassed in the CSRF middleware just like
# /api/context.


@router.post("/state")
async def post_face_state(
    request: Request,
    state: Annotated[str, Form()],
) -> dict[str, object]:
    """Publish a face-state transition to /device-display/events subscribers.

    Body: form-encoded `state=idle|listen|think|speak`. Used by the voice
    loop and by tests; the web chat session calls the helper directly
    instead of going through HTTP."""
    from .device_display import publish_face_state, _VALID_FACE_STATES  # noqa: PLC0415

    if state not in _VALID_FACE_STATES:
        raise HTTPException(
            status_code=400,
            detail=f"state must be one of {sorted(_VALID_FACE_STATES)}",
        )
    await publish_face_state(request, state)
    return {"ok": True, "state": state}
