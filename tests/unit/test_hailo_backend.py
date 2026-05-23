"""End-to-end tests for the HailoBackend HTTP path.

The unit-level normalize/sanitize helpers are exercised in
test_pomodoro_notes.py. This file covers the full chat() round-trip
against a mocked httpx.stream — what Phase 5 will run for real once
the Pi 5 + AI HAT+ 2 are on the desk and the
tishyk/hailo-ollama-openclaw-adapter (pinned to 2026.04.20) is up
on :11435.

Wire contract we're verifying:
  * POST {host}/api/chat with model + messages + stream:true
  * Response is line-delimited JSON, each line carries a
    `message.content` chunk and a `done` flag on the last line
  * Adapter has already normalised Hailo's protocol quirks, but our
    client-side normalize_messages applies belt-and-braces (defence in
    depth if the adapter ever drifts).
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import httpx

from lumi.config import LLMBackendName, Settings
from lumi.llm import make_llm_backend
from lumi.llm.hailo_backend import HailoBackend


def _stream_response(lines: list[str]) -> MagicMock:
    """Mock an httpx.stream context manager that yields the given lines."""
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.iter_lines.return_value = iter(lines)
    cm = MagicMock()
    cm.__enter__.return_value = resp
    cm.__exit__.return_value = False
    return cm


def _ollama_line(content: str, done: bool = False) -> str:
    """Format a single JSON line the way Hailo-Ollama (and the adapter) emit."""
    return json.dumps({"message": {"role": "assistant", "content": content}, "done": done})


# ── Defaults + factory wiring ──────────────────────────────────────────────


def test_default_host_points_at_the_adapter_not_native_hailo() -> None:
    """CLAUDE.md Phase 5 contract: Lumi talks to the adapter on :11435,
    not Hailo's native /api/chat on :8000. Wrong default would silently
    bypass the adapter's protocol normalisation on hardware."""
    b = HailoBackend()
    assert ":11435" in b._host
    assert ":8000" not in b._host


def test_default_model_is_what_we_targeted_for_pi5() -> None:
    """Phase 5 deployment loads qwen3:1.7b into Hailo per CLAUDE.md."""
    b = HailoBackend()
    assert b._model_name == "qwen3:1.7b"


def test_model_property_namespaces_with_hailo_prefix() -> None:
    """audit/log entries need to distinguish hailo from ollama in the
    metadata — the hailo: prefix is how downstream code tells them apart."""
    b = HailoBackend(model_name="qwen3:1.7b")
    assert b.model == "hailo:qwen3:1.7b"


def test_factory_dispatches_hailo_settings(monkeypatch) -> None:
    """make_llm_backend must read cfg.hailo_host + cfg.hailo_model so
    LUMI_HAILO_HOST / LUMI_HAILO_MODEL env vars take effect on the Pi."""
    cfg = Settings(
        llm_backend=LLMBackendName.HAILO,
        hailo_host="http://other-host:9999",
        hailo_model="qwen3:8b",
    )
    backend = make_llm_backend(cfg)
    assert isinstance(backend, HailoBackend)
    assert backend._host == "http://other-host:9999"
    assert backend._model_name == "qwen3:8b"


def test_factory_uses_default_hailo_host_when_unset() -> None:
    cfg = Settings(llm_backend=LLMBackendName.HAILO)
    backend = make_llm_backend(cfg)
    assert ":11435" in backend._host


# ── chat() streaming round-trip ────────────────────────────────────────────


def test_chat_yields_each_chunk_in_order() -> None:
    """Happy path — three streamed chunks come through in submission order."""
    lines = [
        _ollama_line("Hel"),
        _ollama_line("lo"),
        _ollama_line(" there.", done=True),
    ]
    b = HailoBackend()
    with patch("httpx.stream", return_value=_stream_response(lines)) as mock_stream:
        chunks = list(b.chat([{"role": "user", "content": "hi"}]))

    assert chunks == ["Hel", "lo", " there."]
    # The streamed request went to /api/chat at the configured host.
    args, kwargs = mock_stream.call_args
    assert args[0] == "POST"
    assert args[1].endswith("/api/chat")
    assert ":11435" in args[1]
    # And `stream` was requested so the adapter knows to flush per-chunk.
    assert kwargs["json"]["stream"] is True


def test_chat_skips_empty_or_unparseable_lines() -> None:
    """Hailo-Ollama can emit blank keepalive lines; the adapter passes
    them through. Anything that isn't valid JSON or has no content
    should be skipped, not break the iterator."""
    lines = [
        "",                                  # blank keepalive
        "{not valid json",                   # corrupt line
        _ollama_line("ok"),
        _ollama_line("", done=True),         # empty final line — still skipped
    ]
    b = HailoBackend()
    with patch("httpx.stream", return_value=_stream_response(lines)):
        chunks = list(b.chat([{"role": "user", "content": "x"}]))

    assert chunks == ["ok"]


def test_chat_http_error_returns_silently_no_chunks() -> None:
    """If the adapter isn't running (Pi5 dev outside Phase 5, network
    flapping, etc.), chat() must not raise — it yields no chunks and
    the upstream "Sorry, I didn't get a response" fallback triggers."""
    b = HailoBackend()
    with patch("httpx.stream", side_effect=httpx.ConnectError("adapter down")):
        chunks = list(b.chat([{"role": "user", "content": "anything"}]))

    assert chunks == []


def test_chat_request_carries_normalized_messages() -> None:
    """The local _normalize_messages still runs — even though the adapter
    normalises Hailo quirks, our defence in depth means mid-stream
    system messages are dropped and history is trimmed BEFORE the wire."""
    msgs = [
        {"role": "system", "content": "You are Lumi."},
        {"role": "user", "content": "hello\nworld"},
        {"role": "assistant", "content": "ok"},
        {"role": "system", "content": "switched mode"},        # mid-stream
        {"role": "user", "content": "again"},
    ]
    b = HailoBackend()
    with patch("httpx.stream", return_value=_stream_response([_ollama_line("hi", done=True)])) as mock_stream:
        list(b.chat(msgs))

    sent = mock_stream.call_args.kwargs["json"]["messages"]
    # Mid-stream system message dropped — only the leading one survives.
    system_count = sum(1 for m in sent if m["role"] == "system")
    assert system_count == 1
    # Newlines collapsed in user content (Hailo can't take multiline).
    user_msgs = [m for m in sent if m["role"] == "user"]
    assert "\n" not in user_msgs[0]["content"]


def test_chat_carries_the_configured_model_name() -> None:
    """A different LUMI_HAILO_MODEL must reach the wire (so we can swap
    models without code changes once Hailo has more compiled .hef
    files available)."""
    b = HailoBackend(model_name="qwen3:8b")
    with patch("httpx.stream", return_value=_stream_response([_ollama_line("x", done=True)])) as mock_stream:
        list(b.chat([{"role": "user", "content": "hi"}]))

    assert mock_stream.call_args.kwargs["json"]["model"] == "qwen3:8b"
