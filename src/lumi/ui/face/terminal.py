"""Terminal face renderer — CRT phosphor aesthetic with ASCII art face.

Color: classic green phosphor (#33FF33) on black. Scanlines + monospace font.

States:
  IDLE   — box eyes, flat mouth, slow blink
  LISTEN — wide eyes with crosshair pupil, scrolling input bar
  THINK  — squint eyes, animated ellipsis
  SPEAK  — open eyes, wave characters cycling across mouth line
"""

from __future__ import annotations

import numpy as np

from ...hardware.base import Frame
from ...runtime.state_machine import LumiState

_BG: tuple[int, int, int] = (0, 0, 0)

_FONT_SIZE = 26
_LINE_H = 30

# ASCII art rows — 32-char wide, 9 rows. Tuple index = animation frame.
_IDLE: tuple[list[str], ...] = (
    [
        "                                ",
        "                                ",
        "  +-------+    +-------+        ",
        "  |  ( O )|    |  ( O )|        ",
        "  +-------+    +-------+        ",
        "                                ",
        "       +------------+           ",
        "       +------------+           ",
        "                                ",
    ],
    # blink frame
    [
        "                                ",
        "                                ",
        "  +-------+    +-------+        ",
        "  |  (---)|    |  (---)|        ",
        "  +-------+    +-------+        ",
        "                                ",
        "       +------------+           ",
        "       +------------+           ",
        "                                ",
    ],
)

# LISTEN — crosshair pupil, scrolling bar animates via tick
_LISTEN_EYE = ["( + )", "( # )", "( @ )", "( # )"]
_LISTEN_BAR = ["[==========]", "[===========]", "[============]", "[===========]"]

# THINK — squint eyes, cycling ellipsis dots
_THINK_DOTS = ["         .  ", "        .   ", "     .   .  ", "  .  .   .  "]

# SPEAK — wave characters cycling per tick
_WAVE_CHARS = "~-~^~-~^"


class TerminalFaceRenderer:
    def __init__(
        self,
        width: int,
        height: int,
        fg_color: tuple[int, int, int] = (51, 255, 51),
    ) -> None:
        self._w = width
        self._h = height
        self._fg = fg_color
        # Scanline tint: 7% of fg brightness
        self._scan = tuple(max(0, int(c * 0.07)) for c in fg_color)
        self._font: object | None = None

    def _get_font(self) -> object:
        if self._font is None:
            import pygame  # noqa: PLC0415

            try:
                self._font = pygame.font.SysFont("monospace", _FONT_SIZE)
            except Exception:
                self._font = pygame.font.Font(None, _FONT_SIZE)
        return self._font

    def render(self, state: LumiState, tick: int) -> Frame:
        import pygame  # noqa: PLC0415

        surface = pygame.Surface((self._w, self._h))
        surface.fill(_BG)
        self._draw_scanlines(surface)
        match state:
            case LumiState.IDLE:
                self._draw_idle(surface, tick)
            case LumiState.LISTEN:
                self._draw_listen(surface, tick)
            case LumiState.THINK:
                self._draw_think(surface, tick)
            case LumiState.SPEAK:
                self._draw_speak(surface, tick)
        pixels = np.transpose(pygame.surfarray.array3d(surface), (1, 0, 2))
        return Frame(pixels=pixels)

    def _draw_scanlines(self, surface: object) -> None:
        import pygame  # noqa: PLC0415

        for y in range(0, self._h, 2):
            pygame.draw.line(surface, self._scan, (0, y), (self._w, y))

    def _blit_lines(self, surface: object, lines: list[str], color: tuple[int, int, int] | None = None) -> None:
        """Render a list of strings centered vertically and horizontally."""
        import pygame  # noqa: PLC0415

        fg = color if color is not None else self._fg
        font = self._get_font()
        total_h = len(lines) * _LINE_H
        y0 = (self._h - total_h) // 2
        for i, line in enumerate(lines):
            text_surf = font.render(line, False, fg)  # type: ignore[attr-defined]
            x = (self._w - text_surf.get_width()) // 2
            y = y0 + i * _LINE_H
            surface.blit(text_surf, (x, y))  # type: ignore[attr-defined]

    def _draw_idle(self, surface: object, tick: int) -> None:
        frame = 1 if (tick % 90) < 4 else 0
        self._blit_lines(surface, _IDLE[frame])

    def _draw_listen(self, surface: object, tick: int) -> None:
        eye = _LISTEN_EYE[(tick // 8) % len(_LISTEN_EYE)]
        bar = _LISTEN_BAR[(tick // 6) % len(_LISTEN_BAR)]
        lines = [
            "                                ",
            "                                ",
            f"  +-------+    +-------+        ",
            f"  | {eye}  |    | {eye}  |    ",
            f"  +-------+    +-------+        ",
            "                                ",
            f"       {bar}           ",
            "                                ",
            "                                ",
        ]
        self._blit_lines(surface, lines)

    def _draw_think(self, surface: object, tick: int) -> None:
        dots = _THINK_DOTS[(tick // 12) % len(_THINK_DOTS)]
        lines = [
            "                                ",
            "                                ",
            "  +-------+    +-------+        ",
            "  |  (---)|    |  (---)|        ",
            "  +-------+    +-------+        ",
            "                                ",
            f"      {dots}                   ",
            "                                ",
            "                                ",
        ]
        self._blit_lines(surface, lines)

    def _draw_speak(self, surface: object, tick: int) -> None:
        # Shift wave characters by tick to scroll them
        offset = tick % len(_WAVE_CHARS)
        wave = (_WAVE_CHARS * 3)[offset: offset + 10]
        lines = [
            "                                ",
            "                                ",
            "  +-------+    +-------+        ",
            "  |  ( O )|    |  ( O )|        ",
            "  +-------+    +-------+        ",
            "                                ",
            f"       [ {wave} ]              ",
            "                                ",
            "                                ",
        ]
        self._blit_lines(surface, lines)
