"""End-to-end tests for the HailoBackend HTTP path.

The unit-level normalize/sanitize helpers are also exercised in
test_pomodoro_notes.py. This file covers:

  * Each of the seven Hailo wire-protocol rules our normalize/encode
    layer enforces (deep-sanitize, ASCII-encoded JSON, empty-message
    filter, system-first-only, conversation-starts-with-user, history
    cap, content cap).
  * The full chat() round-trip against a mocked httpx.stream.
  * Factory wiring + config defaults.

The rule set is distilled from tishyk/hailo-ollama-openclaw-adapter
(MIT, 2026.04.20). Phase 5 runs all of this for real against the Pi 5
+ AI HAT+ 2; until then, mocked httpx is the contract.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import httpx

from lumi.config import LLMBackendName, Settings
from lumi.llm import make_llm_backend
from lumi.llm.hailo_backend import (
    HailoBackend,
    _deep_sanitize,
    _encode_for_hailo,
    _normalize_messages,
    _sanitize_content,
)


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
    return json.dumps({"message": {"role": "assistant", "content": content}, "done": done})


# ── Defaults + factory wiring ──────────────────────────────────────────────


def test_default_host_points_at_native_hailo_not_external_adapter() -> None:
    """The protocol bridge is in-process now; no external adapter on :11435."""
    b = HailoBackend()
    assert ":8000" in b._host
    assert ":11435" not in b._host


def test_default_model_is_what_we_targeted_for_pi5() -> None:
    b = HailoBackend()
    assert b._model_name == "qwen3:1.7b"


def test_model_property_namespaces_with_hailo_prefix() -> None:
    b = HailoBackend(model_name="qwen3:1.7b")
    assert b.model == "hailo:qwen3:1.7b"


def test_factory_dispatches_hailo_settings() -> None:
    cfg = Settings(
        llm_backend=LLMBackendName.HAILO,
        hailo_host="http://other-host:9999",
        hailo_model="qwen3:8b",
    )
    backend = make_llm_backend(cfg)
    assert isinstance(backend, HailoBackend)
    assert backend._host == "http://other-host:9999"
    assert backend._model_name == "qwen3:8b"


def test_factory_uses_default_host_when_unset() -> None:
    cfg = Settings(llm_backend=LLMBackendName.HAILO)
    backend = make_llm_backend(cfg)
    assert ":8000" in backend._host


# ── Rule 1: deep control-char sanitisation across the whole JSON tree ─────


def test_deep_sanitize_strips_control_chars_in_nested_values() -> None:
    """Hailo 5.3.0 rejects control chars in ANY string, not just content.
    A NUL in the model name or a stray \\x1b in a metadata blob is enough
    to 400 the request."""
    payload = {
        "model": "qwen3\x001.7b",
        "meta": {"trace_id": "abc\x1bxyz"},
        "messages": [
            {"role": "user", "content": "hi\x07there"},
            {"role": "user", "content": ["nested", "list\x00item"]},
        ],
    }
    cleaned = _deep_sanitize(payload)
    blob = json.dumps(cleaned)
    assert "\x00" not in blob
    assert "\x07" not in blob
    assert "\x1b" not in blob
    # And the structure is preserved
    assert cleaned["model"] == "qwen31.7b"
    assert cleaned["meta"]["trace_id"] == "abcxyz"


# ── Rule 2: strict-ASCII JSON encoding ─────────────────────────────────────


def test_encode_for_hailo_escapes_non_ascii_to_unicode_sequences() -> None:
    """Emoji and accented chars must survive on the wire as \\uXXXX
    escapes, not raw UTF-8 bytes — Hailo's parser is stricter with
    multi-byte sequences."""
    payload = {"messages": [{"role": "user", "content": "café 🍵"}]}
    body = _encode_for_hailo(payload)
    # Result must be pure ASCII bytes (every byte < 128).
    assert all(b < 128 for b in body), f"non-ASCII byte in: {body!r}"
    # The original text round-trips through json.loads.
    parsed = json.loads(body)
    assert parsed["messages"][0]["content"] == "café 🍵"


# ── Rule 3: drop empty / whitespace-only messages ──────────────────────────


def test_normalize_drops_empty_or_whitespace_only_messages() -> None:
    """An empty turn in history can confuse Hailo's prompt renderer.
    Drop them before they reach the wire."""
    out = _normalize_messages([
        {"role": "system", "content": "You are Lumi."},
        {"role": "user", "content": "first turn"},
        {"role": "assistant", "content": "   "},        # whitespace only
        {"role": "user", "content": ""},                # empty
        {"role": "assistant", "content": "ok"},
        {"role": "user", "content": "second turn"},
    ])
    contents = [m["content"] for m in out]
    assert "" not in contents
    assert not any(c.isspace() for c in contents)
    # Real turns survive.
    assert any("first turn" in c for c in contents)
    assert any("ok" in c for c in contents)


# ── Rule 4: only the FIRST system message survives (already covered, here
# for documentation completeness) ─────────────────────────────────────────


def test_normalize_keeps_only_first_system_message() -> None:
    out = _normalize_messages([
        {"role": "system", "content": "You are Lumi."},
        {"role": "user", "content": "hi"},
        {"role": "system", "content": "switched mode"},        # dropped
        {"role": "user", "content": "again"},
    ])
    assert sum(1 for m in out if m["role"] == "system") == 1


# ── Rule 5: conversation must start on a user turn (after the optional
# leading system message) ──────────────────────────────────────────────────


def test_normalize_trims_leading_assistant_turn() -> None:
    """If by accident the first non-system message is `assistant`, drop it.
    Hailo treats that as a malformed conversation start."""
    out = _normalize_messages([
        {"role": "system", "content": "You are Lumi."},
        {"role": "assistant", "content": "stray reply"},        # leading assistant
        {"role": "user", "content": "hello"},
    ])
    non_system = [m for m in out if m["role"] != "system"]
    assert non_system[0]["role"] == "user"
    assert "stray reply" not in (m["content"] for m in non_system)


def test_normalize_no_orphan_when_only_assistant_then_user() -> None:
    """No system, leading assistant — still trims the assistant."""
    out = _normalize_messages([
        {"role": "assistant", "content": "stray"},
        {"role": "user", "content": "hi"},
    ])
    assert out == [{"role": "user", "content": "hi"}]


# ── Rule 6/7: history + content caps (also asserted elsewhere) ────────────


def test_normalize_trims_long_history_to_window() -> None:
    msgs = [{"role": "system", "content": "sys"}]
    for i in range(20):
        msgs.append({"role": "user", "content": f"u{i}"})
        msgs.append({"role": "assistant", "content": f"a{i}"})
    out = _normalize_messages(msgs)
    # 1 system + 12 messages (6 turns)
    assert len(out) == 13


# ── chat() streaming round-trip ────────────────────────────────────────────


def test_chat_yields_each_chunk_in_order() -> None:
    lines = [
        _ollama_line("Hel"),
        _ollama_line("lo"),
        _ollama_line(" there.", done=True),
    ]
    b = HailoBackend()
    with patch("httpx.stream", return_value=_stream_response(lines)) as mock_stream:
        chunks = list(b.chat([{"role": "user", "content": "hi"}]))

    assert chunks == ["Hel", "lo", " there."]
    args, kwargs = mock_stream.call_args
    assert args[0] == "POST"
    assert args[1].endswith("/api/chat")
    assert ":8000" in args[1]
    # We send pre-encoded bytes (so we control the ensure_ascii flag),
    # not Python objects.
    assert "content" in kwargs
    assert isinstance(kwargs["content"], bytes)
    assert kwargs["headers"]["Content-Type"] == "application/json"


def test_chat_request_carries_normalized_payload_on_the_wire() -> None:
    """End-to-end: the actual bytes sent to Hailo have system-first,
    no newlines, no empty turns, deep-sanitised, ASCII-only."""
    msgs = [
        {"role": "system", "content": "You are Lumi."},
        {"role": "user", "content": "hello\nworld\x07"},
        {"role": "assistant", "content": "   "},                # empty
        {"role": "system", "content": "mid-stream"},            # dropped
        {"role": "user", "content": "café 🍵"},
    ]
    b = HailoBackend()
    with patch("httpx.stream", return_value=_stream_response([_ollama_line("ok", done=True)])) as mock_stream:
        list(b.chat(msgs))

    body: bytes = mock_stream.call_args.kwargs["content"]
    # ASCII-only on the wire
    assert all(b_ < 128 for b_ in body)
    # The empty assistant turn is gone
    assert b"   " not in body
    # The control char is gone
    assert b"\x07" not in body
    # Mid-stream system is gone (just one system block)
    parsed = json.loads(body)
    assert sum(1 for m in parsed["messages"] if m["role"] == "system") == 1
    # Emoji round-tripped via \uXXXX escapes
    user_contents = [m["content"] for m in parsed["messages"] if m["role"] == "user"]
    assert any("café" in c and "🍵" in c for c in user_contents)


def test_chat_skips_empty_or_unparseable_lines() -> None:
    lines = [
        "",
        "{not valid json",
        _ollama_line("ok"),
        _ollama_line("", done=True),
    ]
    b = HailoBackend()
    with patch("httpx.stream", return_value=_stream_response(lines)):
        chunks = list(b.chat([{"role": "user", "content": "x"}]))
    assert chunks == ["ok"]


def test_chat_http_error_returns_silently_no_chunks() -> None:
    """If Hailo isn't running, chat() yields nothing — the upstream
    "Sorry, I didn't get a response" fallback triggers."""
    b = HailoBackend()
    with patch("httpx.stream", side_effect=httpx.ConnectError("hailo down")):
        chunks = list(b.chat([{"role": "user", "content": "anything"}]))
    assert chunks == []


def test_chat_carries_the_configured_model_name() -> None:
    b = HailoBackend(model_name="qwen3:8b")
    with patch("httpx.stream", return_value=_stream_response([_ollama_line("x", done=True)])) as mock_stream:
        list(b.chat([{"role": "user", "content": "hi"}]))
    body = mock_stream.call_args.kwargs["content"]
    parsed = json.loads(body)
    assert parsed["model"] == "qwen3:8b"


# ── _sanitize_content edge cases (the legacy helper, still used) ───────────


def test_sanitize_content_collapses_runs_of_whitespace() -> None:
    out = _sanitize_content("hello\n\n\nworld\t\t!")
    assert "\n" not in out and "\t" not in out
    assert "  " not in out                              # no double-space
    assert "hello world !" == out


def test_sanitize_content_truncates_at_cap() -> None:
    from lumi.llm.hailo_backend import _MAX_USER_CONTENT_CHARS  # noqa: PLC0415
    out = _sanitize_content("x" * (_MAX_USER_CONTENT_CHARS + 500))
    assert "truncated" in out
    assert len(out) <= _MAX_USER_CONTENT_CHARS + 50
