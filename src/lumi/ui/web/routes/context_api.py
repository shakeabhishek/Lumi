"""HTTP twin of the hotkey daemon: POST text → queued as next-turn context.

Useful for remote triggering (e.g. a future browser extension), for scripts,
and for testing the consume_pending() loop without needing a real hotkey.
Gated on `clipboard_enabled` like the daemon.
"""

from __future__ import annotations

from typing import Annotated

import httpx
from fastapi import APIRouter, Form, HTTPException, Query, Request

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


# ── Location typeahead ──────────────────────────────────────────────────────


@router.get("/locations/search")
async def search_locations(
    request: Request,                       # noqa: ARG001  unused; kept for symmetry + future per-request rate-limiting
    q: str = Query("", min_length=0, max_length=64),
) -> dict[str, list[dict[str, str]]]:
    """City autocomplete backed by OpenWeatherMap's geocoding endpoint.

    Returns up to 5 matches in the shape:
      {"results": [{"name": "Tokyo", "country": "JP", "state": "Tokyo",
                    "label": "Tokyo, Tokyo, JP", "value": "Tokyo,JP"}, ...]}

    `value` is what gets written into the weather_location field — OWM's
    weather endpoint takes "City,CC" so we pre-format. `label` is the
    human-readable string shown in the dropdown.

    No API key → returns an empty list rather than failing. The user
    still sees a free-form text field; they just don't get suggestions.
    """
    from ....runtime import secrets  # noqa: PLC0415

    query = q.strip()
    if len(query) < 2:
        return {"results": []}

    key = secrets.get_secret("openweathermap_api_key")
    if not key:
        return {"results": []}

    try:
        r = httpx.get(
            "https://api.openweathermap.org/geo/1.0/direct",
            params={"q": query, "limit": 5, "appid": key},
            timeout=5.0,
        )
        if r.status_code != 200:
            return {"results": []}
        raw = r.json()
    except (httpx.HTTPError, ValueError):
        return {"results": []}

    out: list[dict[str, str]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name") or ""
        country = entry.get("country") or ""
        state = entry.get("state") or ""
        if not name or not country:
            continue
        # "Tokyo, Tokyo, JP" vs "Tokyo, JP" — drop the redundant
        # state when it duplicates the city (common for Asian capitals).
        parts = [name]
        if state and state != name:
            parts.append(state)
        parts.append(country)
        label = ", ".join(parts)
        # `value` goes into the input → weather endpoint. OWM accepts
        # "City,CC" reliably; appending state can break in some
        # locales, so we keep value short and put state in the label.
        value = f"{name},{country}"
        out.append({
            "name": name,
            "country": country,
            "state": state,
            "label": label,
            "value": value,
        })
    return {"results": out}
