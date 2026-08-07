from __future__ import annotations

import io
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Form, Query, Request
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


# ── Settings hub ────────────────────────────────────────────────────────────


# Settings sub-page registry — drives the /settings hub page so a new
# settings section is just an entry here + a route + a template. Each
# tuple is (path, icon-emoji, label, one-line description, group).
# Groups order the cards on the hub.
# Each section: (path, icon, label, description, group). `path` is a
# segment relative to /settings/ — except entries flagged with a
# leading "/" which point outside /settings (used to surface
# /audit-log under the Memory & data group without having to mount
# it inside the settings router).
_SETTINGS_SECTIONS = [
    # Who Lumi is.
    ("personality", "Personality",  "System prompt + the name Lumi answers to.",     "Identity"),
    ("modes",       "Modes",        "Switch between General / Developer / Focus / Dictation.", "Identity"),
    ("voice",       "Voice",        "Pick the TTS voice + manage your enrolled speaker profile.", "Identity"),

    # How Lumi looks.
    ("face",        "Face",         "Pixel / vector / terminal / sprite — and the background palette.", "Appearance"),

    # What Lumi knows about you.
    ("memory",      "Memory",       "Browse what Lumi has learned about you. Toggle on/off here.", "Memory & data"),
    ("data",        "Privacy & permissions",  "Toggle clipboard, active-window, camera, WiFi access. Export or factory-reset.", "Memory & data"),
    ("/audit-log/", "Audit log",    "Every skill invocation, cloud escalation, and direct LLM turn — filter by source.", "Memory & data"),

    # Where Lumi reaches.
    ("cloud",       "Cloud LLM",    "Configure a cloud provider key for smart routing.",     "Connections"),
]


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def settings_hub(request: Request) -> HTMLResponse:
    """Hub page — one place to discover every settings section. Built
    in response to the pre-2026-05-24 IA audit: the only way to reach
    /settings/voice or /settings/cloud was a direct URL or by guessing
    the dropdown wasn't there. The nav now lands here instead of
    forcing the user into /settings/personality."""
    settings = load_settings(request.app.state.data_dir)
    # Group by section while preserving order.
    groups: dict[str, list[dict[str, str]]] = {}
    for path, label, desc, group in _SETTINGS_SECTIONS:
        # Leading "/" → absolute (lets the hub surface non-/settings
        # pages like /audit-log under a Settings group).
        href = path if path.startswith("/") else f"/settings/{path}"
        groups.setdefault(group, []).append({
            "path": href,
            "label": label,
            "desc": desc,
        })
    return _render(
        request, "settings/hub.html",
        settings=settings,
        groups=groups,
    )


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


# Background gradient palettes available on the device display.
# (id, label, swatch) — swatch is a CSS gradient string used as the
# picker's preview chip. Must stay aligned with `_VALID_THEMES` in
# routes/device_display.py and the [data-theme=...] selectors in
# src/lumi/ui/device_display/src/styles/index.css.
DISPLAY_THEMES = [
    ("default",   "Cosmic",     "linear-gradient(135deg,#581c87,#9d174d,#312e81)"),
    ("sunset",    "Sunset",     "linear-gradient(135deg,#f97316,#ec4899,#7c3aed)"),
    ("ocean",     "Ocean",      "linear-gradient(135deg,#1d4ed8,#14b8a6,#22d3ee)"),
    ("forest",    "Forest",     "linear-gradient(135deg,#166534,#059669,#0d9488)"),
    ("sakura",    "Sakura",     "linear-gradient(135deg,#fbcfe8,#fda4af,#f9a8d4)"),
    ("mint",      "Mint",       "linear-gradient(135deg,#6ee7b7,#99f6e4,#67e8f9)"),
    ("lavender",  "Lavender",   "linear-gradient(135deg,#c4b5fd,#ddd6fe,#a5b4fc)"),
    ("monochrome","Monochrome", "linear-gradient(135deg,#374151,#1f2937,#111827)"),
]
_VALID_DISPLAY_THEME_IDS = {t[0] for t in DISPLAY_THEMES}


