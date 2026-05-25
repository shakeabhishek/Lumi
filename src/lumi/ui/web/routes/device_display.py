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
# Push-based (Phase B). The DeviceBus owns subscriber queues; whoever
# wants to change state publishes one snapshot and every connected
# React client receives it instantly. Periodic CPU/weather refreshes
# come from a single background task so we're not polling on every
# subscriber's connection.


_VALID_FACE_STATES = {"idle", "listen", "think", "speak"}

# Whitelist of palette keys the React device display knows how to
# render. Must stay in sync with the [data-theme=...] selectors in
# src/lumi/ui/device_display/src/styles/index.css. Exposed here as the
# single source of truth so the settings route and the SSE snapshot
# agree on which themes exist.
_VALID_THEMES = frozenset({
    "default", "sunset", "ocean", "forest",
    "sakura", "mint", "lavender", "monochrome",
})


def _settings_snapshot(request: Request) -> dict:
    """Read-only fields derived from on-disk settings — style, sprite
    pack, theme. Recomputed on every publish so a /settings/face change
    reflects without restarting the server."""
    from ..persistence import load_settings  # noqa: PLC0415

    settings = load_settings(request.app.state.data_dir)
    style = settings.face_theme if settings.face_theme in {"pixel", "vector", "terminal"} else "pixel"
    sprite_pack: str | None = None
    if settings.idle_scene and settings.idle_scene != "none":
        # An idle_scene that isn't "none" is always a sprite pack now —
        # the React device display has no procedural rain/snow path.
        style = "sprite"
        sprite_pack = settings.idle_scene
    # Whitelist the theme against the React app's known palettes — an
    # unknown value falls back to the default gradient instead of
    # producing an invisible (un-styled) display.
    theme = settings.display_theme if settings.display_theme in _VALID_THEMES else "default"
    return {
        "style": style,
        "spritePack": sprite_pack,
        "theme": theme,
    }


def _status_text_for(face_state: str) -> str:
    return {
        "idle":   "Connected to cloud",
        "listen": "Listening…",
        "think":  "Thinking…",
        "speak":  "Speaking",
    }.get(face_state, "Connected to cloud")


async def publish_face_state(request: Request, face_state: str) -> None:
    """Helper for in-process callers (chat session, future state-machine
    listener). Updates the cached settings-derived fields too so the
    React client doesn't have to re-fetch /settings between transitions."""
    from .. import device_bus as _bus_mod  # noqa: PLC0415

    if face_state not in _VALID_FACE_STATES:
        return
    snapshot = {
        "state": face_state,
        "statusText": _status_text_for(face_state),
        **_settings_snapshot(request),
    }
    await _bus_mod.get_bus(request.app).publish(snapshot)


@router.get("/events")
async def device_display_events(request: Request) -> StreamingResponse:
    """SSE feed. Each connection subscribes to the broadcaster, gets the
    last-known snapshot delivered immediately (so the face renders
    without waiting for the next transition), then receives push frames
    whenever publish() is called from anywhere in the process.
    """
    from .. import device_bus as _bus_mod  # noqa: PLC0415

    bus = _bus_mod.get_bus(request.app)

    # Seed the bus with the current settings + an "idle" baseline if
    # nothing's been published yet — guarantees first /events response
    # has actual data for the client to render.
    if bus.latest() is None:
        await bus.publish({
            "state": "idle",
            "statusText": _status_text_for("idle"),
            "weather": None,
            "cpuPct": round(psutil.cpu_percent(interval=None)),
            **_settings_snapshot(request),
        })

    async def stream():
        async for snapshot in bus.subscribe():
            if await request.is_disconnected():
                return
            yield f"data: {json.dumps(snapshot)}\n\n".encode()

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# Warm psutil's CPU sampler so the first publish isn't 0% on cold start.
# cpu_percent() returns the delta since the LAST call.
psutil.cpu_percent(interval=None)
time.perf_counter()
