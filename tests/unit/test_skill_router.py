"""Tests for SkillRouter dispatch logic."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from lumi.config import Mode
from lumi.llm.ollama_backend import MockLLMBackend
from lumi.runtime.conversation import ConversationManager
from lumi.skills.base import NativeSkill, SkillResult
from lumi.skills.router import SkillRouter


class _MatchingSkill(NativeSkill):
    """Always matches; returns a fixed response."""

    def __init__(self, response: str = "native response") -> None:
        self._response = response

    def matches(self, transcript: str) -> bool:
        return True

    def execute(self, transcript: str) -> SkillResult:
        return SkillResult(text=self._response)


class _NonMatchingSkill(NativeSkill):
    """Never matches."""

    def matches(self, transcript: str) -> bool:
        return False

    def execute(self, transcript: str) -> SkillResult:
        return SkillResult(text="should not be called")


def _make_router(
    bridge_response: str | None = None,
    include_bridge: bool = True,
    native_skills: list[NativeSkill] | None = None,
) -> tuple[SkillRouter, MockLLMBackend]:
    llm = MockLLMBackend(response="llm response")
    conversation = ConversationManager(llm)
    tts = MagicMock()

    bridge = None
    if include_bridge:
        bridge = MagicMock()
        bridge.send.return_value = bridge_response

    router = SkillRouter(conversation=conversation, tts=tts, bridge=bridge)

    if native_skills is not None:
        router._native = native_skills  # type: ignore[assignment]

    return router, llm


class TestNativeSkillRouting:
    def test_matching_native_skill_wins(self) -> None:
        router, llm = _make_router(bridge_response="openclaw response")
        router._native = [_MatchingSkill("native response")]  # type: ignore[assignment]

        result = router.handle("anything")

        assert result == "native response"
        assert len(llm.received_messages) == 0

    def test_non_matching_native_falls_through(self) -> None:
        router, _ = _make_router(bridge_response="openclaw response")
        router._native = [_NonMatchingSkill()]  # type: ignore[assignment]

        result = router.handle("anything")

        assert result == "openclaw response"

    def test_first_matching_skill_wins(self) -> None:
        router, _ = _make_router(bridge_response="openclaw response")
        router._native = [  # type: ignore[assignment]
            _NonMatchingSkill(),
            _MatchingSkill("first match"),
            _MatchingSkill("second match"),
        ]

        result = router.handle("anything")

        assert result == "first match"


class TestOpenClawRouting:
    def test_openclaw_called_when_no_native_match(self) -> None:
        router, llm = _make_router(bridge_response="weather response")
        router._native = []  # type: ignore[assignment]

        result = router.handle("what's the weather?")

        assert result == "weather response"
        assert len(llm.received_messages) == 0

    def test_openclaw_none_falls_back_to_llm(self) -> None:
        router, llm = _make_router(bridge_response=None)
        router._native = []  # type: ignore[assignment]

        result = router.handle("tell me a joke")

        assert result == "llm response"
        assert len(llm.received_messages) == 1

    def test_no_bridge_goes_straight_to_llm(self) -> None:
        router, llm = _make_router(include_bridge=False)
        router._native = []  # type: ignore[assignment]

        result = router.handle("tell me a joke")

        assert result == "llm response"
        assert len(llm.received_messages) == 1


class TestLLMFallback:
    def test_llm_receives_transcript(self) -> None:
        router, llm = _make_router(include_bridge=False)
        router._native = []  # type: ignore[assignment]

        router.handle("what is the meaning of life?")

        assert len(llm.received_messages) == 1
        assert llm.received_messages[0][-1]["content"] == "what is the meaning of life?"
