"""HailoBackend — local LLM inference on the AI HAT+ 2 (Pi 5 hardware path).

Talks to Hailo-Ollama on port 8000 directly. Most of the wire protocol
is Ollama-compatible, but Hailo's `/api/chat` has several stricter
rules than upstream Ollama. We sanitise at the call site so callers
don't need to care:

  1. **Control chars stripped from every string in the JSON tree.**
     Hailo 5.3.0+ rejects C0/C1 control chars anywhere — not just in
     `messages[].content`. We deep-sanitise the entire request payload
     before serialising.
  2. **Newlines flattened to spaces** inside content. Hailo's prompt
     renderer re-encodes content through an internal template that
     doesn't escape newlines, so any literal newline (even when the
     outer JSON correctly escapes it) causes a parse error.
  3. **Strict ASCII JSON.** We encode with `ensure_ascii=True` so
     non-ASCII chars (emoji, accented letters) are `\\uXXXX` escaped.
     Hailo's parser is happier with ASCII-only bytes on the wire.
  4. **Drop empty/placeholder messages.** Any turn with whitespace-only
     content is filtered before sending — Hailo trips on those.
  5. **No `system`-role on continuations.** Hailo accepts a system
     message only as the FIRST element. We keep the leading system
     prompt and drop any subsequent ones.
  6. **Conversations must START on a user turn** (after the optional
     leading system message). If the first non-system message is
     somehow `assistant`, we trim it.
  7. **Bounded sizes.** Max user content + history turns so a runaway
     prompt doesn't blow Hailo's request budget.

Why these are in-process and not in a separate FastAPI adapter
(tishyk/hailo-ollama-openclaw-adapter): Lumi V1 is a direct LLM client
and is the only thing on the Pi that talks to Hailo. OpenClaw in V2
cloud mode points at a cloud provider, not Hailo, so there's no need
for an Ollama-shaped HTTP shim. One fewer process, one fewer pinned
external repo to track. The rule set above was distilled from
tishyk's adapter (MIT, 2026.04.20) — if Hailo 5.4+ introduces a new
quirk, port it here.
"""

from __future__ import annotations

import json
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

_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def _sanitize_content(text: str) -> str:
    """Drop control chars + literal newlines that Hailo 5.3.0 rejects.

    Returns a single-line, control-char-free string. Truncates to
    `_MAX_USER_CONTENT_CHARS` with a "…[truncated]" suffix.
    """
    if not text:
        return text
    cleaned = _CONTROL_CHARS_RE.sub(" ", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) > _MAX_USER_CONTENT_CHARS:
        cleaned = cleaned[:_MAX_USER_CONTENT_CHARS] + " …[truncated]"
    return cleaned


def _deep_sanitize(obj: Any) -> Any:
    """Recursive content-char strip across the full JSON tree.

    Hailo 5.3.0+ rejects control characters in ANY string field, not just
    in `messages[].content`. A literal NUL in the model name or a stray
    \\x1b in a metadata field is enough to 400 the request. Walk the
    payload before serialising so we don't have to enumerate fields.
    """
    if isinstance(obj, str):
        return _CONTROL_CHARS_RE.sub("", obj)
    if isinstance(obj, dict):
        return {k: _deep_sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_deep_sanitize(item) for item in obj]
    return obj


def _encode_for_hailo(payload: dict) -> bytes:
    """JSON-encode with `ensure_ascii=True` after deep-sanitising.

    Two reasons for the ASCII-only encoding: (a) Hailo's parser is
    happier with ASCII bytes, and (b) the resulting wire form is
    deterministic regardless of the user's locale — so debugging a
    failed request from a tcpdump capture is easier.
    """
    return json.dumps(_deep_sanitize(payload), ensure_ascii=True).encode("utf-8")


def _normalize_messages(messages: list[Message]) -> list[Message]:
    """Apply Hailo's stricter rules in order:

    1. Sanitize every message's content (control chars + newlines + cap).
    2. Drop messages whose sanitized content is empty.
    3. Keep only the FIRST system message (Hailo rejects mid-stream system).
    4. After the system message, the conversation must START with a user
       turn — if the first non-system message is `assistant`, trim it.
    5. Cap history to the last `_MAX_HISTORY_TURNS` user+assistant turns.
    """
    sanitized: list[Message] = []
    seen_system = False
    for msg in messages:
        role = msg.get("role", "")
        raw = msg.get("content", "")
        content = _sanitize_content(raw)
        if not content:
            continue                            # drop empty/placeholder
        if role == "system":
            if seen_system:
                continue                        # only the first survives
            seen_system = True
        sanitized.append({"role": role, "content": content})

    system_msgs = [m for m in sanitized if m["role"] == "system"][:1]
    non_system = [m for m in sanitized if m["role"] != "system"]
    # Drop a leading assistant turn — Hailo wants the conversation to
    # open on the user side once the system prompt is in place.
    while non_system and non_system[0]["role"] != "user":
        non_system = non_system[1:]
    tail = non_system[-(_MAX_HISTORY_TURNS * 2):]
    return [*system_msgs, *tail]


class HailoBackend(LLMBackend):
    """Streams token chunks from a Hailo-compiled LLM on the AI HAT+ 2.

    Constructor mirrors OllamaBackend's shape so dispatch in
    `make_llm_backend` reads cleanly. Defaults point at Hailo-Ollama's
    native endpoint on the Pi (:8000). Override via the LUMI_HAILO_HOST
    env var if you've put Hailo behind a different host or port.
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
        payload = {
            "model": self._model_name,
            "messages": normalized,
            "stream": True,
        }
        body = _encode_for_hailo(payload)
        try:
            with httpx.stream(
                "POST",
                f"{self._host}/api/chat",
                content=body,
                headers={"Content-Type": "application/json"},
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
        try:
            obj: dict[str, Any] = json.loads(raw_line)
        except json.JSONDecodeError:
            return ""
        msg = obj.get("message") or {}
        return msg.get("content", "") or ""
