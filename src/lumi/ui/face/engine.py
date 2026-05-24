"""Face engine — owns the render loop and reacts to state transitions."""

from __future__ import annotations

from pathlib import Path

from ...hardware.base import Display
from ...runtime.state_machine import LumiState
from .chrome import ScreenCompositor
from .idle_scenes import make_scene
from .pixel import PixelFaceRenderer
from .terminal import TerminalFaceRenderer
from .vector import VectorFaceRenderer

_RENDERERS = {
    "vector":   VectorFaceRenderer,
    "terminal": TerminalFaceRenderer,    # kawaii bear, not the old ASCII art
    "pixel":    PixelFaceRenderer,
}

_DEFAULT_COLORS = {
    "vector":   "#F5A623",    # warm amber (only for fallback line drawing)
    "terminal": "#33FF33",    # phosphor green for the bear body
    "pixel":    "#FF6B9D",    # cute pink
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
        chrome: bool = True,
        weather_location: str = "",
        idle_scene: str = "none",
        data_dir: Path | None = None,
    ) -> None:
        w, h = display.size
        self._display = display
        self._data_dir = data_dir
        renderer_cls = _RENDERERS.get(theme, VectorFaceRenderer)
        resolved = color if color else _DEFAULT_COLORS.get(theme, "#F5A623")
        fg = _parse_hex(resolved)
        if renderer_cls is VectorFaceRenderer:
            self._face = renderer_cls(w, h, fg_color=fg, models_dir=models_dir)
        else:
            self._face = renderer_cls(w, h, fg_color=fg)
        self._compositor: ScreenCompositor | None = (
            ScreenCompositor(
                self._face, w, h,
                location=weather_location,
                idle_scene=make_scene(idle_scene, data_dir=data_dir),
            ) if chrome else None
        )
        self._renderer = self._compositor if self._compositor else self._face
        self._state = LumiState.IDLE
        self._tick = 0

    def set_state(self, state: LumiState) -> None:
        """Called by StateMachine on each transition. Resets animation tick.

        Also updates the bottom status band to reflect the current state.
        """
        self._state = state
        self._tick = 0
        if self._compositor is not None:
            self._compositor.set_status(_STATUS_TEXT.get(state, ""))

    def set_status(self, text: str) -> None:
        """Override the bottom status band (e.g. for 'Downloading openclaw skill…')."""
        if self._compositor is not None:
            self._compositor.set_status(text)

    def set_weather_location(self, location: str) -> None:
        if self._compositor is not None:
            self._compositor.set_location(location)

    def set_idle_scene(self, scene_name: str) -> None:
        if self._compositor is not None:
            self._compositor.set_idle_scene(make_scene(scene_name, data_dir=self._data_dir))

    def show(self) -> None:
        """Render current frame and push to display. Must be called from main thread."""
        self._tick += 1
        frame = self._renderer.render(self._state, self._tick)
        self._display.show(frame)


# Bottom-band text for each state. Empty string = band hidden.
_STATUS_TEXT: dict[LumiState, str] = {
    LumiState.IDLE: "",
    LumiState.LISTEN: "Listening…",
    LumiState.THINK: "Thinking…",
    LumiState.SPEAK: "Speaking",
}
