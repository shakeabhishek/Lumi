"""Face engine — owns the render loop and reacts to state transitions."""

from __future__ import annotations

from ...hardware.base import Display
from ...runtime.state_machine import LumiState
from .pixel import PixelFaceRenderer


class FaceEngine:
    def __init__(self, display: Display) -> None:
        w, h = display.size
        self._display = display
        self._renderer = PixelFaceRenderer(w, h)
        self._state = LumiState.IDLE
        self._tick = 0

    def set_state(self, state: LumiState) -> None:
        """Called by StateMachine on each transition. Resets animation tick."""
        self._state = state
        self._tick = 0

    def show(self) -> None:
        """Render current frame and push to display. Must be called from main thread."""
        self._tick += 1
        frame = self._renderer.render(self._state, self._tick)
        self._display.show(frame)
