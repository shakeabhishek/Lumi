"""Unit tests for LLMBackend protocol + MockLLMBackend."""

from __future__ import annotations

from lumi.llm import LLMBackend, MockLLMBackend


def test_mock_yields_chunks_joining_to_response() -> None:
    backend = MockLLMBackend(response="Hello world")
    chunks = list(backend.chat([{"role": "user", "content": "hi"}]))
    assert chunks
    assert "".join(chunks).strip() == "Hello world"


def test_mock_default_response() -> None:
    backend = MockLLMBackend()
    result = "".join(backend.chat([{"role": "user", "content": "hi"}])).strip()
    assert result == "I heard you."


def test_mock_records_received_messages() -> None:
    backend = MockLLMBackend()
    msgs = [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}]
    list(backend.chat(msgs))
    assert len(backend.received_messages) == 1
    assert backend.received_messages[0] == msgs


def test_mock_accumulates_across_calls() -> None:
    backend = MockLLMBackend()
    list(backend.chat([{"role": "user", "content": "first"}]))
    list(backend.chat([{"role": "user", "content": "second"}]))
    assert len(backend.received_messages) == 2


def test_mock_model_property() -> None:
    assert MockLLMBackend().model == "mock"


def test_mock_is_llm_backend_subtype() -> None:
    assert isinstance(MockLLMBackend(), LLMBackend)


def test_mock_custom_response() -> None:
    backend = MockLLMBackend(response="Custom reply here")
    result = "".join(backend.chat([{"role": "user", "content": "?"}])).strip()
    assert result == "Custom reply here"


def test_mock_yields_multiple_chunks_for_multiword_response() -> None:
    backend = MockLLMBackend(response="one two three")
    chunks = list(backend.chat([{"role": "user", "content": "go"}]))
    assert len(chunks) == 3
