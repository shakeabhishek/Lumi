"""Device display — the on-Lumi screen, rendered as a React app.

Architectural pivot (2026-05-24): we used to render Lumi's face with
pygame and push numpy frames to the hardware display. The Pi 5 has 16 GB
of RAM and we ship with Chromium anyway, so the device display is now a
React/Vite app served right here and rendered fullscreen by Chromium in
kiosk mode (Phase 5 wires the autostart).

This module exposes three things:

  GET /device-display
      Serves the built React bundle (index.html + /assets/* via the
      existing /static mount).

  GET /device-display/sprite/{pack}/{file}
      Stream a single PNG frame or manifest.json from either the
      user-uploaded sprite dir (data_dir/sprites/<pack>/) OR the
      bundled assets/sprites/<bundled-dir>/ — the same fallback chain
      the pygame loader used, so existing packs (and the upload UI we
      shipped earlier) keep working without changes.

  GET /device-display/events
      Server-Sent Events stream pushing one JSON frame per LumiState
      transition, plus periodic widget-bar updates (weather, CPU%).
      The React client subscribes and re-renders on each event. The
      backend keeps a single in-process broadcaster — the StateMachine
      and chat session will eventually publish into it.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import psutil  # type: ignore[import-not-found]
from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse

from ...face.idle_scenes import _BUNDLED_DIR_FOR, _SPRITES_DIR

router = APIRouter()


# ── Static React bundle ───────────────────────────────────────────────────


_DEVICE_BUILD = (
    Path(__file__).resolve().parent.parent / "static" / "device-display"
)


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def device_display_index() -> HTMLResponse:
    index = _DEVICE_BUILD / "index.html"
    if not index.exists():
        return HTMLResponse(
            "<h1>Device display not built</h1>"
            "<p>Run <code>cd src/lumi/ui/device_display && npm run build</code>.</p>",
            status_code=503,
        )
    return HTMLResponse(index.read_text(encoding="utf-8"))


@router.get("/assets/{filename:path}", include_in_schema=False)
async def device_display_asset(filename: str) -> FileResponse:
    """Serve the Vite-built JS/CSS bundle. Vite's `base: '/device-display/'`
    config makes the index.html reference these under /device-display/assets/."""
    path = _DEVICE_BUILD / "assets" / filename
    if not path.exists() or not str(path.resolve()).startswith(str(_DEVICE_BUILD.resolve())):
        return FileResponse(_DEVICE_BUILD / "index.html", status_code=404)
    return FileResponse(path)


# ── Sprite serving (bundled + user-uploaded) ──────────────────────────────


def _resolve_sprite_root(pack: str, data_dir: Path) -> Path | None:
    """Same fallback chain as the pygame loader:
      1. data_dir/sprites/<pack>/   (user-uploaded — overrides)
      2. bundled assets/sprites/<bundled-dir-name>/
    Returns the directory or None if neither exists."""
    user = data_dir / "sprites" / pack
    if user.is_dir() and any(user.glob("frame_*.png")):
        return user
    bundled_dir = _BUNDLED_DIR_FOR.get(pack, pack)
    bundled = _SPRITES_DIR / bundled_dir
    if bundled.is_dir() and any(bundled.glob("frame_*.png")):
        return bundled
    return None


@router.get("/sprite/{pack}/{filename}", include_in_schema=False)
async def device_display_sprite(
    request: Request, pack: str, filename: str,
) -> FileResponse:
    # Only PNG frames + the manifest are exposed — block anything else
    # so a path-traversal attempt can't pull arbitrary files.
    if not (filename.startswith("frame_") and filename.endswith(".png")) and filename != "manifest.json":
        return FileResponse(
            _DEVICE_BUILD / "index.html", status_code=404,
            headers={"X-Sprite-Reject": "name"},
        )
    root = _resolve_sprite_root(pack, request.app.state.data_dir)
    if root is None:
        return FileResponse(
            _DEVICE_BUILD / "index.html", status_code=404,
            headers={"X-Sprite-Reject": "pack-missing"},
        )
    candidate = root / filename
    # Defensive path check — root might be a symlink, so resolve both.
    if not candidate.exists() or not str(candidate.resolve()).startswith(str(root.resolve())):
        return FileResponse(
            _DEVICE_BUILD / "index.html", status_code=404,
            headers={"X-Sprite-Reject": "escape"},
        )
    return FileResponse(candidate)


# ── State stream (SSE) ────────────────────────────────────────────────────
#
# Phase A (now): poll-based — the route synthesizes a snapshot every
# second from app.state (last LumiState transition, last weather sample,
# psutil CPU%). This already gives the React app live data with no
# additional infrastructure.
#
# Phase B (when the voice loop is also a long-lived server): hook the
# StateMachine's on_state_change callback into a broadcaster + push
# transitions immediately instead of polling. Trivial drop-in then.


_LAST_PERSISTED_FACE_STATE = "idle"        # updated by main.py state machine when wired


def _device_snapshot(request: Request) -> dict:
    from ..persistence import load_settings  # noqa: PLC0415

    settings = load_settings(request.app.state.data_dir)
    face_state = getattr(request.app.state, "lumi_face_state", _LAST_PERSISTED_FACE_STATE)

    # Map face_theme → device style. "terminal" is the only synonym;
    # an idle-scene that's a sprite pack flips us into sprite mode.
    style = settings.face_theme if settings.face_theme in {"pixel", "vector", "terminal"} else "pixel"
    sprite_pack: str | None = None
    if settings.idle_scene and settings.idle_scene not in {"none", "rain", "snow"}:
        style = "sprite"
        sprite_pack = settings.idle_scene

    cpu = psutil.cpu_percent(interval=None)        # non-blocking

    return {
        "state": face_state,
        "style": style,
        "spritePack": sprite_pack,
        "theme": "default",                         # multi-theme support: V2
        "statusText": _status_text_for(face_state),
        "weather": None,                            # wired in when weather skill exposes it
        "cpuPct": round(cpu),
    }


def _status_text_for(face_state: str) -> str:
    return {
        "idle":   "Connected to cloud",
        "listen": "Listening…",
        "think":  "Thinking…",
        "speak":  "Speaking",
    }.get(face_state, "Connected to cloud")


@router.get("/events")
async def device_display_events(request: Request) -> StreamingResponse:
    """SSE feed of device state. Emits one frame on connect + one every
    second thereafter. Client is the React app's `useDeviceState` hook."""
    async def stream():
        try:
            while True:
                if await request.is_disconnected():
                    return
                snapshot = _device_snapshot(request)
                yield f"data: {json.dumps(snapshot)}\n\n".encode()
                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            return

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",        # disable nginx-style proxy buffering
            "Connection": "keep-alive",
        },
    )


# Warm psutil's CPU sampler so the first /events frame isn't 0% on a
# cold start. cpu_percent() returns the % since the LAST call, so seed
# it at module import.
psutil.cpu_percent(interval=None)
time.perf_counter()      # touch module so timing is hot
