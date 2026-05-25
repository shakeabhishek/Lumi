"""User settings persistence — JSON file stored in data_dir.

These settings are written by the web UI onboarding + dashboard and read by
the voice loop on startup. They live alongside the audit log and embeddings in
data_dir so everything the user configured is in one place.
"""

from __future__ import annotations

import json as _json
import os as _os
import tempfile as _tempfile
from pathlib import Path

from pydantic import BaseModel, Field

AVAILABLE_SKILLS: list[str] = [
    "weather",
    "timer",
    "unit_converter",
    "wikipedia_lookup",
    "file_search",
]


# Native (always-on, local Python) skills the dashboard knows how to
# show + toggle. Keys MUST match the names SkillRouter uses internally
# (lowercased class name minus "Skill"; see SkillRouter._skill_name).
# Each entry is what the user sees in /skills + an example trigger so
# the listing reads as "what can I say" rather than "what's installed."
NATIVE_SKILLS: list[dict[str, str]] = [
    {"name": "timer",         "label": "Timer",          "example": "Set a timer for 5 minutes"},
    {"name": "reminder",      "label": "Reminder",       "example": "Remind me to call mom in 20 minutes"},
    {"name": "pomodoro",      "label": "Pomodoro",       "example": "Start a pomodoro"},
    {"name": "mode_switch",   "label": "Mode switch",    "example": "Switch to focus mode"},
    {"name": "volume",        "label": "Volume",         "example": '"Louder" / "quieter"'},
    {"name": "systemstats",   "label": "System stats",   "example": "How's my machine doing?"},
    {"name": "clipboard",     "label": "Clipboard",      "example": "What's on my clipboard?"},
    {"name": "todo",          "label": "Todos",          "example": "Todo: ship the feature"},
    {"name": "notes",         "label": "Notes",          "example": "Remember that I take oat milk"},
]

PIPER_VOICES: list[dict[str, str]] = [
    {"id": "en_US-amy-medium",     "label": "Amy (US, warm)"},
    {"id": "en_US-lessac-medium",  "label": "Lessac (US, clear)"},
    {"id": "en_US-ryan-medium",    "label": "Ryan (US, calm)"},
    {"id": "en_GB-jenny-diphone",  "label": "Jenny (UK, bright)"},
]

LUMI_NAMES: list[str] = [
    "Lumi", "Aria", "Nova", "Sage", "Atlas",
    "Iris", "Juno", "Hugo", "Echo", "Pip",
]

MODES: list[dict[str, str]] = [
    {"id": "general",    "label": "General",    "desc": "Everyday assistant"},
    {"id": "code",       "label": "Developer",  "desc": "Code-focused, concise"},
    {"id": "focus",      "label": "Focus",      "desc": "No interruptions, minimal replies"},
    {"id": "dictation",  "label": "Dictation",  "desc": "Transcribe what you say"},
]

FACE_THEMES: list[dict[str, str]] = [
    {"id": "vector",   "label": "Vector",   "desc": "Live Twemoji emoji that change with Lumi's mood"},
    {"id": "terminal", "label": "Bear",     "desc": "Cute kawaii bear ʕ♥ᴥ♥ʔ on a phosphor terminal"},
    {"id": "pixel",    "label": "Pixel",    "desc": "Big pink pixel heart, blinks softly"},
]
# id="terminal" is kept for backwards-compat with existing settings, but the
# renderer is no longer the creepy ASCII box-eye art — it's a cute kawaii bear.


