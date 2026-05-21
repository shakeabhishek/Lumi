"""Tests for failure mode hardening — mic errors, STT errors, TTS errors, router errors."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from lumi.runtime.conversation import ConversationManager
from lumi.runtime.state_machine import LumiState, StateMachine


# ---------------------------------------------------------------------------
# ConversationManager.set_context_hint
# ---------------------------------------------------------------------------


def test_context_hint_consumed_after_one_turn() -> None:
    backend = MagicMock()
    backend.chat.side_effect = lambda *_a, **_kw: iter(["reply"])
    conv = ConversationManager(backend)
    conv.set_context_hint("active window: VS Code")
    conv.chat("hello")
    # After audit #5: hints live in a user-role message, not the system role.
    # The hint must be present somewhere in the first turn's payload.
    first_messages = backend.chat.call_args_list[0][0][0]
    blob = "\n".join(m["content"] for m in first_messages)
    assert "VS Code" in blob
    # And the system role itself stays clean (no untrusted content).
    assert "VS Code" not in first_messages[0]["content"]

    conv.chat("hello again")
    second_messages = backend.chat.call_args_list[1][0][0]
    blob2 = "\n".join(m["content"] for m in second_messages)
    assert "VS Code" not in blob2


def test_context_hint_empty_by_default() -> None:
    backend = MagicMock()
    backend.chat.return_value = iter(["reply"])
    conv = ConversationManager(backend)
    conv.chat("test")
    messages = backend.chat.call_args_list[0][0][0]
    # Default system prompt should not include "active window"
    assert "active window" not in messages[0]["content"].lower()


# ---------------------------------------------------------------------------
# SkillRouter error handling
# ---------------------------------------------------------------------------


def test_router_returns_error_message_on_llm_failure() -> None:
    from lumi.skills.router import SkillRouter

    conv = MagicMock()
    conv.chat.side_effect = RuntimeError("LLM unavailable")
    tts = MagicMock()
    router = SkillRouter(conversation=conv, tts=tts)
    # Router itself propagates — main.py catches and returns friendly message
    with pytest.raises(RuntimeError, match="LLM unavailable"):
        router.handle("hello")


def test_router_openclaw_miss_falls_through_to_llm() -> None:
    from lumi.skills.router import SkillRouter

    conv = MagicMock()
    conv.chat.return_value = "llm answer"
    bridge = MagicMock()
    bridge.send.return_value = None  # simulate openclaw miss
    tts = MagicMock()
    router = SkillRouter(conversation=conv, tts=tts, bridge=bridge)
    result = router.handle("some unknown query")
    assert result == "llm answer"
    conv.chat.assert_called_once()


def test_router_openclaw_network_failure_falls_through() -> None:
    from lumi.skills.router import SkillRouter

    conv = MagicMock()
    conv.chat.return_value = "fallback"
    bridge = MagicMock()
    bridge.send.return_value = None  # bridge already swallows exceptions
    tts = MagicMock()
    router = SkillRouter(conversation=conv, tts=tts, bridge=bridge)
    result = router.handle("weather today")
    assert result == "fallback"


# ---------------------------------------------------------------------------
# OpenClawBridge timeout / network errors
# ---------------------------------------------------------------------------


def test_openclaw_bridge_timeout_returns_none() -> None:
    import httpx

    from lumi.skills.openclaw_bridge import OpenClawBridge

    bridge = OpenClawBridge("http://localhost:18789", "token", timeout=1.0)
    with patch("lumi.skills.openclaw_bridge.httpx.post",
               side_effect=httpx.TimeoutException("timed out")):
        result = bridge.send("hello")
    assert result is None


def test_openclaw_bridge_connection_error_returns_none() -> None:
    import httpx

    from lumi.skills.openclaw_bridge import OpenClawBridge

    bridge = OpenClawBridge("http://localhost:18789", "token")
    with patch("lumi.skills.openclaw_bridge.httpx.post",
               side_effect=httpx.ConnectError("refused")):
        result = bridge.send("hello")
    assert result is None


# ---------------------------------------------------------------------------
# StateMachine stays consistent through transitions
# ---------------------------------------------------------------------------


def test_state_machine_recovers_to_idle() -> None:
    sm = StateMachine()
    sm.transition(LumiState.LISTEN)
    sm.transition(LumiState.THINK)
    sm.transition(LumiState.IDLE)
    assert sm.state == LumiState.IDLE


def test_state_machine_listener_called_on_error_recovery() -> None:
    sm = StateMachine()
    seen: list[LumiState] = []
    sm.on_state_change(seen.append)
    sm.transition(LumiState.LISTEN)
    sm.transition(LumiState.IDLE)  # simulate recovery
    assert seen == [LumiState.LISTEN, LumiState.IDLE]
