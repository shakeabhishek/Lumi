"""Pixel face renderer — chunky 8-bit style with cute heart eyes.

Renders on a 48×32 canvas then scales up 10×. Each canvas pixel becomes a
10×10 block on the final 480×320 surface. Default color is pink (#FF6B9D).

States:
  IDLE   — heart eyes + rosy cheeks + smile, slow blink
  LISTEN — heart eyes, expanding square pulse ring
  THINK  — squint lines + scrolling ellipsis dots
  SPEAK  — heart eyes + animated blocky mouth
"""

from __future__ import annotations

import numpy as np

from ...hardware.base import Frame
from ...runtime.state_machine import LumiState

_BG: tuple[int, int, int] = (26, 26, 26)
_BLUSH: tuple[int, int, int] = (200, 100, 130)  # soft rosy cheek — independent of fg

# 7 cols × 6 rows heart, relative to top-left origin
_HEART: list[tuple[int, int]] = [
    (1, 0), (2, 0), (4, 0), (5, 0),
    (0, 1), (1, 1), (2, 1), (3, 1), (4, 1), (5, 1), (6, 1),
    (0, 2), (1, 2), (2, 2), (3, 2), (4, 2), (5, 2), (6, 2),
    (1, 3), (2, 3), (3, 3), (4, 3), (5, 3),
    (2, 4), (3, 4), (4, 4),
    (3, 5),
]

# Small canvas dimensions — scaled up 10× to fill 480×320
_CW, _CH = 48, 32

# Eye center positions on the small canvas
_LEFT_EYE = (12, 11)
_RIGHT_EYE = (36, 11)


def _draw_heart(canvas: object, color: tuple[int, int, int], cx: int, cy: int) -> None:
    import pygame  # noqa: PLC0415

    for dx, dy in _HEART:
        pygame.draw.rect(canvas, color, (cx - 3 + dx, cy - 3 + dy, 1, 1))


class PixelFaceRenderer:
    def __init__(
        self,
        width: int,
        height: int,
        fg_color: tuple[int, int, int] = (255, 107, 157),  # default: cute pink
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

    def _draw_blush(self, canvas: object) -> None:
        import pygame  # noqa: PLC0415

        pygame.draw.rect(canvas, _BLUSH, (7, 16, 4, 2))
        pygame.draw.rect(canvas, _BLUSH, (37, 16, 4, 2))

    def _draw_idle(self, canvas: object, tick: int) -> None:
        import pygame  # noqa: PLC0415

        blink = tick % 90
        if blink < 4:
            # Blink: flat bars where hearts were
            for ex, ey in (_LEFT_EYE, _RIGHT_EYE):
                pygame.draw.rect(canvas, self._fg, (ex - 3, ey + 1, 7, 1))
        else:
            _draw_heart(canvas, self._fg, *_LEFT_EYE)
            _draw_heart(canvas, self._fg, *_RIGHT_EYE)
        self._draw_blush(canvas)
        # Cute smile: "U" shape made from dots
        for mx in range(17, 32, 3):
            pygame.draw.rect(canvas, self._fg, (mx, 23, 2, 1))
        # Smile corners curve up
        pygame.draw.rect(canvas, self._fg, (15, 22, 2, 1))
        pygame.draw.rect(canvas, self._fg, (31, 22, 2, 1))

    def _draw_listen(self, canvas: object, tick: int) -> None:
        import pygame  # noqa: PLC0415

        _draw_heart(canvas, self._fg, *_LEFT_EYE)
        _draw_heart(canvas, self._fg, *_RIGHT_EYE)
        self._draw_blush(canvas)
        # Expanding square pulse ring
        pulse = (tick // 3) % 10
        r = 6 + pulse * 2
        cx, cy = _CW // 2, _CH // 2
        pygame.draw.rect(canvas, self._fg, (cx - r, cy - r, r * 2, r * 2), 1)

    def _draw_think(self, canvas: object, tick: int) -> None:
        import pygame  # noqa: PLC0415

        # Squint eyes — flat horizontal lines, no hearts
        for ex, ey in (_LEFT_EYE, _RIGHT_EYE):
            pygame.draw.rect(canvas, self._fg, (ex - 3, ey + 1, 7, 2))
        # Three scrolling dots
        dot_phase = (tick // 12) % 3
        for i in range(3):
            color = self._fg if i == dot_phase else tuple(c // 3 for c in self._fg)
            pygame.draw.rect(canvas, color, (18 + i * 5, 22, 2, 2))

    def _draw_speak(self, canvas: object, tick: int) -> None:
        import pygame  # noqa: PLC0415

        _draw_heart(canvas, self._fg, *_LEFT_EYE)
        _draw_heart(canvas, self._fg, *_RIGHT_EYE)
        self._draw_blush(canvas)
        # Animated blocky mouth — zigzag that scrolls
        phase = (tick // 4) % 6
        step_y = [22, 21, 22, 23, 22, 21]
        for i, mx in enumerate(range(14, 35, 3)):
            y = step_y[(i + phase) % len(step_y)]
            pygame.draw.rect(canvas, self._fg, (mx, y, 3, 2))