@router.get("/face", response_class=HTMLResponse)
async def face_get(request: Request) -> HTMLResponse:
    sprite_packs = list_sprite_packs(request.app.state.data_dir)
    return _render(
        request, "settings/face.html",
        sprite_packs=sprite_packs,
        display_themes=DISPLAY_THEMES,
    )


@router.post("/face", response_class=RedirectResponse, status_code=303)
async def face_post(
    request: Request,
    face_theme: Annotated[str, Form()] = "vector",
    face_color: Annotated[str, Form()] = "",
    idle_scene: Annotated[str, Form()] = "none",
    display_theme: Annotated[str, Form()] = "default",
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
    s.display_theme = display_theme if display_theme in _VALID_DISPLAY_THEME_IDS else "default"
    save_settings(data_dir, s)
    # Push a fresh snapshot so the React device-display re-renders
    # with the new palette right away — no F5 needed.
    from .device_display import publish_face_state  # noqa: PLC0415

    await publish_face_state(request, "idle")
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


@router.post("/memory/toggle", response_class=RedirectResponse, status_code=303)
async def memory_toggle(request: Request) -> str:
    """Flip memory_enabled — used by the /settings/memory CTA when
    memory is off and the user wants to turn it on right there
    instead of going hunting through /settings/data.

    Stays a separate route from /settings/data POST so the redirect
    target makes sense (back to /settings/memory, not back to data).
    """
    data_dir = request.app.state.data_dir
    s = load_settings(data_dir)
    s.memory_enabled = not s.memory_enabled
    save_settings(data_dir, s)
    return "/settings/memory"


@router.get("/memory", response_class=HTMLResponse)
async def memory_get(
    request: Request,
    q: str = Query(""),
) -> HTMLResponse:
    """Memory browser. `q=foo` runs a semantic search; empty query
    returns whatever the collection's nearest-neighbour to a blank
    string is — which Chroma happens to treat as "everything",
    yielding recent additions first. Total count is shown so the
    user can tell when memory is silently empty vs full of stuff."""
    data_dir = request.app.state.data_dir
    s = load_settings(data_dir)
    conversations: list[str] = []
    total = 0
    memory_available = False
    if s.memory_enabled:
        try:
            from ....runtime.memory import MemoryStore  # noqa: PLC0415

            if MemoryStore.is_available():
                memory_available = True
                store = MemoryStore(data_dir)
                # Total — surfaces "memory toggle is on but you have 0
                # entries because the deps aren't installed" vs "memory
                # is genuinely empty because you haven't talked yet."
                if store._collection is not None:                 # noqa: SLF001
                    total = store._collection.count()              # noqa: SLF001
                raw = store.get_relevant_context(q or "recent", n=20)
                conversations = raw.split("\n\n") if raw else []
        except Exception:
            pass
    return request.app.state.templates.TemplateResponse(
        request, "settings/memory.html",
        {
            "settings": s,
            "conversations": conversations,
            "memory_available": memory_available,
            "total": total,
            "q": q,
        },
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
    # Gmail App Password + the address it belongs to. Without these here,
    # "Forget everything" would leave working mailbox credentials on disk.
    "gmail_address",
    "gmail_app_password",
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
        secret_backend=secrets.backend_kind(),
    )


@router.post("/cloud", response_class=RedirectResponse, status_code=303)
async def cloud_post(
    request: Request,
    cloud_llm_provider: Annotated[str, Form()] = "",
    cloud_llm_api_key: Annotated[str, Form()] = "",
    cloud_llm_model: Annotated[str, Form()] = "",
    cloud_routing_enabled: Annotated[str, Form()] = "",
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
    s.cloud_routing_enabled = cloud_routing_enabled == "on"

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
