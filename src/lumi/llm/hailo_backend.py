"""HailoBackend — local LLM inference on the AI HAT+ 2 (Pi 5 hardware path).

Talks to Hailo-Ollama on port 8000 directly. Most of the wire protocol is
Ollama-compatible, but Hailo's `/api/chat` has a few stricter rules than
upstream Ollama. We sanitize at the call site so callers don't need to
care:

  - Strip control characters from user content (Hailo 5.3.0+ rejects them
    rather than tolerating them).
  - Strip literal newlines inside user content (also a hard error).
  - Drop `system`-role messages on conversation continuations (Hailo lets
    them appear only as the FIRST message). We keep the leading system
    prompt, drop any subsequent ones.
  - Bound max user content size and history turns so a runaway prompt
    doesn't blow Hailo's request budget.

Why we ported the quirks into HailoBackend rather than depending on the
external adapter: Lumi V1 runtime is a direct LLM client (no OpenClaw
gateway involved), so we don't need a separate FastAPI translator on
port 11435. A second process is overhead V1 doesn't need.

Credit: protocol observations distilled from
https://github.com/tishyk/hailo-ollama-openclaw-adapter (MIT, 2026.04.20).
That adapter is still the right deployment for V2 when OpenClaw drives
orchestration — at that point it sits between OpenClaw and Hailo and we
keep this backend pointed at Hailo directly.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx

from ..log import get_logger
from .ollama_backend import LLMBackend, Message

log = get_logger(__name__)

# Maximum sizes — chosen to fit within Hailo's accepted request budget
# while leaving room for our system prompt and tool outputs.
_MAX_USER_CONTENT_CHARS = 4000
_MAX_HISTORY_TURNS = 6
_REQUEST_TIMEOUT_S = 180.0


def _sanitize_content(text: str) -> str:
    """Drop control chars + literal newlines that Hailo 5.3.0 rejects."""
    if not text:
        return text
    # Strip all C0 + C1 control chars EXCEPT keep spaces. Newlines/CR/tabs go.
    cleaned = re.sub(r"[\x00-\x1f\x7f-\x9f]", " ", text)
    # Collapse runs of whitespace into single spaces so we don't pile up "   ".
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) > _MAX_USER_CONTENT_CHARS:
        cleaned = cleaned[:_MAX_USER_CONTENT_CHARS] + " …[truncated]"
    return cleaned


def _normalize_messages(messages: list[Message]) -> list[Message]:
    """Apply Hailo's stricter rules: keep only the FIRST system message,
    sanitize content, and trim history to a sane window."""
    out: list[Message] = []
    seen_system = False
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if role == "system":
            if seen_system:
                # Drop subsequent system messages — Hailo treats them as an error
                # on conversation continuations.
                continue
            seen_system = True
            out.append({"role": "system", "content": _sanitize_content(content)})
            continue
        out.append({"role": role, "content": _sanitize_content(content)})

    # Trim to last _MAX_HISTORY_TURNS turns AFTER the system message.
    system_msgs = [m for m in out if m["role"] == "system"]
    tail = [m for m in out if m["role"] != "system"][-(_MAX_HISTORY_TURNS * 2):]
    return [*system_msgs, *tail]


class HailoBackend(LLMBackend):
    """Streams token chunks from a Hailo-compiled LLM on the AI HAT+ 2.

    Constructor mirrors OllamaBackend's shape so dispatch in
    `make_llm_backend` reads cleanly. The default URL points at
    Hailo-Ollama's actual port; callers don't need to know about the
    quirks sanitized in `_normalize_messages`.
    """

    def __init__(
        self,
        model_path: Path | str | None = None,            # kept for compat (model name only on Pi)
        model_name: str = "qwen3:1.7b",
        host: str = "http://127.0.0.1:8000",
    ) -> None:
        self._model_name = model_name
        self._host = host.rstrip("/")
        # `model_path` is informational — Hailo loads .hef files at its own startup;
        # we just refer to the loaded model by name here.
        self._model_path = Path(model_path) if model_path else None

    @property
    def model(self) -> str:
        return f"hailo:{self._model_name}"

    def chat(self, messages: list[Message]) -> Iterator[str]:
        normalized = _normalize_messages(messages)
        try:
            with httpx.stream(
                "POST",
                f"{self._host}/api/chat",
                json={
                    "model": self._model_name,
                    "messages": normalized,
                    "stream": True,
                },
                timeout=_REQUEST_TIMEOUT_S,
            ) as r:
                r.raise_for_status()
                for raw in r.iter_lines():
                    if not raw:
                        continue
                    chunk = self._extract_delta(raw)
                    if chunk:
                        yield chunk
        except httpx.HTTPError as exc:
            log.warning("hailo.http_error", error=str(exc), host=self._host)
            return

    # ── internals ──────────────────────────────────────────────────────────

    @staticmethod
    def _extract_delta(raw_line: str) -> str:
        """Hailo-Ollama emits JSON lines like Ollama's /api/chat stream.

        Each line is a JSON object with `message.content` (incremental token)
        and `done` (final flag). We yield the incremental content.
        """
        import json  # noqa: PLC0415

        try:
            obj: dict[str, Any] = json.loads(raw_line)
        except json.JSONDecodeError:
            return ""
        msg = obj.get("message") or {}
        return msg.get("content", "") or ""
