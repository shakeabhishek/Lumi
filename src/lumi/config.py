"""Centralized runtime configuration.

All settings load from environment variables (or a .env file) with `LUMI_` prefix.
See .env.example for the full surface.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMBackendName(str, Enum):
    OLLAMA = "ollama"
    HAILO = "hailo"
    MOCK = "mock"


class FaceTheme(str, Enum):
    PIXEL = "pixel"
    VECTOR = "vector"
    TERMINAL = "terminal"


class Mode(str, Enum):
    GENERAL = "general"
    CODE = "code"
    FOCUS = "focus"
    DICTATION = "dictation"


class WakeStrategy(str, Enum):
    PUSH_TO_TALK = "push_to_talk"
    WAKE_WORD = "wake_word"
    PRESENCE = "presence"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LUMI_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM
    llm_backend: LLMBackendName = LLMBackendName.OLLAMA
    ollama_host: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen2.5:1.5b"

    # Audio
    audio_input_device: str | None = None
    audio_output_device: str | None = None
    audio_sample_rate: int = 16000
    audio_record_duration_s: float = 5.0

    # STT
    whisper_model: str = "tiny"
    whisper_compute: str = "int8"

    # TTS
    piper_voice: str = "en_US-amy-medium"

    # Face
    face_width: int = 480
    face_height: int = 320
    face_fps: int = 30
    face_theme: FaceTheme = FaceTheme.PIXEL
    # Foreground hex color. Defaults per theme: pixel=#FF6B9D, vector=#F5A623, terminal=#33FF33.
    # Set LUMI_FACE_COLOR to override (e.g. "#FF6B9D" for pink, "#00BFFF" for blue).
    face_color: str = ""

    # OpenClaw
    openclaw_enabled: bool = True
    openclaw_url: str = "http://127.0.0.1:18789"
    openclaw_token: str = "lumi-dev-token"

    # Memory (requires [memory] extra)
    memory_enabled: bool = False

    # Speaker verification (requires [voice] extra + enrollment)
    voice_id_enabled: bool = False

    # Runtime
    mode: Mode = Mode.GENERAL
    wake: WakeStrategy = WakeStrategy.PUSH_TO_TALK
    log_level: str = "INFO"

    # Paths
    data_dir: Path = Field(default_factory=lambda: Path("./data"))
    models_dir: Path = Field(default_factory=lambda: Path("./models"))

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.models_dir.mkdir(parents=True, exist_ok=True)


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
        _settings.ensure_dirs()
    return _settings
