"""Face engine — owns the render loop and reacts to state transitions."""

from __future__ import annotations

from pathlib import Path

from ...hardware.base import Display
from ...runtime.state_machine import LumiState
from .pixel import PixelFaceRenderer
from .terminal import TerminalFaceRenderer
from .vector import VectorFaceRenderer

_RENDERERS = {
    "pixel": PixelFaceRenderer,
    "vector": VectorFaceRenderer,
    "terminal": TerminalFaceRenderer,
}

_DEFAULT_COLORS = {
    "pixel": "#FF6B9D",     # cute pink
    "vector": "#F5A623",    # warm amber (only for fallback line drawing)
    "terminal": "#33FF33",  # phosphor green
}


def _parse_hex(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


class FaceEngine:
    def __init__(
        self,
        display: Display,
        theme: str = "vector",
        color: str | None = None,
        models_dir: Path | None = None,
    ) -> None:
        w, h = display.size
        self._display = display
        renderer_cls = _RENDERERS.get(theme, VectorFaceRenderer)
        resolved = color if color else _DEFAULT_COLORS.get(theme, "#F5A623")
        fg = _parse_hex(resolved)
        # Only VectorFaceRenderer takes models_dir; others ignore.
        if renderer_cls is VectorFaceRenderer:
            self._renderer = renderer_cls(w, h, fg_color=fg, models_dir=models_dir)
        else:
            self._renderer = renderer_cls(w, h, fg_color=fg)
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
