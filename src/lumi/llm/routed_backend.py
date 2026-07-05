"""RoutedBackend — cloud-first LLM with a local fallback.

Wraps a local `LLMBackend` (Ollama/Hailo/Mock) and an optional cloud
client. When cloud is configured, it is tried FIRST for every turn —
local only serves the reply if cloud is unavailable (no network, no
key, request fails) or returns nothing. If no cloud client is
configured at all, RoutedBackend is a transparent passthrough to
local.

Flipped 2026-07-05 from the original local-first-with-escalation
design (local always ran to completion, THEN cloud was tried only if
the local reply looked evasive). That meant an escalated turn paid
local generation time PLUS cloud generation time — the worst-case
latency, not the best. Cloud-first trades "occasional cloud API
spend" for "responsive replies on the model that's actually fast and
capable," which is the tradeoff the user explicitly asked for.

Streaming: cloud is tried via `complete_streaming()` and its FIRST
chunk is peeked before committing — if that first chunk never arrives
(cloud down, key missing, immediate error), nothing has been shown to
the caller yet, so falling back to local is clean. If cloud fails
PARTWAY through (after some chunks were already yielded), we can't
un-yield what's already been shown — splicing in a full local reply
at that point would look like two answers stitched together, so we
just stop and log rather than fabricate a coherent recovery.

Privacy invariant (mirrored from CLAUDE.md V2 roadmap):

  Only the current turn + recent history + system prompt are sent
  to cloud — never the memory store, audit log, clipboard, or
  voice embedding.

Implemented by `_strip_memory_prelude`: ConversationManager injects
retrieved memory snippets as a synthetic user message tagged with
the "RELEVANT PAST CONVERSATION SNIPPETS" header. We detect that
header and drop the message before the cloud call. Other untrusted
context (clipboard / active window) carries the "USER-PROVIDED
CONTEXT" header — kept, because it came from the live turn the user
just took, not historical recall.

Audit logging happens one layer up (SkillRouter → AuditLog). This
class exposes `.last_route` so the caller can label the entry
"routed:local" vs "routed:cloud:gemini".
"""

from __future__ import annotations

import re
from collections.abc import Iterator

from ..log import get_logger
from .ollama_backend import LLMBackend, Message

log = get_logger(__name__)


# Explicit per-turn marker: "cloud: <question>" signals the user wants to
# bypass skill routing and go straight to the LLM. RoutedBackend itself no
# longer branches on this (cloud is tried first for every turn regardless,
# since 2026-07-05's cloud-first flip), but SkillRouter's
# _worth_trying_openclaw() still uses it to skip the OpenClaw bridge for
# an explicit escalation — that's a separate concern from RoutedBackend's
# own local/cloud choice, so the constant stays here as the shared home
# for "what does the cloud: prefix look like."
_EXPLICIT_CLOUD_PREFIX = re.compile(r"^\s*cloud:\s*", re.IGNORECASE)


# ── Cloud-safe message filtering ─────────────────────────────────────────────


_MEMORY_PRELUDE_HEADER = "RELEVANT PAST CONVERSATION SNIPPETS"


def _strip_memory_prelude(messages: list[Message]) -> list[Message]:
    """Return a copy of `messages` with any memory-retrieval user
    message removed. ConversationManager._build_messages() injects
    these with a distinctive header — we detect and drop. Context
    hints (clipboard / active-window, marked "USER-PROVIDED CONTEXT")
    are KEPT because they came from the current turn, not historical
    recall."""
    out = []
    for m in messages:
        if m.get("role") == "user" and _MEMORY_PRELUDE_HEADER in m.get("content", ""):
            log.info("routed.memory_stripped_for_cloud", chars=len(m["content"]))
            continue
        out.append(m)
    return out


# ── Routed backend ───────────────────────────────────────────────────────────


class CloudLLMClient:
    """Minimal duck-typed interface a cloud client must satisfy.
    Implementations live in cloud_clients.py; this class doc is the
    contract.

    A cloud client takes a messages list (same shape as LLMBackend.chat).
    `complete_streaming` is the primary path (RoutedBackend calls it for
    every cloud-first turn); `complete` (full reply, non-streaming) is
    kept for callers that explicitly want a one-shot string.
    """

    def complete(self, messages: list[Message]) -> str:  # pragma: no cover - protocol
        raise NotImplementedError

    def complete_streaming(
        self, messages: list[Message],
    ) -> Iterator[str]:  # pragma: no cover - protocol
        raise NotImplementedError

    @property
    def label(self) -> str:  # pragma: no cover - protocol
        """Returned for audit logging — e.g., 'gemini'."""
        raise NotImplementedError


class RoutedBackend(LLMBackend):
    """Wraps a local LLMBackend + an optional cloud client."""

    def __init__(
        self,
        local: LLMBackend,
        cloud: CloudLLMClient | None = None,
    ) -> None:
        self._local = local
        self._cloud = cloud
        # Inspected by the caller after .chat() completes — populated
        # to "local" or "cloud:<label>" so the audit logger can
        # record which path served the turn.
        self.last_route: str = "local"

    @property
    def model(self) -> str:
        # Local label is the truth on disk for the dashboard /
        # cfg.ollama_model display. The dynamic per-turn route is in
        # last_route + the audit log.
        return self._local.model

    def chat(self, messages: list[Message]) -> Iterator[str]:
        """Yield reply text. Cloud is tried FIRST when configured —
        local only serves the turn if cloud is unavailable or empty.

        The first cloud chunk is peeked before committing: if it never
        arrives, nothing has reached the caller yet, so falling back
        to local is clean. If cloud fails partway through (after some
        chunks were already yielded), we can't un-yield what's been
        shown — splicing in a full local reply at that point would
        look like two answers stitched together, so we stop and log
        rather than fabricate a coherent recovery.
        """
        if self._cloud is None:
            self.last_route = "local"
            yield from self._local.chat(messages)
            return

        cloud_msgs = _strip_memory_prelude(messages)
        cloud_gen: Iterator[str] | None = None
        first_chunk: str | None = None
        try:
            cloud_gen = self._cloud.complete_streaming(cloud_msgs)
            first_chunk = next(cloud_gen, None)
        except Exception as exc:
            log.warning("routed.cloud_unavailable", error=str(exc), provider=self._cloud.label)

        if not first_chunk:
            log.info("routed.cloud_empty_or_unavailable_fallback_local")
            self.last_route = "local"
            yield from self._local.chat(messages)
            return

        self.last_route = f"cloud:{self._cloud.label}"
        chars = len(first_chunk)
        yield first_chunk
        try:
            assert cloud_gen is not None
            for chunk in cloud_gen:
                chars += len(chunk)
                yield chunk
            log.info("routed.cloud_primary", provider=self._cloud.label, chars=chars)
        except Exception as exc:
            log.warning(
                "routed.cloud_stream_interrupted",
                error=str(exc), provider=self._cloud.label, chars_sent=chars,
            )
