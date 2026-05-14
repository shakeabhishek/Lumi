from __future__ import annotations

import io
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse

from ..persistence import FACE_THEMES, MODES, PIPER_VOICES, load_settings, save_settings

router = APIRouter()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _render(request: Request, template: str, **ctx: object) -> HTMLResponse:
    s = load_settings(request.app.state.data_dir)
    return request.app.state.templates.TemplateResponse(
        request, template,
        {
            "settings": s,
            "piper_voices": PIPER_VOICES,
            "face_themes": FACE_THEMES,
            "modes": MODES,
            **ctx,
        },
    )


# ---------------------------------------------------------------------------
# Personality — system prompt editor
# ---------------------------------------------------------------------------


@router.get("/personality", response_class=HTMLResponse)
async def personality_get(request: Request) -> HTMLResponse:
    return _render(request, "settings/personality.html")


@router.post("/personality", response_class=RedirectResponse, status_code=303)
async def personality_post(
    request: Request,
    system_prompt_override: Annotated[str, Form()] = "",
) -> str:
    data_dir = request.app.state.data_dir
    s = load_settings(data_dir)
    s.system_prompt_override = system_prompt_override
    save_settings(data_dir, s)
    return "/settings/personality"


# ---------------------------------------------------------------------------
# Voice picker
# ---------------------------------------------------------------------------


@router.get("/voice", response_class=HTMLResponse)
async def voice_get(request: Request) -> HTMLResponse:
    return _render(request, "settings/voice.html")


@router.post("/voice", response_class=RedirectResponse, status_code=303)
async def voice_post(
    request: Request,
    piper_voice: Annotated[str, Form()] = "en_US-amy-medium",
    voice_id_enabled: Annotated[str, Form()] = "",
) -> str:
    data_dir = request.app.state.data_dir
    s = load_settings(data_dir)
    s.piper_voice = piper_voice
    s.voice_id_enabled = voice_id_enabled == "on"
    save_settings(data_dir, s)
    return "/settings/voice"


# ---------------------------------------------------------------------------
# Face theme
# ---------------------------------------------------------------------------


@router.get("/face", response_class=HTMLResponse)
async def face_get(request: Request) -> HTMLResponse:
    return _render(request, "settings/face.html")


@router.post("/face", response_class=RedirectResponse, status_code=303)
async def face_post(
    request: Request,
    face_theme: Annotated[str, Form()] = "pixel",
    face_color: Annotated[str, Form()] = "",
) -> str:
    data_dir = request.app.state.data_dir
    s = load_settings(data_dir)
    s.face_theme = face_theme
    s.face_color = face_color
    save_settings(data_dir, s)
    return "/settings/face"


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------


@router.get("/modes", response_class=HTMLResponse)
async def modes_get(request: Request) -> HTMLResponse:
    return _render(request, "settings/modes.html")


@router.post("/modes", response_class=RedirectResponse, status_code=303)
async def modes_post(
    request: Request,
    mode: Annotated[str, Form()] = "general",
) -> str:
    data_dir = request.app.state.data_dir
    s = load_settings(data_dir)
    s.mode = mode
    save_settings(data_dir, s)
    return "/settings/modes"


# ---------------------------------------------------------------------------
# Data permissions
# ---------------------------------------------------------------------------


@router.get("/data", response_class=HTMLResponse)
async def data_get(request: Request) -> HTMLResponse:
    return _render(request, "settings/data.html")


@router.post("/data", response_class=RedirectResponse, status_code=303)
async def data_post(
    request: Request,
    active_window: Annotated[str, Form()] = "",
    clipboard: Annotated[str, Form()] = "",
    camera: Annotated[str, Form()] = "",
    wifi_skills: Annotated[str, Form()] = "",
    memory_enabled: Annotated[str, Form()] = "",
) -> str:
    data_dir = request.app.state.data_dir
    s = load_settings(data_dir)
    s.active_window_enabled = active_window == "on"
    s.clipboard_enabled = clipboard == "on"
    s.camera_enabled = camera == "on"
    s.wifi_skills_enabled = wifi_skills == "on"
    s.memory_enabled = memory_enabled == "on"
    save_settings(data_dir, s)
    return "/settings/data"


# ---------------------------------------------------------------------------
# Memory browser
# ---------------------------------------------------------------------------


@router.get("/memory", response_class=HTMLResponse)
async def memory_get(request: Request) -> HTMLResponse:
    data_dir = request.app.state.data_dir
    s = load_settings(data_dir)
    conversations: list[str] = []
    if s.memory_enabled:
        try:
            from ....runtime.memory import MemoryStore  # noqa: PLC0415

            if MemoryStore.is_available():
                store = MemoryStore(data_dir)
                conversations_raw = store.get_relevant_context("", n=20)
                conversations = conversations_raw.split("\n\n") if conversations_raw else []
        except Exception:
            pass
    return request.app.state.templates.TemplateResponse(
        request, "settings/memory.html",
        {"settings": s, "conversations": conversations},
    )


# ---------------------------------------------------------------------------
# Data export — "take everything with you"
# ---------------------------------------------------------------------------

# Items that are user data (worth exporting) vs ephemeral caches (skip).
# Excludes anything that can be re-derived: model downloads, embedding caches,
# .ollama logs, etc.
_EXPORT_ITEMS: tuple[str, ...] = (
    "settings.json",
    "audit_log.jsonl",
    "perf.jsonl",
    "notes.jsonl",
    "owner_embedding.npy",
    "chroma",  # ChromaDB directory; included whole
)


@router.get("/data/export")
async def data_export(request: Request) -> StreamingResponse:
    """Stream a ZIP of all user data on disk."""
    data_dir: Path = request.app.state.data_dir
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in _EXPORT_ITEMS:
            src = data_dir / name
            if not src.exists():
                continue
            if src.is_file():
                zf.write(src, arcname=name)
            else:
                for child in src.rglob("*"):
                    if child.is_file():
                        zf.write(child, arcname=str(child.relative_to(data_dir)))
    buf.seek(0)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="lumi-export-{ts}.zip"'},
    )


# ---------------------------------------------------------------------------
# Factory reset — "forget everything"
# ---------------------------------------------------------------------------


@router.post("/data/reset", response_class=RedirectResponse, status_code=303)
async def data_reset(request: Request) -> str:
    """Wipe all user data and reset to first-boot state.

    Removes every file in data_dir except the directory itself. The next page
    load triggers onboarding from step 1.
    """
    data_dir: Path = request.app.state.data_dir
    for child in data_dir.iterdir():
        try:
            if child.is_file() or child.is_symlink():
                child.unlink()
            else:
                shutil.rmtree(child, ignore_errors=True)
        except OSError:
            continue
    return "/onboarding/1"
