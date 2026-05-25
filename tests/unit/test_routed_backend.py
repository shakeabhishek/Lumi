"""Tests for RoutedBackend — local-first LLM with cloud escalation.

Coverage focus:
  * No cloud client → behaves exactly like the local backend
  * Local reply trips low-confidence → cloud is called
  * Local reply is fine → cloud is NOT called (we don't waste API spend)
  * Memory-retrieval prelude is stripped before cloud send
  * Explicit "cloud: ..." prefix forces cloud regardless of local quality
  * Cloud failure falls back to the local reply (never serve nothing)
  * `last_route` accurately reports which path served the turn
"""

from __future__ import annotations

from typing import Iterator

import pytest

from lumi.llm.ollama_backend import LLMBackend, Message
from lumi.llm.routed_backend import RoutedBackend


class _FakeLocal(LLMBackend):
    """A stub LLMBackend that yields a configurable reply char-by-char
    (so the streaming/collect path is exercised) and records every
    messages list it was handed."""

    def __init__(self, reply: str) -> None:
        self._reply = reply
        self.calls: list[list[Message]] = []

    @property
    def model(self) -> str:
        return "fake-local"

    def chat(self, messages: list[Message]) -> Iterator[str]:
        self.calls.append([dict(m) for m in messages])
        for ch in self._reply:
            yield ch


class _FakeCloud:
    """Stub CloudLLMClient — records calls and returns a configured reply
    (or raises if `error` is set)."""

    label = "gemini"

    def __init__(self, reply: str = "from cloud", error: Exception | None = None) -> None:
        self._reply = reply
        self._error = error
        self.calls: list[list[Message]] = []

    def complete(self, messages: list[Message]) -> str:
        if self._error:
            raise self._error
        self.calls.append([dict(m) for m in messages])
        return self._reply


def _hello_msgs(user_text: str = "hi") -> list[Message]:
    return [
        {"role": "system", "content": "you are lumi"},
        {"role": "user", "content": user_text},
    ]


# ── No cloud client → identity wrapper ─────────────────────────────────────


def test_no_cloud_passes_through_local() -> None:
    """If RoutedBackend has no cloud, it just streams local — no
    behaviour change vs the unwrapped backend."""
    local = _FakeLocal("This is a perfectly fine response.")
    routed = RoutedBackend(local=local, cloud=None)

    chunks = list(routed.chat(_hello_msgs()))
    assert "".join(chunks) == "This is a perfectly fine response."
    assert routed.last_route == "local"


# ── Low-confidence escalation ──────────────────────────────────────────────


@pytest.mark.parametrize("local_reply", [
    "I don't know.",
    "I'm not sure.",
    "I cannot help with that.",
    "Yes.",                          # too short → low confidence
    "As an AI language model, I cannot…",
])
def test_low_confidence_escalates_to_cloud(local_reply: str) -> None:
    local = _FakeLocal(local_reply)
    cloud = _FakeCloud("Detailed cloud answer.")
    routed = RoutedBackend(local=local, cloud=cloud)

    chunks = list(routed.chat(_hello_msgs()))
    assert "".join(chunks) == "Detailed cloud answer."
    assert routed.last_route == "cloud:gemini"
    assert len(cloud.calls) == 1


def test_confident_local_does_not_call_cloud() -> None:
    """If the local model gave a good answer, we don't burn cloud
    API spend re-asking. Important — defaults to local."""
    local = _FakeLocal("Paris is the capital of France. It has been the seat of government since the Middle Ages.")
    cloud = _FakeCloud("you should never see this")
    routed = RoutedBackend(local=local, cloud=cloud)

    chunks = list(routed.chat(_hello_msgs("what's the capital of france")))
    assert "Paris" in "".join(chunks)
    assert cloud.calls == [], "cloud was called despite a confident local reply"
    assert routed.last_route == "local"


# ── Memory prelude scrubbing ───────────────────────────────────────────────


def test_memory_prelude_stripped_from_cloud_call() -> None:
    """ConversationManager injects retrieved memory snippets as a
    user message tagged with the "RELEVANT PAST CONVERSATION
    SNIPPETS" header. That message must NOT reach the cloud — only
    the live turn + system prompt do. (Live untrusted context like
    clipboard hints stays because it's from THIS turn.)"""
    local = _FakeLocal("I don't know.")
    cloud = _FakeCloud("from cloud, no memory needed")
    routed = RoutedBackend(local=local, cloud=cloud)

    msgs: list[Message] = [
        {"role": "system", "content": "you are lumi"},
        {"role": "user", "content":
            "RELEVANT PAST CONVERSATION SNIPPETS\n\nUser took oat milk yesterday."},
        {"role": "user", "content":
            "USER-PROVIDED CONTEXT (from clipboard, active window, or hotkey)\n\nFoo"},
        {"role": "user", "content": "what did I take yesterday?"},
    ]
    list(routed.chat(msgs))

    assert len(cloud.calls) == 1
    cloud_received = cloud.calls[0]
    # Memory prelude is gone, but the other messages survived.
    contents = [m["content"] for m in cloud_received]
    assert not any("RELEVANT PAST CONVERSATION SNIPPETS" in c for c in contents), \
        "memory prelude leaked to cloud"
    assert any("USER-PROVIDED CONTEXT" in c for c in contents), \
        "live context hint was wrongly stripped"
    assert any("what did I take yesterday" in c for c in contents)


# ── Explicit opt-in ────────────────────────────────────────────────────────


def test_cloud_prefix_forces_cloud_even_on_confident_local() -> None:
    """The user can override the heuristic by typing "cloud: ..." —
    skips the local round-trip entirely and goes straight to cloud."""
    local = _FakeLocal("local has plenty to say here, no need to escalate.")
    cloud = _FakeCloud("from cloud per explicit request")
    routed = RoutedBackend(local=local, cloud=cloud)

    chunks = list(routed.chat(_hello_msgs("cloud: who painted the night watch")))
    assert "".join(chunks) == "from cloud per explicit request"
    assert routed.last_route == "cloud:gemini"
    # Local was NOT called — explicit-cloud is a fast path.
    assert local.calls == [], "local was called despite explicit cloud opt-in"


# ── Cloud failure → fall back ──────────────────────────────────────────────


def test_cloud_failure_falls_back_to_local_reply() -> None:
    """If cloud throws, RoutedBackend serves the local reply rather
    than nothing. The user is never stranded with zero output just
    because the network blipped."""
    local = _FakeLocal("I don't know.")
    cloud = _FakeCloud(error=RuntimeError("network is dead"))
    routed = RoutedBackend(local=local, cloud=cloud)

    chunks = list(routed.chat(_hello_msgs()))
    assert "".join(chunks) == "I don't know."
    assert routed.last_route == "local"


def test_cloud_returns_empty_falls_back_to_local() -> None:
    """If cloud returns a blank string (rare but possible — API
    quota exhausted, content filter, etc.) we keep local rather
    than show the user nothing."""
    local = _FakeLocal("I don't know.")
    cloud = _FakeCloud(reply="")
    routed = RoutedBackend(local=local, cloud=cloud)

    chunks = list(routed.chat(_hello_msgs()))
    assert "".join(chunks) == "I don't know."
    assert routed.last_route == "local"
