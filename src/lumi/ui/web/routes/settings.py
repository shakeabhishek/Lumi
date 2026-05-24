from __future__ import annotations

import io
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse

from ...face.idle_scenes import list_sprite_packs
from ...face.sprite_upload import delete_user_pack, validate_and_extract_zip
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
    sprite_packs = list_sprite_packs(request.app.state.data_dir)
    return _render(request, "settings/face.html", sprite_packs=sprite_packs)


@router.post("/face", response_class=RedirectResponse, status_code=303)
async def face_post(
    request: Request,
    face_theme: Annotated[str, Form()] = "vector",
    face_color: Annotated[str, Form()] = "",
    idle_scene: Annotated[str, Form()] = "none",
) -> str:
    data_dir = request.app.state.data_dir
    s = load_settings(data_dir)
    s.face_theme = face_theme
    s.face_color = face_color
    # Valid idle scenes: "none" + every available sprite pack (bundled or
    # user-uploaded). Anything else falls back to none so we never persist
    # a scene name the React device display can't resolve.
    valid_scenes = {"none", *(p["name"] for p in list_sprite_packs(data_dir))}
    s.idle_scene = idle_scene if idle_scene in valid_scenes else "none"
    save_settings(data_dir, s)
    return "/settings/face"


# ---------------------------------------------------------------------------
# Sprite packs — upload / list / delete idle-scene sprite packs
# ---------------------------------------------------------------------------


@router.get("/sprites", response_class=HTMLResponse)
async def sprites_get(request: Request) -> HTMLResponse:
    return _render(
        request, "settings/sprites.html",
        sprite_packs=list_sprite_packs(request.app.state.data_dir),
    )


@router.post("/sprites/upload", response_class=RedirectResponse, status_code=303)
async def sprites_upload(request: Request) -> str:
    """Upload a ZIP of frame_NNN.png + optional manifest.json.

    Routes through `validate_and_extract_zip` so the validation rules are
    testable in isolation (see test_sprite_upload.py). User packs land at
    data_dir/sprites/<name>/ and override bundled packs with the same name.
    """
    form = await request.form()
    pack_name = str(form.get("pack_name") or "").strip()
    upload = form.get("zipfile")
    if upload is None or not hasattr(upload, "read"):
        return "/settings/sprites?err=" + _q("no file uploaded")
    blob = await upload.read()
    sprites_root = request.app.state.data_dir / "sprites"
    result = validate_and_extract_zip(blob, pack_name, sprites_root)
    if not result.ok:
        return "/settings/sprites?err=" + _q(result.error)
    return f"/settings/sprites?ok={_q(result.pack_name)}"


@router.post("/sprites/delete", response_class=RedirectResponse, status_code=303)
async def sprites_delete(
    request: Request,
    pack_name: Annotated[str, Form()] = "",
) -> str:
    """Delete a user-uploaded pack. Bundled packs are not deletable from
    here (they live in the wheel — they'd come back on the next install)."""
    sprites_root = request.app.state.data_dir / "sprites"
    ok, err = delete_user_pack(pack_name, sprites_root)
    if not ok:
        return "/settings/sprites?err=" + _q(err)

    # If the user just deleted the pack their idle_scene was pointing to,
    # fall back to "none" so the renderer doesn't try to load a vanished pack.
    s = load_settings(request.app.state.data_dir)
    if s.idle_scene == pack_name:
        s.idle_scene = "none"
        save_settings(request.app.state.data_dir, s)
    return "/settings/sprites?deleted=" + _q(pack_name)


def _q(s: str) -> str:
    """URL-quote for redirect query strings."""
    from urllib.parse import quote  # noqa: PLC0415
    return quote(s, safe="")


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
    from ....host_helper.send_to_lumi import default_combo  # noqa: PLC0415

    return _render(request, "settings/data.html", default_hotkey=default_combo())


@router.post("/data", response_class=RedirectResponse, status_code=303)
async def data_post(
    request: Request,
    active_window: Annotated[str, Form()] = "",
    clipboard: Annotated[str, Form()] = "",
    camera: Annotated[str, Form()] = "",
    wifi_skills: Annotated[str, Form()] = "",
    memory_enabled: Annotated[str, Form()] = "",
    hotkey_combo: Annotated[str, Form()] = "",
    weather_location: Annotated[str, Form()] = "",
) -> str:
    data_dir = request.app.state.data_dir
    s = load_settings(data_dir)
    s.active_window_enabled = active_window == "on"
    s.clipboard_enabled = clipboard == "on"
    s.camera_enabled = camera == "on"
    s.wifi_skills_enabled = wifi_skills == "on"
    s.memory_enabled = memory_enabled == "on"
    s.hotkey_combo = hotkey_combo.strip()
    s.weather_location = weather_location.strip()
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


# Known secret keys we've ever stored in the OS keychain. Factory reset
# walks this list and deletes each — without it, API keys survive "Forget
# everything" and silently re-enable cloud mode on the next launch.
# Add new keychain names here when introduced.
_KNOWN_SECRET_KEYS: tuple[str, ...] = (
    "cloud_llm_api_key",
    "openweathermap_api_key",
)


