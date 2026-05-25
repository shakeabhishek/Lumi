"""RoutedBackend — local-first LLM with cloud escalation on low confidence.

Wraps a local `LLMBackend` (Ollama/Hailo/Mock) and an optional cloud
client. The local backend always runs first. If its reply trips a
low-confidence signal — short, "I don't know"–style, or matches an
explicit user marker — RoutedBackend discards the local reply and
re-asks the cloud LLM with the same messages, then yields the cloud
reply instead. If cloud is unavailable or also fails, the local
reply is returned as the safest fallback.

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


# ── Confidence detection ─────────────────────────────────────────────────────


# Phrases the local model emits when it doesn't have a good answer.
# Match anywhere in the reply, case-insensitive. Designed to catch
# qwen2.5/llama-style boilerplate without false-positive on real
# answers that happen to contain "know" or "sure".
_LOW_CONFIDENCE_MARKERS = re.compile(
    r"(?:^|\b)("
    r"i\s+don't\s+know|i\s+do\s+not\s+know|"
    r"i'?m\s+not\s+sure|i\s+am\s+not\s+sure|"
    r"can'?t\s+help|cannot\s+help|"
    r"no\s+idea|"
    r"unable\s+to\s+(?:help|answer|provide)|"
    r"i\s+don't\s+have\s+(?:enough\s+)?(?:information|context|access)|"
    r"as\s+an\s+ai\s+language\s+model"
    r")(?:$|\b)",
    re.IGNORECASE,
)

# Anything shorter than this from the local model is treated as
# evasive (one-word "Yes." / "No." / "OK." replies often signal the
# model gave up rather than answering). Keep low — real short
# answers like "12" to "what's 7+5" should NOT escalate, so 12 chars
# is a reasonable floor that captures "Yes." but lets "12" pass.
# Tuned against a small handful of qwen2.5:7b traces.
_MIN_REPLY_CHARS = 12

# Explicit per-turn opt-in: "cloud: <question>" forces a routed call
# even if the local model would have answered confidently. Useful for
# A/B testing or when the user wants the cloud's stronger reasoning.
_EXPLICIT_CLOUD_PREFIX = re.compile(r"^\s*cloud:\s*", re.IGNORECASE)


def _trips_low_confidence(reply: str) -> bool:
    """True if the local reply looks evasive / unhelpful."""
    if not reply or len(reply.strip()) < _MIN_REPLY_CHARS:
        return True
    if _LOW_CONFIDENCE_MARKERS.search(reply):
        return True
    return False


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

    A cloud client takes a messages list (same shape as LLMBackend.chat)
    and returns the full reply as a string. Synchronous + non-streaming
    by design — streaming the second pass would tangle with the local
    pass and double the perceived latency. For a short fallback reply
    the difference is negligible.
    """

    def complete(self, messages: list[Message]) -> str:                 # pragma: no cover - protocol
        raise NotImplementedError

    @property
    def label(self) -> str:                                             # pragma: no cover - protocol
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
        """Yield reply text. Always runs local first; may swap in
        cloud on low confidence or explicit opt-in.

        Implemented as a one-shot collect-then-decide for the cloud
        path: we can't tell whether the local reply is good until
        it's complete, and streaming both backends in parallel would
        double API spend / cold-start time. The local path still
        streams to the caller when the route stays local.
        """
        explicit_cloud = self._explicit_cloud_opt_in(messages)

        # Fast path — no cloud available or user didn't opt in and
        # we're not routing: stream local straight through.
        if self._cloud is None and not explicit_cloud:
            self.last_route = "local"
            yield from self._local.chat(messages)
            return

        # User explicitly asked for cloud — skip the local round-trip.
        if explicit_cloud and self._cloud is not None:
            try:
                cloud_msgs = _strip_memory_prelude(messages)
                reply = self._cloud.complete(cloud_msgs)
                self.last_route = f"cloud:{self._cloud.label}"
                log.info("routed.cloud_explicit", provider=self._cloud.label, chars=len(reply))
                yield reply
                return
            except Exception as exc:
                log.warning("routed.cloud_failed_explicit", error=str(exc))
                # Fall through to local — user wanted cloud but it
                # failed; serving SOMETHING beats serving nothing.

        # Default routing: collect local first, decide.
        local_reply = "".join(self._local.chat(messages))

        if self._cloud is None or not _trips_low_confidence(local_reply):
            self.last_route = "local"
            log.info("routed.local", chars=len(local_reply))
            yield local_reply
            return

        # Low confidence — escalate.
        try:
            cloud_msgs = _strip_memory_prelude(messages)
            cloud_reply = self._cloud.complete(cloud_msgs)
            if not cloud_reply.strip():
                # Cloud answered with nothing useful — keep local.
                self.last_route = "local"
                log.info("routed.cloud_empty_fallback_local", local_chars=len(local_reply))
                yield local_reply
                return
            self.last_route = f"cloud:{self._cloud.label}"
            log.info(
                "routed.cloud_escalated",
                provider=self._cloud.label,
                local_chars=len(local_reply),
                cloud_chars=len(cloud_reply),
            )
            yield cloud_reply
        except Exception as exc:
            log.warning("routed.cloud_failed", error=str(exc), provider=self._cloud.label)
            self.last_route = "local"
            yield local_reply

    @staticmethod
    def _explicit_cloud_opt_in(messages: list[Message]) -> bool:
        """True if the LATEST user turn carries the "cloud:" prefix."""
        for m in reversed(messages):
            if m.get("role") == "user":
                return bool(_EXPLICIT_CLOUD_PREFIX.match(m.get("content", "")))
        return False
