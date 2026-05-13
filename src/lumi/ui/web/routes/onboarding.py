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
from fastapi import APIRouter, Form, Request, UploadFile
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
    extra = {}
    if step == 4:
        extra["clip_count"] = _clip_count(request.app.state.data_dir)
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


@router.post("/4/record", response_class=HTMLResponse)
async def record_clip(request: Request) -> HTMLResponse:
    """Record one 5-second clip from the server's microphone."""
    data_dir = request.app.state.data_dir
    n = _clip_count(data_dir)
    if n >= 3:
        return HTMLResponse('<p class="msg ok">Already have 3 clips — click Complete.</p>')
    try:
        from ....hardware.audio_io import SoundDeviceInput  # noqa: PLC0415
        from ....config import get_settings  # noqa: PLC0415

        cfg = get_settings()
        mic = SoundDeviceInput(sample_rate=cfg.audio_sample_rate, device=cfg.audio_input_device)
        clip = mic.record(5.0)
        np.save(_clips_dir(data_dir) / f"clip_{n}.npy", clip)
        n += 1
    except Exception as exc:
        return HTMLResponse(f'<p class="msg err">Recording failed: {exc}</p>')

    if n < 3:
        return HTMLResponse(
            f'<p class="msg ok">Clip {n}/3 recorded.</p>'
            f'<button class="btn" hx-post="/onboarding/4/record" hx-target="#enroll-status">'
            f"Record clip {n + 1}/3</button>"
        )
    return HTMLResponse(
        '<p class="msg ok">All 3 clips recorded.</p>'
        '<button class="btn primary" hx-post="/onboarding/4/enroll" hx-target="#enroll-status">'
        "Complete enrollment</button>"
    )


@router.post("/4/enroll", response_class=HTMLResponse)
async def enroll(request: Request) -> HTMLResponse:
    data_dir = request.app.state.data_dir
    clips_dir = _clips_dir(data_dir)
    clip_files = sorted(clips_dir.glob("clip_*.npy"))
    if len(clip_files) < 3:
        return HTMLResponse('<p class="msg err">Need 3 clips — record them first.</p>')
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
        return HTMLResponse(
            '<p class="msg ok">Enrolled! '
            '<a href="/onboarding/5" class="btn primary">Continue →</a></p>'
        )
    except Exception as exc:
        return HTMLResponse(f'<p class="msg err">Enrollment failed: {exc}</p>')


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
    face_theme: Annotated[str, Form()] = "pixel",
) -> str:
    data_dir = request.app.state.data_dir
    s = load_settings(data_dir)
    s.face_theme = face_theme
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
) -> str:
    data_dir = request.app.state.data_dir
    s = load_settings(data_dir)
    s.active_window_enabled = active_window == "on"
    s.clipboard_enabled = clipboard == "on"
    s.camera_enabled = camera == "on"
    s.wifi_skills_enabled = wifi_skills == "on"
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
) -> str:
    data_dir = request.app.state.data_dir
    s = load_settings(data_dir)
    s.owner_name = owner_name
    s.onboarding_complete = True
    save_settings(data_dir, s)
    return "/"