@router.post("/data/reset", response_class=RedirectResponse, status_code=303)
async def data_reset(request: Request) -> str:
    """Wipe ALL user-specific state and reset to first-boot.

    Scope of the wipe — anything that ever held PII or user preferences:
      1. Every file in data_dir (conversations, audit log, voice embedding,
         settings, hotkey-pending, notes, journal, perf log, ChromaDB).
      2. Every known keychain entry (cloud LLM key, OpenWeatherMap key).
      3. The providers block in ~/.openclaw/openclaw.json (where the cloud
         API key gets mirrored for the OpenClaw gateway) — purged via
         `openclaw_operator._revert_to_ollama` which also flips the agent
         default back to local Ollama.
      4. The in-memory chat session on app.state (carries the Pseudonymizer
         mapping for the current process).

    Next page load triggers onboarding from step 1.
    """
    from ....runtime import secrets as _secrets  # noqa: PLC0415

    data_dir: Path = request.app.state.data_dir

    # 1. data_dir contents
    if data_dir.exists():
        for child in data_dir.iterdir():
            try:
                if child.is_file() or child.is_symlink():
                    child.unlink()
                else:
                    shutil.rmtree(child, ignore_errors=True)
            except OSError:
                continue

    # 2. OS keychain entries — every name we know we've ever set
    for key in _KNOWN_SECRET_KEYS:
        try:
            _secrets.delete_secret(key)
        except Exception:        # noqa: BLE001
            # delete_secret is already silent on most errors; this is
            # defence in depth — never let a key-deletion failure block
            # the rest of the wipe.
            continue

    # 3. OpenClaw config providers block (mirrored plaintext API key)
    try:
        from ....skills.openclaw_operator import _openclaw_config_path, _revert_to_ollama  # noqa: PLC0415

        cfg_path = _openclaw_config_path()
        if cfg_path.exists():
            _revert_to_ollama(cfg_path)
    except Exception:            # noqa: BLE001
        # OpenClaw might not be installed; don't block reset on it.
        pass

    # 4. Drop the cached chat session so the next request rebuilds with
    #    fresh state (and the old Pseudonymizer mapping doesn't survive).
    if hasattr(request.app.state, "chat_session"):
        del request.app.state.chat_session

    return "/onboarding/1"


# ---------------------------------------------------------------------------
# Cloud LLM fallback config (V2 routing reads these)
# ---------------------------------------------------------------------------

_VALID_PROVIDERS = ("", "openai", "anthropic", "gemini")
_CLOUD_KEY_NAME = "cloud_llm_api_key"


@router.get("/cloud", response_class=HTMLResponse)
async def cloud_get(request: Request) -> HTMLResponse:
    from ....runtime import secrets  # noqa: PLC0415

    existing = secrets.get_secret(_CLOUD_KEY_NAME)
    return _render(
        request, "settings/cloud.html",
        key_mask=secrets.mask(existing),
        secrets_available=secrets.is_available(),
    )


@router.post("/cloud", response_class=RedirectResponse, status_code=303)
async def cloud_post(
    request: Request,
    cloud_llm_provider: Annotated[str, Form()] = "",
    cloud_llm_api_key: Annotated[str, Form()] = "",
    cloud_llm_model: Annotated[str, Form()] = "",
    clear_key: Annotated[str, Form()] = "",
    clear_confirm: Annotated[str, Form()] = "",
) -> str:
    from ....runtime import secrets  # noqa: PLC0415
    from ....skills.openclaw_operator import sync_to_openclaw  # noqa: PLC0415

    data_dir = request.app.state.data_dir
    s = load_settings(data_dir)
    provider = cloud_llm_provider.strip().lower()
    if provider not in _VALID_PROVIDERS:
        provider = ""
    s.cloud_llm_provider = provider
    s.cloud_llm_model = cloud_llm_model.strip()

    # Defence-in-depth: the UI shows a two-step confirmation requiring the
    # literal word "clear", but a hand-crafted form post could still hit
    # the route with only clear_key=1. Reject it server-side too.
    if clear_key and clear_confirm.strip().lower() == "clear":
        secrets.delete_secret(_CLOUD_KEY_NAME)
        s.cloud_llm_api_key_set = False
    elif cloud_llm_api_key.strip():
        try:
            secrets.set_secret(_CLOUD_KEY_NAME, cloud_llm_api_key.strip())
            s.cloud_llm_api_key_set = True
        except secrets.BackendUnavailable:
            s.cloud_llm_api_key_set = False
    save_settings(data_dir, s)

    # Sync to OpenClaw (writes provider+key into ~/.openclaw/openclaw.json and
    # restarts the gateway). Best-effort: if OpenClaw isn't installed, just
    # log and continue.
    if s.cloud_llm_api_key_set and provider:
        try:
            sync_to_openclaw(provider, s.cloud_llm_model)
        except Exception:
            pass
    elif not s.cloud_llm_api_key_set:
        try:
            sync_to_openclaw("")  # revert OpenClaw to local
        except Exception:
            pass

    # Drop the cached chat session so it picks up the new runtime_mode.
    if hasattr(request.app.state, "chat_session"):
        del request.app.state.chat_session

    return "/settings/cloud"
