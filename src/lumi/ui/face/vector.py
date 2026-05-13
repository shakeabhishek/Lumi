"""Vector face renderer — smooth geometric shapes with expressive eyebrows.

Distinct from pixel (chunky 8-bit) and terminal (ASCII CRT): this renderer
uses clean circles, arcs, and thick polylines with no aliasing tricks.
Eyebrows communicate emotion; eyes have a small highlight dot for depth.

States:
  IDLE   — ring eyes + highlight, neutral brows, soft arc smile, slow blink
  LISTEN — wide eyes, raised brows, three fading ripple rings
  THINK  — half-closed eyes, angled inward brows, three phase-offset dots
  SPEAK  — open eyes + highlight, raised brows, thick animated sine mouth
"""

from __future__ import annotations

import math

import numpy as np

from ...hardware.base import Frame
from ...runtime.state_machine import LumiState

_BG: tuple[int, int, int] = (26, 26, 26)
# Highlight is always white regardless of fg color
_HIGHLIGHT: tuple[int, int, int] = (255, 255, 255)


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

    def _draw_eye(self, surface: object, ex: int, ey: int, r: int = 22, pupil_r: int = 9) -> None:
        """Ring eye with filled pupil and a small highlight dot."""
        import pygame  # noqa: PLC0415

        pygame.draw.circle(surface, self._fg, (ex, ey), r, 3)
        pygame.draw.circle(surface, self._fg, (ex, ey), pupil_r)
        # Highlight: small dot offset to upper-left of pupil
        pygame.draw.circle(surface, _HIGHLIGHT, (ex - pupil_r // 3, ey - pupil_r // 3), 3)

    def _draw_brow(
        self, surface: object, ex: int, ey: int, tilt: float = 0.0, raise_: int = 0
    ) -> None:
        """Short thick eyebrow arc above the eye. tilt < 0 = angry inner, > 0 = surprised."""
        import pygame  # noqa: PLC0415

        brow_y = ey - 30 - raise_
        bx0 = ex - 14
        bx1 = ex + 14
        # tilt shifts endpoints: positive tilt lifts inner corner
        y0 = brow_y + int(tilt * 6)
        y1 = brow_y - int(tilt * 6)
        pygame.draw.line(surface, self._fg, (bx0, y0), (bx1, y1), 4)

    def _draw_idle(self, surface: object, tick: int) -> None:
        import pygame  # noqa: PLC0415

        left, right = self._eye_centers()
        blink = tick % 90
        for ex, ey in (left, right):
            if blink < 4:
                # Blink: squish pupil to a line, keep ring
                pygame.draw.circle(surface, self._fg, (ex, ey), 22, 3)
                squish = max(1, int(9 * (1.0 - blink / 4.0)))
                pygame.draw.ellipse(surface, self._fg, (ex - 9, ey - squish, 18, squish * 2))
            else:
                self._draw_eye(surface, ex, ey)
            # Neutral brow — flat, slight raise
            self._draw_brow(surface, ex, ey, tilt=0.0, raise_=0)
        # Soft smile arc
        mouth_rect = pygame.Rect(self._w // 2 - 34, self._h * 2 // 3 - 10, 68, 30)
        pygame.draw.arc(surface, self._fg, mouth_rect, math.pi + 0.4, 2 * math.pi - 0.4, 3)

    def _draw_listen(self, surface: object, tick: int) -> None:
        import pygame  # noqa: PLC0415

        left, right = self._eye_centers()
        for ex, ey in (left, right):
            self._draw_eye(surface, ex, ey, r=26, pupil_r=11)
            # Raised brows — wider open
            self._draw_brow(surface, ex, ey, tilt=0.0, raise_=6)
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
        lx, ly = left
        rx, ry = right
        for ex, ey in (left, right):
            # Half-covered ring eyes
            pygame.draw.circle(surface, self._fg, (ex, ey), 22, 3)
            pygame.draw.rect(surface, _BG, (ex - 25, ey + 1, 50, 28))
            pygame.draw.line(surface, self._fg, (ex - 22, ey), (ex + 22, ey), 3)
        # Angled inward "thinking" brows — inner corners dip
        self._draw_brow(surface, lx, ly, tilt=-0.6, raise_=2)
        self._draw_brow(surface, rx, ry, tilt=0.6, raise_=2)
        # Phase-offset orbiting dots
        dot_y = self._h * 2 // 3
        for i, dot_x in enumerate([self._w // 2 - 40, self._w // 2, self._w // 2 + 40]):
            offset = int(10 * math.sin(tick / 10.0 + i * math.pi * 2.0 / 3.0))
            pygame.draw.circle(surface, self._fg, (dot_x, dot_y + offset), 8)

    def _draw_speak(self, surface: object, tick: int) -> None:
        import pygame  # noqa: PLC0415

        left, right = self._eye_centers()
        for ex, ey in (left, right):
            self._draw_eye(surface, ex, ey)
            # Slightly raised brows — animated/expressive
            self._draw_brow(surface, ex, ey, tilt=0.0, raise_=4)
        # Thick flowing sine mouth
        my = self._h * 2 // 3
        points = [
            (x, my + int(13 * math.sin((x - (self._w // 2 - 72)) / 26.0 + tick / 6.0)))
            for x in range(self._w // 2 - 72, self._w // 2 + 73, 2)
        ]
        if len(points) >= 2:
            pygame.draw.lines(surface, self._fg, False, points, 4)
