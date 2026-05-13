"""Vector face renderer — clean geometric shapes, same warm amber palette.

States:
  IDLE   — ring eyes with filled pupil, soft arc mouth, slow blink
  LISTEN — ring eyes with solid pupil, three fading ripple circles
  THINK  — half-covered ring eyes, three phase-offset orbiting dots
  SPEAK  — ring eyes with solid pupil, thick sine-wave mouth
"""

from __future__ import annotations

import math

import numpy as np

from ...hardware.base import Frame
from ...runtime.state_machine import LumiState

_BG: tuple[int, int, int] = (26, 26, 26)


class VectorFaceRenderer:
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
        blink = tick % 90
        for ex, ey in (left, right):
            pygame.draw.circle(surface, self._fg, (ex, ey), 22, 3)
            if blink < 4:
                # Squish pupil to a line during blink
                squish = max(1, int(10 * (1.0 - blink / 4.0)))
                pygame.draw.ellipse(surface, self._fg, (ex - 10, ey - squish, 20, squish * 2))
            else:
                pygame.draw.circle(surface, self._fg, (ex, ey), 10)
        # Gentle resting arc mouth
        mouth_rect = pygame.Rect(self._w // 2 - 32, self._h * 2 // 3 - 8, 64, 28)
        pygame.draw.arc(surface, self._fg, mouth_rect, math.pi + 0.35, 2 * math.pi - 0.35, 3)

    def _draw_listen(self, surface: object, tick: int) -> None:
        import pygame  # noqa: PLC0415

        left, right = self._eye_centers()
        for ex, ey in (left, right):
            pygame.draw.circle(surface, self._fg, (ex, ey), 26, 3)
            pygame.draw.circle(surface, self._fg, (ex, ey), 12)
        # Three fading ripple rings
        cx, cy = self._w // 2, self._h // 2
        for i in range(3):
            phase = (tick + i * 15) % 45
            fade = 1.0 - phase / 45.0
            r = 55 + phase * 4
            color = tuple(max(0, int(c * fade)) for c in self._fg)
            pygame.draw.circle(surface, color, (cx, cy), r, 2)

    def _draw_think(self, surface: object, tick: int) -> None:
        import pygame  # noqa: PLC0415

        left, right = self._eye_centers()
        for ex, ey in (left, right):
            # Full ring, then mask lower half with bg to look half-closed
            pygame.draw.circle(surface, self._fg, (ex, ey), 22, 3)
            pygame.draw.rect(surface, _BG, (ex - 25, ey + 1, 50, 28))
            pygame.draw.line(surface, self._fg, (ex - 22, ey), (ex + 22, ey), 3)
        # Phase-offset orbiting dots
        dot_y = self._h * 2 // 3
        for i, dot_x in enumerate([self._w // 2 - 40, self._w // 2, self._w // 2 + 40]):
            offset = int(10 * math.sin(tick / 10.0 + i * math.pi * 2.0 / 3.0))
            pygame.draw.circle(surface, self._fg, (dot_x, dot_y + offset), 8)

    def _draw_speak(self, surface: object, tick: int) -> None:
        import pygame  # noqa: PLC0415

        left, right = self._eye_centers()
        for ex, ey in (left, right):
            pygame.draw.circle(surface, self._fg, (ex, ey), 22, 3)
            pygame.draw.circle(surface, self._fg, (ex, ey), 10)
        # Thick flowing sine mouth
        my = self._h * 2 // 3
        points = [
            (x, my + int(13 * math.sin((x - (self._w // 2 - 72)) / 26.0 + tick / 6.0)))
            for x in range(self._w // 2 - 72, self._w // 2 + 73, 2)
        ]
        if len(points) >= 2:
            pygame.draw.lines(surface, self._fg, False, points, 4)
