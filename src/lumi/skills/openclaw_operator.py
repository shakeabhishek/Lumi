"""Sync Lumi's cloud LLM settings into OpenClaw's gateway config.

When the user adds a cloud LLM provider + API key in /settings/cloud, we
write that into `~/.openclaw/openclaw.json` so the OpenClaw gateway uses
the cloud model as its agent operator. This is the V2 unlock — strong
cloud models can drive OpenClaw's heavy agent loop, which qwen2.5:7b can't.

After updating the config, the OpenClaw gateway needs to be restarted (or
reloaded) to pick up the change. We trigger a restart via the CLI.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from ..log import get_logger
from ..runtime import secrets

log = get_logger(__name__)


# Lumi's provider name → OpenClaw provider config shape.
# `api` matches the protocol family OpenClaw uses to talk to them.
_PROVIDERS: dict[str, dict] = {
    "anthropic": {
        "baseUrl": "https://api.anthropic.com",
        "api": "anthropic",
        "default_model": "claude-opus-4-7",
        "contextWindow": 200000,
        "maxTokens": 8192,
    },
    "openai": {
        "baseUrl": "https://api.openai.com",
        "api": "openai",
        "default_model": "gpt-5",
        "contextWindow": 128000,
        "maxTokens": 4096,
    },
    "gemini": {
        "baseUrl": "https://generativelanguage.googleapis.com",
        "api": "google",
        "default_model": "gemini-2.5-pro",
        "contextWindow": 1000000,
        "maxTokens": 8192,
    },
}


def _openclaw_config_path() -> Path:
    return Path.home() / ".openclaw" / "openclaw.json"


def sync_to_openclaw(provider: str, model: str = "") -> tuple[bool, str]:
    """Write the user's cloud provider + key into OpenClaw's config.

    Returns (ok, message). On `ok=True`, message describes what changed.
    On `ok=False`, message describes why we couldn't wire it.
    """
    cfg_path = _openclaw_config_path()
    if not cfg_path.exists():
        return False, f"OpenClaw config not found at {cfg_path} — run setup.sh first."

    if not provider:
        return _revert_to_ollama(cfg_path)

    if provider not in _PROVIDERS:
        return False, f"Unknown provider: {provider!r}"

    api_key = secrets.get_secret("cloud_llm_api_key")
    if not api_key:
        return False, "Cloud LLM API key is not set in the OS keychain."

    spec = _PROVIDERS[provider]
    model = (model or spec["default_model"]).strip()

    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg.setdefault("models", {}).setdefault("providers", {})[provider] = {
        "baseUrl": spec["baseUrl"],
        "apiKey": api_key,
        "api": spec["api"],
        "models": [
            {
                "id": model,
                "name": model,
                "input": ["text"],
                "contextWindow": spec["contextWindow"],
                "maxTokens": spec["maxTokens"],
            }
        ],
    }
    cfg.setdefault("agents", {}).setdefault("defaults", {})["model"] = {
        "primary": f"{provider}/{model}",
    }
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    log.info("openclaw.operator_synced", provider=provider, model=model)

    restarted = _restart_gateway()
    return True, (
        f"OpenClaw now uses {provider}/{model} as its operator"
        + (" (gateway restarted)." if restarted else " (restart the gateway to apply).")
    )


def _revert_to_ollama(cfg_path: Path) -> tuple[bool, str]:
    """User cleared the cloud key → flip OpenClaw back to local Ollama."""
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg.setdefault("agents", {}).setdefault("defaults", {})["model"] = {
        "primary": "ollama/qwen2.5:7b",
    }
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    log.info("openclaw.operator_reverted_to_local")
    restarted = _restart_gateway()
    return True, (
        "OpenClaw reverted to local qwen2.5:7b"
        + (" (gateway restarted)." if restarted else " (restart the gateway to apply).")
    )


def _restart_gateway() -> bool:
    """Best-effort gateway restart via the CLI. Silent on failure."""
    try:
        env = {**os.environ}
        for k_lower in ("openweathermap_api_key",):
            v = secrets.get_secret(k_lower)
            if v:
                env[k_lower.upper()] = v
        subprocess.run(
            ["npx", "openclaw", "gateway", "start"],
            capture_output=True, timeout=20, check=False, env=env,
        )
        return True
    except Exception as exc:
        log.warning("openclaw.restart_failed", error=str(exc))
        return False
