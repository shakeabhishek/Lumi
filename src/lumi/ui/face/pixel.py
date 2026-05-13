"""Pixel face renderer — 8-bit chunky style.

Renders at 48×32 then scales up 10× so each "pixel" is a 10×10 block.
This gives an unmistakably retro, NES-style look.

States:
  IDLE   — rectangular eyes, flat dotted mouth, slow blink
  LISTEN — wide square eyes, expanding square pulse frame
  THINK  — squint (half-height eyes), scrolling ellipsis dots
  SPEAK  — square eyes, blocky stepped mouth that animates
"""

from __future__ import annotations

import numpy as np

from ...hardware.base import Frame
from ...runtime.state_machine import LumiState

_BG: tuple[int, int, int] = (26, 26, 26)

# Small canvas — each unit becomes a 10×10 block on the final 480×320 surface
_CW = 48
_CH = 32


class PixelFaceRenderer:
    def __init__(
        self,
        width: int,
        height: int,
        fg_color: tuple[int, int, int] = (245, 166, 35),
    ) -> None:
        self._w = width
        self._h = height
        self._fg = fg_color

    def render(self, state: LumiState, tick: int) -> Frame:
        import pygame  # noqa: PLC0415

        canvas = pygame.Surface((_CW, _CH))
        canvas.fill(_BG)
        match state:
            case LumiState.IDLE:
                self._draw_idle(canvas, tick)
            case LumiState.LISTEN:
                self._draw_listen(canvas, tick)
            case LumiState.THINK:
                self._draw_think(canvas, tick)
            case LumiState.SPEAK:
                self._draw_speak(canvas, tick)
        scaled = pygame.transform.scale(canvas, (self._w, self._h))
        pixels = np.transpose(pygame.surfarray.array3d(scaled), (1, 0, 2))
        return Frame(pixels=pixels)

    @staticmethod
    def _eye_pos() -> tuple[tuple[int, int], tuple[int, int]]:
        # (x, y) of top-left corner for each 5×4 eye block
        return (10, 9), (33, 9)

    def _draw_idle(self, canvas: object, tick: int) -> None:
        import pygame  # noqa: PLC0415

        blink = tick % 90
        for ex, ey in self._eye_pos():
            if blink < 4:
                # Blink: single pixel-wide bar
                pygame.draw.rect(canvas, self._fg, (ex, ey + 2, 5, 1))
            else:
                # Normal eye: solid 5×4 block
                pygame.draw.rect(canvas, self._fg, (ex, ey, 5, 4))
        # Dotted flat mouth
        for mx in range(16, 33, 3):
            pygame.draw.rect(canvas, self._fg, (mx, 22, 2, 1))

    def _draw_listen(self, canvas: object, tick: int) -> None:
        import pygame  # noqa: PLC0415

        # Wide-open eyes: 6×5 blocks
        for ex, ey in ((9, 8), (32, 8)):
            pygame.draw.rect(canvas, self._fg, (ex, ey, 7, 5))
        # Expanding square pulse — outline only, grows each 8 ticks
        pulse = (tick // 3) % 10
        r = 6 + pulse * 2
        cx, cy = _CW // 2, _CH // 2
        pygame.draw.rect(canvas, self._fg, (cx - r, cy - r, r * 2, r * 2), 1)

    def _draw_think(self, canvas: object, tick: int) -> None:
        import pygame  # noqa: PLC0415

        # Squint eyes: 5×2 blocks
        for ex, ey in self._eye_pos():
            pygame.draw.rect(canvas, self._fg, (ex, ey + 1, 5, 2))
        # Three scrolling dots
        dot_phase = (tick // 12) % 3
        for i in range(3):
            bright = self._fg if i == dot_phase else tuple(c // 3 for c in self._fg)
            pygame.draw.rect(canvas, bright, (18 + i * 5, 22, 2, 2))

    def _draw_speak(self, canvas: object, tick: int) -> None:
        import pygame  # noqa: PLC0415

        # Open eyes: 5×4 blocks
        for ex, ey in self._eye_pos():
            pygame.draw.rect(canvas, self._fg, (ex, ey, 5, 4))
        # Blocky stepped mouth — phase shifts per tick
        # Zigzag: alternating high/low blocks that scroll
        phase = (tick // 4) % 6
        step_y = [22, 21, 22, 23, 22, 21]
        for i, mx in enumerate(range(14, 35, 3)):
            y = step_y[(i + phase) % len(step_y)]
            pygame.draw.rect(canvas, self._fg, (mx, y, 3, 2))