class UserSettings(BaseModel):
    # Identity
    lumi_name: str = "Lumi"
    owner_name: str = ""

    # TTS voice
    piper_voice: str = "en_US-amy-medium"

    # Speaker verification
    voice_id_enrolled: bool = False
    voice_id_enabled: bool = False

    # Face
    face_theme: str = "vector"
    # Ambient scene shown when Lumi is IDLE instead of the face.
    # "none" (default) = face floats alone; any other value is a sprite
    # pack name (bundled or uploaded under /settings/sprites).
    idle_scene: str = "none"
    face_color: str = ""  # empty = use per-theme default
    # Background gradient palette for the device display. Independent
    # of face_theme — that picks WHO is drawn (pixel/vector/terminal/
    # sprite); display_theme picks the colour wash behind them. Values
    # must match the [data-theme=...] selectors in
    # device_display/src/styles/index.css.
    display_theme: str = "default"

    # Cloud routing — when True (and a cloud_llm_provider + key are
    # configured), RoutedBackend re-asks the cloud LLM whenever the
    # local model emits a low-confidence reply ("I don't know" /
    # short / boilerplate). See llm/routed_backend.py for the gating
    # signals. Off by default — opt-in because every escalated turn
    # is a network round-trip and a cloud-API spend.
    cloud_routing_enabled: bool = False

    # Conversation mode
    mode: str = "general"

    # Memory
    memory_enabled: bool = False

    # Skills
    openclaw_enabled: bool = True
    enabled_skills: list[str] = Field(default_factory=lambda: list(AVAILABLE_SKILLS))
    # Native skills are always-on by default — opt-out lives here as
    # an explicit deny-list rather than a positive list, so adding a
    # new native skill in code doesn't silently leave it disabled for
    # existing users (a positive list would have stale defaults).
    # The names match the keys in NATIVE_SKILLS below.
    disabled_native_skills: list[str] = Field(default_factory=list)

    # Permissions
    active_window_enabled: bool = False
    clipboard_enabled: bool = False
    camera_enabled: bool = False
    wifi_skills_enabled: bool = True

    # Send-to-Lumi hotkey (empty = platform default: cmd+shift+l on macOS, ctrl+shift+l elsewhere)
    hotkey_combo: str = ""

    # City Lumi uses for the weather chip on the device display.
    # Empty = no weather shown (just the clock). Asked in onboarding step 7.
    weather_location: str = ""

    # Cloud LLM fallback — V1 stores config; V2 wires the routing.
    # The API KEY ITSELF is NOT in this file — it lives in the OS keychain
    # via lumi.runtime.secrets. user_settings.json holds only the
    # non-sensitive flag below so the UI knows a key is set.
    cloud_llm_provider: str = ""           # "", "openai", "anthropic", "gemini"
    cloud_llm_api_key_set: bool = False    # mirror of "is there a secret in the keychain?"
    cloud_llm_model: str = ""              # provider-specific model id; empty = provider default

    # System prompt override (empty = use defaults from prompts.py)
    system_prompt_override: str = ""

    # Onboarding state
    onboarding_complete: bool = False
    onboarding_step: int = 1


def _settings_path(data_dir: Path) -> Path:
    return data_dir / "user_settings.json"


def load_settings(data_dir: Path) -> UserSettings:
    p = _settings_path(data_dir)
    if not p.exists():
        return UserSettings()
    try:
        # Read raw JSON first so we can lift any legacy plaintext API key out
        # of the file and into the OS keychain before constructing the model.
        raw = _json.loads(p.read_text(encoding="utf-8"))
        _migrate_plaintext_api_key(data_dir, raw)
        return UserSettings.model_validate(raw)
    except Exception:
        return UserSettings()


def _migrate_plaintext_api_key(data_dir: Path, raw: dict) -> None:
    """One-time migration: previously cloud_llm_api_key was stored in this JSON.

    If we see one, move it to the OS keychain, set the boolean flag, and
    rewrite the file without the plaintext field. Silent no-op if the key
    field isn't present or empty.
    """
    if "cloud_llm_api_key" not in raw:
        return
    legacy = raw.pop("cloud_llm_api_key", "") or ""
    if not legacy:
        raw["cloud_llm_api_key_set"] = False
        _atomic_write(data_dir, raw)
        return
    try:
        from ...runtime.secrets import set_secret  # noqa: PLC0415
        set_secret("cloud_llm_api_key", legacy)
        raw["cloud_llm_api_key_set"] = True
    except Exception:
        # If the keychain isn't reachable we leave the flag false; the user
        # will be asked to re-enter the key. Better than holding plaintext.
        raw["cloud_llm_api_key_set"] = False
    _atomic_write(data_dir, raw)


def _atomic_write_text(path: Path, payload: str) -> None:
    """Write `payload` to `path` atomically via tempfile + os.replace.

    A crash mid-write must not leave user_settings.json half-flushed —
    the next launch reads the truncated file as invalid JSON and we
    fall back to a brand-new UserSettings(), silently wiping the user's
    onboarding state, voice ID flag, skill toggles, etc.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = _tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent),
    )
    try:
        with _os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
        _os.replace(tmp, path)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise


def _atomic_write(data_dir: Path, raw: dict) -> None:
    """Back-compat wrapper for the migration path. Atomic now too."""
    _atomic_write_text(_settings_path(data_dir), _json.dumps(raw, indent=2))


def save_settings(data_dir: Path, settings: UserSettings) -> None:
    _atomic_write_text(_settings_path(data_dir), settings.model_dump_json(indent=2))
