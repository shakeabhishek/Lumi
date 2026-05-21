"""Shared session-building helpers for the voice loop and the web chat.

Two entry surfaces (CLI `lumi run` and FastAPI `/chat/`) need the same
runtime wiring around OpenClaw: pick the right mode based on whether a
cloud LLM key is configured, attach a Pseudonymizer in cloud mode so PII
never leaves the device unmasked, and remediate legacy on-disk configs.

This module centralizes that policy so the two paths can't drift apart
again (audit #3 was caused by exactly that drift).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..log import get_logger
from ..skills.openclaw_bridge import OpenClawBridge
from ..skills.openclaw_operator import ensure_config_perms
from .privacy import Pseudonymizer

if TYPE_CHECKING:
    from ..ui.web.persistence import UserSettings

log = get_logger(__name__)


CloudBundle = tuple[OpenClawBridge | None, Pseudonymizer | None, str]


def build_cloud_bridge(
    user: UserSettings,
    *,
    openclaw_enabled: bool,
    timeout: float = 30.0,
) -> CloudBundle:
    """Return (bridge, pseudonymizer, runtime_mode) for the given user.

    Modes:
      "openclaw_cloud" — user has set a cloud provider AND key. Bridge
        shells out to `npx openclaw agent`; Pseudonymizer masks PII
        before any subprocess call.
      "ollama"         — V1 hybrid floor. Bridge does direct Ollama
        tool_calls into our Python skill impls. No Pseudonymizer needed.

    Returns (None, None, "ollama") if openclaw is disabled at the system
    level — the router then falls through to the direct LLM path.

    In cloud mode this also tightens perms on a legacy world-readable
    ~/.openclaw/openclaw.json so the plaintext API key isn't readable
    by other local users or backed up by cloud-sync agents.
    """
    if not openclaw_enabled:
        return None, None, "ollama"

    cloud_active = bool(
        user.openclaw_enabled
        and user.cloud_llm_api_key_set
        and user.cloud_llm_provider
    )
    runtime_mode = "openclaw_cloud" if cloud_active else "ollama"

    pseudo: Pseudonymizer | None = None
    if runtime_mode == "openclaw_cloud":
        ensure_config_perms()
        extra = [user.owner_name] if user.owner_name else []
        pseudo = Pseudonymizer(extra_names=extra)

    bridge = OpenClawBridge(
        runtime_mode=runtime_mode,
        pseudonymizer=pseudo,
        timeout=timeout,
    )
    log.info("session.bridge_built", mode=runtime_mode, pseudonymized=pseudo is not None)
    return bridge, pseudo, runtime_mode
