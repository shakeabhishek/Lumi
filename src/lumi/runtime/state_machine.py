"""Lumi runtime state machine.

States flow: IDLE → LISTEN → THINK → SPEAK → IDLE (repeat).
Listeners registered via on_state_change() are called synchronously on
every transition. The voice loop's only listener is
`runtime.device_display_client.state_callback()`, which fires a
fire-and-forget POST to /api/state so the React device display
animates in sync with the conversation.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum

from ..log import get_logger

log = get_logger(__name__)


class LumiState(Enum):
    IDLE = "idle"
    LISTEN = "listen"
    THINK = "think"
    SPEAK = "speak"


class StateMachine:
    def __init__(self) -> None:
        self._state = LumiState.IDLE
        self._listeners: list[Callable[[LumiState], None]] = []

    @property
    def state(self) -> LumiState:
        return self._state

    def transition(self, new_state: LumiState) -> None:
        log.info("state.transition", from_=self._state.value, to=new_state.value)
        self._state = new_state
        for cb in self._listeners:
            cb(new_state)

    def on_state_change(self, callback: Callable[[LumiState], None]) -> None:
        self._listeners.append(callback)
