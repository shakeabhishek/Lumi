"""Tests for StateMachine — transitions and listener callbacks."""

from __future__ import annotations

import pytest

from lumi.runtime.state_machine import LumiState, StateMachine


class TestInitialState:
    def test_starts_idle(self) -> None:
        sm = StateMachine()
        assert sm.state == LumiState.IDLE


class TestTransitions:
    def test_transition_updates_state(self) -> None:
        sm = StateMachine()
        sm.transition(LumiState.LISTEN)
        assert sm.state == LumiState.LISTEN

    def test_full_cycle(self) -> None:
        sm = StateMachine()
        for state in [LumiState.LISTEN, LumiState.THINK, LumiState.SPEAK, LumiState.IDLE]:
            sm.transition(state)
            assert sm.state == state

    def test_same_state_transition_allowed(self) -> None:
        sm = StateMachine()
        sm.transition(LumiState.IDLE)
        assert sm.state == LumiState.IDLE


class TestListeners:
    def test_listener_called_on_transition(self) -> None:
        sm = StateMachine()
        calls: list[LumiState] = []
        sm.on_state_change(calls.append)
        sm.transition(LumiState.THINK)
        assert calls == [LumiState.THINK]

    def test_multiple_listeners_all_called(self) -> None:
        sm = StateMachine()
        calls_a: list[LumiState] = []
        calls_b: list[LumiState] = []
        sm.on_state_change(calls_a.append)
        sm.on_state_change(calls_b.append)
        sm.transition(LumiState.SPEAK)
        assert calls_a == [LumiState.SPEAK]
        assert calls_b == [LumiState.SPEAK]

    def test_listener_receives_all_transitions(self) -> None:
        sm = StateMachine()
        seen: list[LumiState] = []
        sm.on_state_change(seen.append)
        for state in [LumiState.LISTEN, LumiState.THINK, LumiState.SPEAK, LumiState.IDLE]:
            sm.transition(state)
        assert seen == [LumiState.LISTEN, LumiState.THINK, LumiState.SPEAK, LumiState.IDLE]

    def test_no_listeners_is_fine(self) -> None:
        sm = StateMachine()
        sm.transition(LumiState.LISTEN)  # should not raise
        assert sm.state == LumiState.LISTEN
