"""Unit tests for ConversationManager."""

from __future__ import annotations

import pytest

from lumi.config import Mode
from lumi.llm import MockLLMBackend
from lumi.runtime.conversation import ConversationManager


@pytest.fixture
def backend() -> MockLLMBackend:
    return MockLLMBackend(response="I am Lumi.")


@pytest.fixture
def manager(backend: MockLLMBackend) -> ConversationManager:
    return ConversationManager(backend, mode=Mode.GENERAL)


def test_chat_returns_full_reply(manager: ConversationManager) -> None:
    assert manager.chat("Hello") == "I am Lumi."


def test_chat_appends_user_and_assistant_to_history(manager: ConversationManager) -> None:
    manager.chat("Hello")
    assert len(manager._history) == 2
    assert manager._history[0] == {"role": "user", "content": "Hello"}
    assert manager._history[1]["role"] == "assistant"
    assert manager._history[1]["content"] == "I am Lumi."


def test_system_prompt_is_first_message(backend: MockLLMBackend) -> None:
    mgr = ConversationManager(backend, mode=Mode.GENERAL)
    mgr.chat("test")
    sent = backend.received_messages[0]
    assert sent[0]["role"] == "system"
    assert "Lumi" in sent[0]["content"]


def test_focus_mode_system_prompt_differs_from_general(backend: MockLLMBackend) -> None:
    general_mgr = ConversationManager(MockLLMBackend(), mode=Mode.GENERAL)
    focus_mgr = ConversationManager(backend, mode=Mode.FOCUS)
    general_mgr.chat("test")
    focus_mgr.chat("test")
    # focus backend received a different system prompt
    focus_sent = backend.received_messages[0]
    assert "focus" in focus_sent[0]["content"].lower()


def test_set_mode_changes_next_system_prompt(backend: MockLLMBackend) -> None:
    mgr = ConversationManager(backend, mode=Mode.GENERAL)
    mgr.set_mode(Mode.CODE)
    mgr.chat("show me code")
    sent = backend.received_messages[0]
    content = sent[0]["content"].lower()
    assert "developer" in content or "code" in content


def test_clear_resets_history(manager: ConversationManager) -> None:
    manager.chat("Hello")
    manager.clear()
    assert manager._history == []


def test_max_turns_truncates_history() -> None:
    b = MockLLMBackend(response="ok")
    mgr = ConversationManager(b, max_turns=2)
    for i in range(10):
        mgr.chat(f"message {i}")
    last_sent = b.received_messages[-1]
    non_system = [m for m in last_sent if m["role"] != "system"]
    assert len(non_system) <= 4  # 2 turns * 2 messages each


def test_stream_chat_yields_chunks(backend: MockLLMBackend) -> None:
    mgr = ConversationManager(backend, mode=Mode.GENERAL)
    chunks = list(mgr.stream_chat("Hello"))
    assert chunks
    assert "".join(chunks).strip() == "I am Lumi."


def test_stream_chat_appends_to_history(backend: MockLLMBackend) -> None:
    mgr = ConversationManager(backend, mode=Mode.GENERAL)
    list(mgr.stream_chat("Hello"))
    assert mgr._history[-1]["role"] == "assistant"
    assert mgr._history[-1]["content"] == "I am Lumi."


def test_multi_turn_history_sent_to_llm(backend: MockLLMBackend) -> None:
    mgr = ConversationManager(backend)
    mgr.chat("first")
    mgr.chat("second")
    last_sent = backend.received_messages[-1]
    user_msgs = [m for m in last_sent if m["role"] == "user"]
    assert len(user_msgs) == 2


def test_mode_property(manager: ConversationManager) -> None:
    assert manager.mode == Mode.GENERAL
    manager.set_mode(Mode.DICTATION)
    assert manager.mode == Mode.DICTATION
