"""Terminal face renderer — CRT phosphor aesthetic with cute kawaii bear face.

Replaces the original box-eye ASCII art with the kawaii bear (`ʕ ᴥ ʔ`)
the user picked during onboarding preview. Body characters render in
phosphor green (terminal aesthetic); heart eyes render in pink so the
cute-bear vibe carries.

States:
  IDLE   — ʕ♥ᴥ♥ʔ  (heart-eyed, content)        slow blink to ʕ-ᴥ-ʔ
  LISTEN — ʕ◉ᴥ◉ʔ  (alert, ears up)             "Listening" with a pulsing bar
  THINK  — ʕ•ᴥ•ʔ  (small eyes, focused)        cycling thought dots
  SPEAK  — ʕ⌐■ᴥ■ʔ (mouth open)                cycling sine wave
"""

from __future__ import annotations

import numpy as np

from ...hardware.base import Frame
from ...runtime.state_machine import LumiState

_BG: tuple[int, int, int] = (0, 0, 0)
_PINK: tuple[int, int, int] = (255, 122, 201)        # heart pink, on top of phosphor green body

_FACE_FONT_SIZE = 80     # the bear face — big, like the dashboard preview
_LABEL_FONT_SIZE = 18

# State → (face_string, label_or_animation_callback)
_FACES = {
    LumiState.IDLE:   "ʕ♥ᴥ♥ʔ",
    LumiState.LISTEN: "ʕ◉ᴥ◉ʔ",
    LumiState.THINK:  "ʕ•ᴥ•ʔ",
    LumiState.SPEAK:  "ʕ⌐■ᴥ■ʔ",
}
# Blink frame for IDLE: every ~90 ticks, eyes close for ~4 ticks
_IDLE_BLINK = "ʕ-ᴥ-ʔ"

# Bottom animation bars/dots by state (label is below the face)
_LISTEN_BAR = ("[          ]", "[==        ]", "[====      ]", "[======    ]",
               "[========  ]", "[==========]", "[========  ]", "[======    ]",
               "[====      ]", "[==        ]")
_THINK_DOTS = (".   ", "..  ", "... ", "....", " ...", "  ..", "   .", "    ")


class TerminalFaceRenderer:
    """Cute kawaii bear face on CRT phosphor scanlines."""

    def __init__(
        self,
        width: int,
        height: int,
        fg_color: tuple[int, int, int] = (51, 255, 51),       # phosphor green
    ) -> None:
        self._w = width
        self._h = height
        self._fg = fg_color
        self._scan = tuple(max(0, int(c * 0.07)) for c in fg_color)
        self._face_font: object | None = None
        self._label_font: object | None = None

    def _get_face_font(self) -> object:
        if self._face_font is None:
            import pygame  # noqa: PLC0415

            # Try fonts known to ship the Canadian-Syllabics codepoint (ʕ ʔ).
            # SF Mono on macOS / DejaVu Sans Mono on Linux both have it.
            for name in ("SF Mono", "DejaVu Sans Mono", "Menlo", "Consolas", "monospace"):
                try:
                    f = pygame.font.SysFont(name, _FACE_FONT_SIZE)
                    if f.size("ʕ")[0] > 0:
                        self._face_font = f
                        break
                except Exception:
                    continue
            if self._face_font is None:
                self._face_font = pygame.font.Font(None, _FACE_FONT_SIZE)
        return self._face_font

    def _get_label_font(self) -> object:
        if self._label_font is None:
            import pygame  # noqa: PLC0415

            try:
                self._label_font = pygame.font.SysFont("monospace", _LABEL_FONT_SIZE, bold=True)
            except Exception:
                self._label_font = pygame.font.Font(None, _LABEL_FONT_SIZE)
        return self._label_font

    def render(self, state: LumiState, tick: int) -> Frame:
        import pygame  # noqa: PLC0415

        surface = pygame.Surface((self._w, self._h))
        surface.fill(_BG)
        self._draw_scanlines(surface)

        face_text = _FACES.get(state, _FACES[LumiState.IDLE])
        # Blink for IDLE
        if state == LumiState.IDLE and (tick % 90) < 4:
            face_text = _IDLE_BLINK
        self._blit_face_with_pink_hearts(surface, face_text)

        # State-specific bottom-row animation
        label = self._label_for(state, tick)
        if label:
            self._blit_label(surface, label)

        pixels = np.transpose(pygame.surfarray.array3d(surface), (1, 0, 2))
        return Frame(pixels=pixels)

    # ── helpers ─────────────────────────────────────────────────────────────

    def _draw_scanlines(self, surface: object) -> None:
        import pygame  # noqa: PLC0415

        for y in range(0, self._h, 2):
            pygame.draw.line(surface, self._scan, (0, y), (self._w, y))

    def _blit_face_with_pink_hearts(self, surface: object, text: str) -> None:
        """Render the bear face char-by-char so the hearts can be pink while
        the body characters render in the foreground (phosphor) color."""
        font = self._get_face_font()
        # First measure the whole string so we can center.
        glyph_surfaces = []
        for ch in text:
            color = _PINK if ch == "♥" else self._fg
            glyph_surfaces.append(font.render(ch, True, color))  # type: ignore[attr-defined]
        total_w = sum(g.get_width() for g in glyph_surfaces)
        max_h = max((g.get_height() for g in glyph_surfaces), default=0)
        x = (self._w - total_w) // 2
        y = (self._h - max_h) // 2 - 10  # nudge up a touch so label fits below
        for g in glyph_surfaces:
            surface.blit(g, (x, y))  # type: ignore[attr-defined]
            x += g.get_width()

    def _blit_label(self, surface: object, text: str) -> None:
        font = self._get_label_font()
        img = font.render(text, True, self._fg)  # type: ignore[attr-defined]
        x = (self._w - img.get_width()) // 2
        y = (self._h * 3) // 4
        surface.blit(img, (x, y))  # type: ignore[attr-defined]

    def _label_for(self, state: LumiState, tick: int) -> str:
        if state == LumiState.LISTEN:
            return _LISTEN_BAR[(tick // 4) % len(_LISTEN_BAR)]
        if state == LumiState.THINK:
            return _THINK_DOTS[(tick // 6) % len(_THINK_DOTS)]
        if state == LumiState.SPEAK:
            offset = tick % 8
            return ("~-~^~-~^~-~^~-~^"[offset: offset + 12])
        return ""
