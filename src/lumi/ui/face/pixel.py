"""Pixel face renderer — draws Lumi's animated face onto a pygame Surface.

Color palette: warm amber #F5A623 on near-black #1A1A1A.

States:
  IDLE   — two oval eyes, slow blink every ~90 ticks
  LISTEN — eyes wide + expanding pulse ring
  THINK  — eyes half-closed + three bouncing dots
  SPEAK  — eyes open + wavy mouth (sine wave, phase advances per tick)
"""

from __future__ import annotations

import math

import numpy as np

from ...hardware.base import Frame
from ...runtime.state_machine import LumiState

_BG: tuple[int, int, int] = (26, 26, 26)


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

        surface = pygame.Surface((self._w, self._h))
        surface.fill(_BG)
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

    def _eye_centers(self) -> tuple[tuple[int, int], tuple[int, int]]:
        cx = self._w // 2
        cy = self._h // 2 - self._h // 10
        gap = self._w // 6
        return (cx - gap, cy), (cx + gap, cy)

    def _draw_idle(self, surface: object, tick: int) -> None:
        import pygame  # noqa: PLC0415

        left, right = self._eye_centers()
        blink_phase = tick % 90
        ew = 44
        if blink_phase < 4:
            eh = max(2, 36 - blink_phase * 9)
        else:
            eh = 36
        for cx, cy in (left, right):
            pygame.draw.ellipse(surface, self._fg, (cx - ew // 2, cy - eh // 2, ew, eh))

    def _draw_listen(self, surface: object, tick: int) -> None:
        import pygame  # noqa: PLC0415

        left, right = self._eye_centers()
        ew, eh = 52, 46
        for cx, cy in (left, right):
            pygame.draw.ellipse(surface, self._fg, (cx - ew // 2, cy - eh // 2, ew, eh))
        # Expanding pulse rings (two offset rings for depth)
        for offset in (0, 20):
            radius = 70 + ((tick + offset) % 40) * 3
            pygame.draw.circle(surface, self._fg, (self._w // 2, self._h // 2), radius, 2)

    def _draw_think(self, surface: object, tick: int) -> None:
        import pygame  # noqa: PLC0415

        left, right = self._eye_centers()
        ew, eh = 44, 18  # half-closed
        for cx, cy in (left, right):
            pygame.draw.ellipse(surface, self._fg, (cx - ew // 2, cy - eh // 2, ew, eh))
        # Three bouncing dots below center
        dot_y_base = self._h * 2 // 3
        for i, dot_x in enumerate(
            [self._w // 2 - 36, self._w // 2, self._w // 2 + 36]
        ):
            offset = int(8 * math.sin(tick / 8.0 + i * math.pi / 1.5))
            pygame.draw.circle(surface, self._fg, (dot_x, dot_y_base + offset), 7)

    def _draw_speak(self, surface: object, tick: int) -> None:
        import pygame  # noqa: PLC0415

        left, right = self._eye_centers()
        ew, eh = 44, 36
        for cx, cy in (left, right):
            pygame.draw.ellipse(surface, self._fg, (cx - ew // 2, cy - eh // 2, ew, eh))
        # Wavy mouth — sine wave advancing per tick
        my = self._h * 2 // 3
        mx_start = self._w // 2 - 60
        mx_end = self._w // 2 + 60
        prev_x, prev_y = mx_start, my
        for x in range(mx_start + 1, mx_end + 1):
            phase = (x - mx_start) / 30.0 + tick / 8.0
            y = my + int(10 * math.sin(phase))
            pygame.draw.line(surface, self._fg, (prev_x, prev_y), (x, y), 3)
            prev_x, prev_y = x, y
