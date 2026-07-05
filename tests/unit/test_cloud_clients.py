"""Tests for GeminiClient — the CloudLLMClient used by RoutedBackend.

`complete_streaming` was added 2026-07-05 alongside RoutedBackend's
cloud-first flip: cloud went from an occasional non-streaming fallback
to the primary path for every turn, so it needed to stream like the
local backend does.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from lumi.llm.cloud_clients import GeminiClient


def _sse_response(events: list[dict]) -> MagicMock:
    """Build a mock httpx.stream() context manager yielding SSE lines
    for the given list of Gemini-shaped response dicts."""
    lines = [f"data: {json.dumps(e)}" for e in events]
    lines.append("data: [DONE]")

    resp = MagicMock()
    resp.iter_lines.return_value = lines
    resp.raise_for_status.return_value = None
    ctx = MagicMock()
    ctx.__enter__.return_value = resp
    ctx.__exit__.return_value = False
    return ctx


def _candidate(text: str) -> dict:
    return {"candidates": [{"content": {"parts": [{"text": text}]}}]}


def test_complete_streaming_yields_text_chunks_in_order() -> None:
    events = [_candidate("Hello"), _candidate(" world"), _candidate("!")]
    with patch("httpx.stream", return_value=_sse_response(events)):
        client = GeminiClient(api_key="fake-key")
        chunks = list(client.complete_streaming([{"role": "user", "content": "hi"}]))
    assert chunks == ["Hello", " world", "!"]


def test_complete_streaming_skips_empty_and_done_lines() -> None:
    resp = MagicMock()
    resp.iter_lines.return_value = ["", "data: [DONE]", "not-an-sse-line"]
    resp.raise_for_status.return_value = None
    ctx = MagicMock()
    ctx.__enter__.return_value = resp
    ctx.__exit__.return_value = False

    with patch("httpx.stream", return_value=ctx):
        client = GeminiClient(api_key="fake-key")
        chunks = list(client.complete_streaming([{"role": "user", "content": "hi"}]))
    assert chunks == []


def test_complete_streaming_skips_unparseable_json() -> None:
    resp = MagicMock()
    resp.iter_lines.return_value = ["data: {broken json", "data: " + '{"candidates": []}']
    resp.raise_for_status.return_value = None
    ctx = MagicMock()
    ctx.__enter__.return_value = resp
    ctx.__exit__.return_value = False

    with patch("httpx.stream", return_value=ctx):
        client = GeminiClient(api_key="fake-key")
        # Must not raise despite the malformed line.
        chunks = list(client.complete_streaming([{"role": "user", "content": "hi"}]))
    assert chunks == []


def test_complete_streaming_skips_empty_candidates() -> None:
    events = [{"candidates": []}, _candidate("real text")]
    with patch("httpx.stream", return_value=_sse_response(events)):
        client = GeminiClient(api_key="fake-key")
        chunks = list(client.complete_streaming([{"role": "user", "content": "hi"}]))
    assert chunks == ["real text"]


def test_complete_and_complete_streaming_share_body_building() -> None:
    """Both methods must send the same system/user/assistant role
    mapping — regression guard against the refactor that split
    complete() into _build_body() + complete()/complete_streaming()."""
    client = GeminiClient(api_key="fake-key")
    messages = [
        {"role": "system", "content": "be terse"},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    body = client._build_body(messages)
    assert body["systemInstruction"]["parts"][0]["text"] == "be terse"
    assert body["contents"] == [
        {"role": "user", "parts": [{"text": "hi"}]},
        {"role": "model", "parts": [{"text": "hello"}]},
    ]
