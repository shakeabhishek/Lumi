"""User settings persistence — JSON file stored in data_dir.

These settings are written by the web UI onboarding + dashboard and read by
the voice loop on startup. They live alongside the audit log and embeddings in
data_dir so everything the user configured is in one place.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

AVAILABLE_SKILLS: list[str] = [
    "weather",
    "timer",
    "unit_converter",
    "wikipedia_lookup",
    "file_search",
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
    {"id": "pixel",    "label": "Pixel",    "desc": "Chunky 8-bit pixel art with heart eyes"},
    {"id": "vector",   "label": "Vector",   "desc": "Smooth geometric shapes with expressive brows"},
    {"id": "terminal", "label": "Terminal", "desc": "Classic green phosphor CRT style"},
]


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
    face_color: str = ""  # empty = use per-theme default

    # Conversation mode
    mode: str = "general"

    # Memory
    memory_enabled: bool = False

    # Skills
    openclaw_enabled: bool = True
    enabled_skills: list[str] = Field(default_factory=lambda: list(AVAILABLE_SKILLS))

    # Permissions
    active_window_enabled: bool = False
    clipboard_enabled: bool = False
    camera_enabled: bool = False
    wifi_skills_enabled: bool = True

    # Send-to-Lumi hotkey (empty = platform default: cmd+shift+l on macOS, ctrl+shift+l elsewhere)
    hotkey_combo: str = ""

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
        return UserSettings.model_validate_json(p.read_text(encoding="utf-8"))
    except Exception:
        return UserSettings()


def save_settings(data_dir: Path, settings: UserSettings) -> None:
    p = _settings_path(data_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(settings.model_dump_json(indent=2), encoding="utf-8")
