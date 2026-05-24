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
import stat
import subprocess
import tempfile
from pathlib import Path

from ..log import get_logger
from ..runtime import secrets

log = get_logger(__name__)


def _write_config_securely(cfg_path: Path, cfg: dict) -> None:
    """Atomic write + 0600 perms. The file holds a plaintext cloud API key
    (OpenClaw doesn't support keychain refs yet), so it must not be world
    or group readable, and must not appear half-written on crash."""
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        prefix=cfg_path.name + ".", suffix=".tmp", dir=str(cfg_path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)  # 0600 before publishing
        os.replace(tmp, cfg_path)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise


def ensure_config_perms() -> None:
    """One-shot remediation: tighten perms on ~/.openclaw/openclaw.json if it
    holds any of our cloud providers (i.e. contains a plaintext API key) and
    isn't already 0600. Safe to call repeatedly; no-op if file missing or
    already locked down. Called from app startup paths."""
    cfg_path = _openclaw_config_path()
    if not cfg_path.exists():
        return
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        providers = cfg.get("models", {}).get("providers", {}) or {}
        if not any(p in _PROVIDERS for p in providers):
            return                  # nothing sensitive in the file
        mode = cfg_path.stat().st_mode & 0o777
        if mode != (stat.S_IRUSR | stat.S_IWUSR):
            os.chmod(cfg_path, stat.S_IRUSR | stat.S_IWUSR)
            log.info("openclaw.config_perms_tightened", old_mode=oct(mode))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("openclaw.config_perms_check_failed", error=str(exc))


# Lumi's provider name → OpenClaw provider config shape.
# The `api` strings must match OpenClaw's MODEL_APIS enum (in its
# zod-schema.core.js). The canonical set as of OpenClaw 2026.04.20:
#   openai-completions, openai-responses, openai-codex-responses,
#   anthropic-messages, google-generative-ai, github-copilot,
#   bedrock-converse-stream, ollama, azure-openai-responses.
# A wrong value (e.g. just "openai" or "google") makes OpenClaw refuse
# to start the gateway — caught the hard way during V2 verification.
_PROVIDERS: dict[str, dict] = {
    "anthropic": {
        "baseUrl": "https://api.anthropic.com",
        "api": "anthropic-messages",
        "default_model": "claude-opus-4-7",
        "contextWindow": 200000,
        "maxTokens": 8192,
    },
    "openai": {
        "baseUrl": "https://api.openai.com",
        "api": "openai-completions",
        "default_model": "gpt-5",
        "contextWindow": 128000,
        "maxTokens": 4096,
    },
    "gemini": {
        "baseUrl": "https://generativelanguage.googleapis.com",
        "api": "google-generative-ai",
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
    providers = cfg.setdefault("models", {}).setdefault("providers", {})

    # Purge any other Lumi-managed providers before adding the new one.
    # OpenClaw validates the entire providers block on startup — leaving
    # a stale anthropic block with an invalid `api` field around (because
    # we switched to gemini) crashes the gateway. Foreign providers
    # (anything not in _PROVIDERS — e.g. user-added or stock entries
    # like ollama) are preserved.
    for other in [p for p in list(providers) if p in _PROVIDERS and p != provider]:
        providers.pop(other, None)

    providers[provider] = {
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
    _write_config_securely(cfg_path, cfg)
    log.info("openclaw.operator_synced", provider=provider, model=model)

    restarted = _restart_gateway()
    return True, (
        f"OpenClaw now uses {provider}/{model} as its operator"
        + (" (gateway restarted)." if restarted else " (restart the gateway to apply).")
    )


def _revert_to_ollama(cfg_path: Path) -> tuple[bool, str]:
    """User cleared the cloud key → flip OpenClaw back to local Ollama AND
    purge every cloud provider entry so the API key doesn't survive on disk."""
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    providers = cfg.get("models", {}).get("providers", {})
    purged = [p for p in list(providers) if p in _PROVIDERS]
    for p in purged:
        providers.pop(p, None)
    cfg.setdefault("agents", {}).setdefault("defaults", {})["model"] = {
        "primary": "ollama/qwen2.5:7b",
    }
    _write_config_securely(cfg_path, cfg)
    log.info("openclaw.operator_reverted_to_local", purged=purged)
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
