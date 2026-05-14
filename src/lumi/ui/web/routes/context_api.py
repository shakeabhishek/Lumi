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
