"""Pixel face renderer — kawaii 8-bit expressions per state.

Replaces the original pink-heart-eye face. The redesign was driven by a
Figma reference (face.zip in the project parent dir) showing a 16-face
kawaii expression set: round black eyes with white highlights, pink
blush ovals, eyelid lines above, and varying mouth shapes.

Renders on a 48×32 canvas (same as before — engine wiring unchanged)
then scales up to fill the 480×320 display. State → composition:

  IDLE   — open eyes, gentle smile, blush. Slow blink every ~3s.
  LISTEN — eyes wide + raised brows ("ready to hear"). Slight surprise.
  THINK  — eyes glance up + flat mouth + side-floating dot trail.
  SPEAK  — closed happy arcs (^_^) + open smile that pulses on mouth tick.

Colour theming:
  - `fg_color` (constructor) tints the outline/eyebrow accent — lets the
    user pick their face colour in /settings/face.
  - Eye black, white highlight, and pink blush stay fixed: the kawaii
    palette is part of the style. Theming the eyes' base colour would
    make every shade except the original look creepy.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from ...hardware.base import Frame
from ...runtime.state_machine import LumiState

if TYPE_CHECKING:
    import pygame as _pygame

# Canvas + display ---------------------------------------------------------
_CW, _CH = 48, 32          # small grid scaled 10× to fill 480×320

# Palette (kawaii-fixed except the accent) ----------------------------------
_BG = (252, 240, 232)        # warm cream — soft on the eye for a desk display
_EYE_DARK = (28, 20, 32)     # near-black with a hint of indigo
_EYE_HIGHLIGHT = (255, 255, 255)
_BLUSH = (255, 168, 184)     # pink — independent of accent so it doesn't clash
_SHADOW = (220, 200, 196)    # subtle face shadow under the chin

# Eye positions (centre x of each eye) — symmetrical around the face midline
_EYE_Y = 13
_LEFT_EYE_X = 17
_RIGHT_EYE_X = 31


# ── Component patterns (relative coordinates) ──────────────────────────────
# Each pattern is a list of (dx, dy, colour-tag) tuples, anchored to the
# component's centre. Colour tags: "dark" (eye outline), "hi" (highlight),
# "blush", "accent" (uses fg_color).

EyeFrame = list[tuple[int, int, str]]


def _eye_open() -> EyeFrame:
    """4-wide, 5-tall round eye with a single white highlight pixel."""
    out: EyeFrame = []
    # Filled near-circle, 4×4
    for dy in range(4):
        for dx in range(4):
            if (dx, dy) in {(0, 0), (3, 0), (0, 3), (3, 3)}:        # rounded corners
                continue
            out.append((dx, dy, "dark"))
    # Highlight: top-left interior
    out.append((1, 0, "hi"))
    return out


def _eye_blink() -> EyeFrame:
    """Closed eye — a flat line at the bottom of the open-eye bounds."""
    return [(dx, 3, "dark") for dx in range(4)]


def _eye_happy() -> EyeFrame:
    """^_^ closed arc — happy/speaking expression."""
    return [
        (0, 2, "dark"), (1, 1, "dark"), (2, 1, "dark"), (3, 2, "dark"),
    ]


def _eye_wide() -> EyeFrame:
    """Slightly taller open eye for the surprised/listening state."""
    out: EyeFrame = []
    for dy in range(5):
        for dx in range(4):
            if (dx, dy) in {(0, 0), (3, 0), (0, 4), (3, 4)}:
                continue
            out.append((dx, dy, "dark"))
    out.append((1, 1, "hi"))            # highlight a bit lower
    return out


def _eye_up() -> EyeFrame:
    """Looking-up eye for THINK — pupil at the top."""
    out: EyeFrame = []
    # Outline only on the bottom + sides; iris/pupil at the very top
    for dy in range(4):
        for dx in range(4):
            if dy == 0 and dx in {1, 2}:        # top: solid (the pupil moved up)
                out.append((dx, dy, "dark"))
            elif dy in {1, 2} and dx in {0, 3}:  # sides
                out.append((dx, dy, "dark"))
            elif dy == 3 and dx in {1, 2}:       # bottom curve
                out.append((dx, dy, "dark"))
    return out


# Brow patterns -------------------------------------------------------------

def _brow_neutral() -> EyeFrame:
    """Subtle arched line above the eye."""
    return [(0, 0, "accent"), (1, 0, "accent"), (2, 0, "accent"), (3, 0, "accent")]


def _brow_raised() -> EyeFrame:
    """Diagonal-up line — questioning / listening."""
    return [(0, 1, "accent"), (1, 0, "accent"), (2, 0, "accent"), (3, 0, "accent")]


def _brow_thinking() -> EyeFrame:
    """Inverted arch — pinched / contemplative."""
    return [(0, 0, "accent"), (1, 1, "accent"), (2, 1, "accent"), (3, 0, "accent")]


# Mouth patterns ------------------------------------------------------------

def _mouth_smile() -> list[tuple[int, int, str]]:
    """Gentle "u" smile spanning ~10px wide.

    Pixels are relative to the mouth's CENTRE-bottom anchor so it sits
    symmetrically between the two blush cheeks.
    """
    return [
        (-4, 0, "dark"),
        (-3, 1, "dark"), (-2, 2, "dark"), (-1, 2, "dark"),
        (0, 2, "dark"), (1, 2, "dark"), (2, 2, "dark"),
        (3, 1, "dark"),
        (4, 0, "dark"),
    ]


def _mouth_o() -> list[tuple[int, int, str]]:
    """Small round "o" for surprise/listen."""
    return [
        (-1, 0, "dark"), (0, 0, "dark"),
        (-2, 1, "dark"),                (1, 1, "dark"),
        (-1, 2, "dark"), (0, 2, "dark"),
    ]


def _mouth_line() -> list[tuple[int, int, str]]:
    """Flat line — thinking / unreadable."""
    return [(dx, 1, "dark") for dx in range(-3, 4)]


def _mouth_open_smile_small() -> list[tuple[int, int, str]]:
    return [
        (-3, 0, "dark"), (3, 0, "dark"),
        (-2, 1, "dark"), (-1, 1, "dark"), (0, 1, "dark"), (1, 1, "dark"), (2, 1, "dark"),
        (-1, 2, "dark"), (0, 2, "dark"), (1, 2, "dark"),
    ]


def _mouth_open_smile_wide() -> list[tuple[int, int, str]]:
    return [
        (-4, 0, "dark"), (4, 0, "dark"),
        (-3, 1, "dark"), (-2, 1, "dark"), (-1, 1, "dark"),
        (0, 1, "dark"), (1, 1, "dark"), (2, 1, "dark"), (3, 1, "dark"),
        (-2, 2, "dark"), (-1, 2, "dark"), (0, 2, "dark"), (1, 2, "dark"), (2, 2, "dark"),
        (-1, 3, "dark"), (0, 3, "dark"), (1, 3, "dark"),
    ]


class PixelFaceRenderer:
    """Hand-pixeled kawaii expressions per state, composed at runtime.

    Stays drop-in compatible with the engine: same constructor signature
    and `render(state, tick)` contract as the previous heart-eye version.
    The `fg_color` kwarg now tints only the eyebrow/accent — eye black,
    blush pink, and highlight white are fixed because the kawaii palette
    only reads right with that specific contrast.
    """

    def __init__(
        self,
        width: int,
        height: int,
        fg_color: tuple[int, int, int] = (255, 107, 157),  # pink accent — used for brows
    ) -> None:
        self._w = width
        self._h = height
        self._accent = fg_color
        self._color_for = {
            "dark": _EYE_DARK,
            "hi": _EYE_HIGHLIGHT,
            "blush": _BLUSH,
            "accent": self._accent,
        }

    # ── Public API ─────────────────────────────────────────────────────────

    def render(self, state: LumiState, tick: int) -> Frame:
        import pygame  # noqa: PLC0415

        canvas = pygame.Surface((_CW, _CH))
        canvas.fill(_BG)

        # A soft chin shadow on every frame so the face has a base.
        for x in range(8, _CW - 8):
            canvas.set_at((x, _CH - 4), _SHADOW)
        for x in range(10, _CW - 10):
            canvas.set_at((x, _CH - 3), _SHADOW)

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

    # ── State compositions ─────────────────────────────────────────────────

    def _draw_idle(self, canvas: _pygame.Surface, tick: int) -> None:
        # Slow blink: closed for ~5 ticks every 100.
        is_blinking = (tick % 100) < 5
        eye = _eye_blink() if is_blinking else _eye_open()
        self._draw_eyes(canvas, eye, _brow_neutral() if not is_blinking else [])
        if not is_blinking:
            self._draw_blush(canvas)
        self._stamp_pattern(canvas, _mouth_smile(), _CW // 2, 22)

    def _draw_listen(self, canvas: _pygame.Surface, tick: int) -> None:        # noqa: ARG002
        self._draw_eyes(canvas, _eye_wide(), _brow_raised())
        self._draw_blush(canvas)
        self._stamp_pattern(canvas, _mouth_o(), _CW // 2, 22)

    def _draw_think(self, canvas: _pygame.Surface, tick: int) -> None:
        self._draw_eyes(canvas, _eye_up(), _brow_thinking())
        # No blush — thinking is a more sober expression.
        self._stamp_pattern(canvas, _mouth_line(), _CW // 2, 22)
        # Three dots scrolling at the side, indicating "processing".
        dot_phase = (tick // 12) % 3
        for i in range(3):
            colour = self._accent if i == dot_phase else tuple(c // 3 for c in self._accent)
            for dx in range(2):
                for dy in range(2):
                    canvas.set_at((38 + i * 3 + dx, 14 + dy), colour)

    def _draw_speak(self, canvas: _pygame.Surface, tick: int) -> None:
        self._draw_eyes(canvas, _eye_happy(), _brow_neutral())
        self._draw_blush(canvas)
        # Mouth alternates between small + wide smile so it reads as talking.
        wide = (tick // 6) % 2 == 0
        mouth = _mouth_open_smile_wide() if wide else _mouth_open_smile_small()
        self._stamp_pattern(canvas, mouth, _CW // 2, 21)

    # ── Helpers ────────────────────────────────────────────────────────────

    def _draw_eyes(
        self,
        canvas: _pygame.Surface,
        eye_pattern: EyeFrame,
        brow_pattern: EyeFrame,
    ) -> None:
        # Each eye pattern is anchored to its top-left; the eye centre is
        # offset by (2, 2) relative to that — so we subtract to position
        # the *centre* over the eye coordinate.
        for cx in (_LEFT_EYE_X, _RIGHT_EYE_X):
            self._stamp_pattern(canvas, eye_pattern, cx - 1, _EYE_Y - 2)
            if brow_pattern:
                # Brow sits 3 pixels above the eye top.
                self._stamp_pattern(canvas, brow_pattern, cx - 1, _EYE_Y - 5)

    def _draw_blush(self, canvas: _pygame.Surface) -> None:
        for cx in (_LEFT_EYE_X, _RIGHT_EYE_X):
            for dx in range(-2, 3):
                for dy in range(2):
                    canvas.set_at((cx + dx, _EYE_Y + 4 + dy), _BLUSH)

    def _stamp_pattern(
        self,
        canvas: _pygame.Surface,
        pattern: list[tuple[int, int, str]],
        x: int,
        y: int,
    ) -> None:
        """Place a relative-coords pattern at canvas (x, y). Out-of-bounds
        pixels are silently dropped."""
        w, h = _CW, _CH
        for dx, dy, tag in pattern:
            px, py = x + dx, y + dy
            if 0 <= px < w and 0 <= py < h:
                canvas.set_at((px, py), self._color_for[tag])
