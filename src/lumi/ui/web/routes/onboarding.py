"""Onboarding flow — 9 steps from first boot to first conversation.

Step 1  Welcome
Step 2  WiFi setup (laptop: informational only)
Step 3  Name your Lumi
Step 4  Voice enrollment (server-side mic recording, 3 × 5s clips)
Step 5  Voice personality (Piper voice picker)
Step 6  Face style
Step 7  Permissions
Step 8  Work mode
Step 9  Done / first conversation
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import numpy as np
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ..persistence import (
    LUMI_NAMES,
    FACE_THEMES,
    MODES,
    PIPER_VOICES,
    load_settings,
    save_settings,
)

router = APIRouter()

TOTAL_STEPS = 9

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _render(request: Request, step: int, **ctx: object) -> HTMLResponse:
    from ....host_helper.send_to_lumi import default_combo  # noqa: PLC0415

    settings = load_settings(request.app.state.data_dir)
    return request.app.state.templates.TemplateResponse(
        request, f"onboarding/step_{step}.html",
        {
            "settings": settings,
            "step": step,
            "total": TOTAL_STEPS,
            "lumi_names": LUMI_NAMES,
            "piper_voices": PIPER_VOICES,
            "face_themes": FACE_THEMES,
            "modes": MODES,
            "default_hotkey": settings.hotkey_combo or default_combo(),
            **ctx,
        },
    )


def _clips_dir(data_dir: Path) -> Path:
    d = data_dir / ".enrollment_clips"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _clip_count(data_dir: Path) -> int:
    return len(list(_clips_dir(data_dir).glob("clip_*.npy")))


def _clear_clips(data_dir: Path) -> None:
    for f in _clips_dir(data_dir).glob("clip_*.npy"):
        f.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Step GET handlers
# ---------------------------------------------------------------------------


@router.get("/{step}", response_class=HTMLResponse)
async def onboarding_get(request: Request, step: int) -> HTMLResponse:
    if step < 1 or step > TOTAL_STEPS:
        return RedirectResponse(url="/onboarding/1")  # type: ignore[return-value]
    extra: dict[str, object] = {}
    if step == 4:
        extra["clip_count"] = _clip_count(request.app.state.data_dir)
    if step == 6:
        # Reuse the same palette list /settings/face renders so the
        # onboarding picker can't drift from the dashboard picker.
        from .settings import DISPLAY_THEMES  # noqa: PLC0415

        extra["display_themes"] = DISPLAY_THEMES
    return _render(request, step, **extra)


# ---------------------------------------------------------------------------
# Step 1 — Welcome
# ---------------------------------------------------------------------------


@router.post("/1", response_class=RedirectResponse, status_code=303)
async def step1(request: Request) -> str:
    return "/onboarding/2"


# ---------------------------------------------------------------------------
# Step 2 — WiFi (informational on laptop)
# ---------------------------------------------------------------------------


@router.post("/2", response_class=RedirectResponse, status_code=303)
async def step2(request: Request) -> str:
    return "/onboarding/3"


# ---------------------------------------------------------------------------
# Step 3 — Name
# ---------------------------------------------------------------------------


@router.post("/3", response_class=RedirectResponse, status_code=303)
async def step3(
    request: Request,
    lumi_name: Annotated[str, Form()] = "Lumi",
) -> str:
    data_dir = request.app.state.data_dir
    s = load_settings(data_dir)
    s.lumi_name = lumi_name
    s.onboarding_step = 4
    save_settings(data_dir, s)
    return "/onboarding/4"


# ---------------------------------------------------------------------------
# Step 4 — Voice enrollment (server-side recording)
# ---------------------------------------------------------------------------


def _enroll_partial(request: Request, **ctx: object) -> HTMLResponse:
    """Render the small enrollment-status fragment that HTMX swaps into
    #enroll-status. Centralises all the markup the inline f-strings used
    to hold, and keeps exception text off the page (audit #14)."""
    return request.app.state.templates.TemplateResponse(
        request, "onboarding/_enroll_partial.html", ctx,
    )


@router.post("/4/record", response_class=HTMLResponse)
async def record_clip(request: Request) -> HTMLResponse:
    """Record one 5-second clip from the server's microphone."""
    data_dir = request.app.state.data_dir
    n = _clip_count(data_dir)
    if n >= 3:
        return _enroll_partial(request, state="already_done")
    try:
        from ....hardware.audio_io import SoundDeviceInput  # noqa: PLC0415
        from ....config import get_settings  # noqa: PLC0415

        cfg = get_settings()
        mic = SoundDeviceInput(sample_rate=cfg.audio_sample_rate, device=cfg.audio_input_device)
        clip = mic.record(5.0)
        np.save(_clips_dir(data_dir) / f"clip_{n}.npy", clip)
        n += 1
    except Exception:
        # Log the real exception server-side via FastAPI's logger but never
        # leak it to the UI — it can carry file paths and audio-driver
        # internals that aren't useful to the user.
        import logging  # noqa: PLC0415
        logging.getLogger(__name__).exception("onboarding.record_failed")
        return _enroll_partial(request, state="error", error_kind="recording")

    if n < 3:
        return _enroll_partial(request, state="recorded", n_recorded=n)
    return _enroll_partial(request, state="all_recorded")


@router.post("/4/enroll", response_class=HTMLResponse)
async def enroll(request: Request) -> HTMLResponse:
    data_dir = request.app.state.data_dir
    clips_dir = _clips_dir(data_dir)
    clip_files = sorted(clips_dir.glob("clip_*.npy"))
    if len(clip_files) < 3:
        return _enroll_partial(request, state="error", error_kind="missing_clips")
    try:
        from ....audio.voice_id import VoiceID  # noqa: PLC0415
        from ....config import get_settings  # noqa: PLC0415

        cfg = get_settings()
        clips = [np.load(str(f)) for f in clip_files]
        voice_id = VoiceID(data_dir)
        voice_id.enroll(clips, cfg.audio_sample_rate)
        _clear_clips(data_dir)

        s = load_settings(data_dir)
        s.voice_id_enrolled = True
        s.voice_id_enabled = True
        s.onboarding_step = 5
        save_settings(data_dir, s)
        return _enroll_partial(request, state="enrolled")
    except Exception:
        import logging  # noqa: PLC0415
        logging.getLogger(__name__).exception("onboarding.enroll_failed")
        return _enroll_partial(request, state="error", error_kind="enrollment")


@router.post("/4/skip", response_class=RedirectResponse, status_code=303)
async def skip_enrollment(request: Request) -> str:
    data_dir = request.app.state.data_dir
    _clear_clips(data_dir)
    s = load_settings(data_dir)
    s.onboarding_step = 5
    save_settings(data_dir, s)
    return "/onboarding/5"


# ---------------------------------------------------------------------------
# Step 5 — Voice personality
# ---------------------------------------------------------------------------


@router.post("/5", response_class=RedirectResponse, status_code=303)
async def step5(
    request: Request,
    piper_voice: Annotated[str, Form()] = "en_US-amy-medium",
) -> str:
    data_dir = request.app.state.data_dir
    s = load_settings(data_dir)
    s.piper_voice = piper_voice
    s.onboarding_step = 6
    save_settings(data_dir, s)
    return "/onboarding/6"


# ---------------------------------------------------------------------------
# Step 6 — Face style
# ---------------------------------------------------------------------------


@router.post("/6", response_class=RedirectResponse, status_code=303)
async def step6(
    request: Request,
    face_theme: Annotated[str, Form()] = "",      # blank = keep persisted default
    display_theme: Annotated[str, Form()] = "",
) -> str:
    data_dir = request.app.state.data_dir
    s = load_settings(data_dir)
    # If the form didn't carry a value (radio not selected), keep whatever
    # was already on the settings model — the persistence layer's default
    # ("vector") is the one source of truth. Onboarding must not silently
    # flip themes for users who re-run the flow after a factory reset.
    if face_theme:
        s.face_theme = face_theme
    if display_theme:
        # Reuse the validation allow-list owned by routes/settings.py so
        # we don't drift on what palettes the React display supports.
        from .settings import _VALID_DISPLAY_THEME_IDS  # noqa: PLC0415

        if display_theme in _VALID_DISPLAY_THEME_IDS:
            s.display_theme = display_theme
    s.onboarding_step = 7
    save_settings(data_dir, s)
    return "/onboarding/7"


# ---------------------------------------------------------------------------
# Step 7 — Permissions
# ---------------------------------------------------------------------------


@router.post("/7", response_class=RedirectResponse, status_code=303)
async def step7(
    request: Request,
    active_window: Annotated[str, Form()] = "",
    clipboard: Annotated[str, Form()] = "",
    camera: Annotated[str, Form()] = "",
    wifi_skills: Annotated[str, Form()] = "on",
    hotkey_combo: Annotated[str, Form()] = "",
    weather_location: Annotated[str, Form()] = "",
) -> str:
    data_dir = request.app.state.data_dir
    s = load_settings(data_dir)
    s.active_window_enabled = active_window == "on"
    s.clipboard_enabled = clipboard == "on"
    s.camera_enabled = camera == "on"
    s.wifi_skills_enabled = wifi_skills == "on"
    s.hotkey_combo = hotkey_combo.strip()
    s.weather_location = weather_location.strip()
    s.onboarding_step = 8
    save_settings(data_dir, s)
    return "/onboarding/8"


# ---------------------------------------------------------------------------
# Step 8 — Work mode
# ---------------------------------------------------------------------------


@router.post("/8", response_class=RedirectResponse, status_code=303)
async def step8(
    request: Request,
    mode: Annotated[str, Form()] = "general",
) -> str:
    data_dir = request.app.state.data_dir
    s = load_settings(data_dir)
    s.mode = mode
    s.onboarding_step = 9
    save_settings(data_dir, s)
    return "/onboarding/9"


# ---------------------------------------------------------------------------
# Step 9 — Complete
# ---------------------------------------------------------------------------


@router.post("/9", response_class=RedirectResponse, status_code=303)
async def step9(
    request: Request,
    owner_name: Annotated[str, Form()] = "",
    first_message: Annotated[str, Form()] = "",
) -> str:
    """Wrap up onboarding. The user can type a first message into the
    bubble — if they do, we land in /chat with it queued (via the
    same hotkey-context pending mechanism that the global hotkey
    uses) so their first conversation turn lights up the moment the
    dashboard loads."""
    data_dir = request.app.state.data_dir
    s = load_settings(data_dir)
    s.owner_name = owner_name.strip()
    s.onboarding_complete = True
    save_settings(data_dir, s)

    msg = first_message.strip()
    if msg:
        # Forward the message to /chat via a query param. The chat
        # page reads `?prefill=…` and auto-fires it on load — same
        # path the user would take by typing it themselves. Avoids
        # tangling onboarding with the chat session builder or the
        # hotkey-context machinery (which is keyed on clipboard
        # permission + has a 60s freshness window we don't want here).
        import urllib.parse  # noqa: PLC0415

        return f"/chat/?prefill={urllib.parse.quote(msg)}"
    return "/"
