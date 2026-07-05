"""Tests for RoutedBackend — cloud-first LLM with a local fallback.

Flipped 2026-07-05 from local-first-with-escalation: the old design ran
local to completion FIRST, only trying cloud if the local reply looked
evasive — meaning an escalated turn paid local generation time PLUS
cloud generation time, the worst-case latency. Cloud-first tries cloud
first for every turn (when configured); local only serves the reply if
cloud is unavailable or empty.

Coverage focus:
  * No cloud client → behaves exactly like the local backend
  * Cloud available and streams → cloud serves the turn, local not called
  * Cloud unavailable/raises before any chunk → clean fallback to local
  * Cloud returns nothing at all → falls back to local
  * Cloud fails PARTWAY through (after some chunks) → stream stops, no
    local splice (would look like two answers stitched together)
  * Memory-retrieval prelude is stripped before cloud send
  * `last_route` accurately reports which path served the turn
"""

from __future__ import annotations

from collections.abc import Iterator

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
        yield from self._reply


class _FakeCloud:
    """Stub CloudLLMClient — records calls and streams a configured
    sequence of chunks. `error_after` raises mid-stream after that many
    chunks (None = never); `fail_immediately` raises before yielding
    anything at all."""

    label = "gemini"

    def __init__(
        self,
        chunks: list[str] | None = None,
        fail_immediately: Exception | None = None,
        error_after: int | None = None,
    ) -> None:
        self._chunks = chunks if chunks is not None else ["from cloud"]
        self._fail_immediately = fail_immediately
        self._error_after = error_after
        self.calls: list[list[Message]] = []

    def complete(self, messages: list[Message]) -> str:
        return "".join(self._chunks)

    def complete_streaming(self, messages: list[Message]) -> Iterator[str]:
        self.calls.append([dict(m) for m in messages])
        if self._fail_immediately:
            raise self._fail_immediately
        for i, chunk in enumerate(self._chunks):
            if self._error_after is not None and i >= self._error_after:
                raise RuntimeError("stream dropped mid-turn")
            yield chunk


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


# ── Cloud-first happy path ──────────────────────────────────────────────


def test_cloud_serves_the_turn_when_available() -> None:
    """Cloud is tried first and wins — local is never even called,
    unlike the old escalation design."""
    local = _FakeLocal("local should not be used")
    cloud = _FakeCloud(chunks=["Detailed ", "cloud ", "answer."])
    routed = RoutedBackend(local=local, cloud=cloud)

    chunks = list(routed.chat(_hello_msgs()))
    assert "".join(chunks) == "Detailed cloud answer."
    assert routed.last_route == "cloud:gemini"
    assert local.calls == [], "local was called despite cloud succeeding"
    assert len(cloud.calls) == 1


def test_cloud_streams_chunk_by_chunk() -> None:
    """Chunks arrive incrementally from the caller's perspective, not
    buffered into one blob — this is the whole point of the flip."""
    local = _FakeLocal("unused")
    cloud = _FakeCloud(chunks=["a", "b", "c"])
    routed = RoutedBackend(local=local, cloud=cloud)

    chunks = list(routed.chat(_hello_msgs()))
    assert chunks == ["a", "b", "c"]


# ── Cloud unavailable before any output → clean fallback ──────────────────


def test_cloud_exception_before_first_chunk_falls_back_to_local() -> None:
    """Cloud raises immediately (network down, bad key) — nothing has
    been shown to the caller yet, so falling back to local is clean."""
    local = _FakeLocal("local saves the day")
    cloud = _FakeCloud(fail_immediately=RuntimeError("network is dead"))
    routed = RoutedBackend(local=local, cloud=cloud)

    chunks = list(routed.chat(_hello_msgs()))
    assert "".join(chunks) == "local saves the day"
    assert routed.last_route == "local"


def test_cloud_empty_stream_falls_back_to_local() -> None:
    """Cloud streams nothing at all (empty candidates, content filter,
    quota exhausted) — falls back to local rather than showing nothing."""
    local = _FakeLocal("local saves the day")
    cloud = _FakeCloud(chunks=[])
    routed = RoutedBackend(local=local, cloud=cloud)

    chunks = list(routed.chat(_hello_msgs()))
    assert "".join(chunks) == "local saves the day"
    assert routed.last_route == "local"


# ── Cloud fails PARTWAY through → stop, don't splice local ────────────────


def test_cloud_failure_mid_stream_stops_without_local_splice() -> None:
    """Once some cloud chunks have already reached the caller, we can't
    un-yield them — appending a full local reply afterward would look
    like two answers stitched together. The stream should just stop."""
    local = _FakeLocal("this must NOT appear in the output")
    cloud = _FakeCloud(chunks=["Partial ", "reply", " before drop"], error_after=2)
    routed = RoutedBackend(local=local, cloud=cloud)

    chunks = list(routed.chat(_hello_msgs()))
    assert "".join(chunks) == "Partial reply"
    assert "must NOT appear" not in "".join(chunks)
    assert routed.last_route == "cloud:gemini"
    assert local.calls == [], "local was spliced in after a partial cloud stream"


# ── Memory prelude scrubbing ───────────────────────────────────────────────


def test_memory_prelude_stripped_from_cloud_call() -> None:
    """ConversationManager injects retrieved memory snippets as a
    user message tagged with the "RELEVANT PAST CONVERSATION
    SNIPPETS" header. That message must NOT reach the cloud — only
    the live turn + system prompt do. (Live untrusted context like
    clipboard hints stays because it's from THIS turn.)"""
    local = _FakeLocal("unused")
    cloud = _FakeCloud(chunks=["from cloud, no memory needed"])
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
