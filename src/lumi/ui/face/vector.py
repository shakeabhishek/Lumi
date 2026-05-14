"""Vector face renderer — Twemoji emojis cycling with Lumi's state.

Replaces the previous hand-drawn vector face with Twitter's open-source
Twemoji set, the same family used by the web onboarding preview. One emoji
per state, blitted to the center of the frame with a gentle vertical float.

Renders entirely on-device. The first call downloads four 72x72 PNGs from
jsDelivr's Twemoji mirror and caches them under `models/twemoji/`; every
render after that reads the cache.

State → emoji:
  IDLE   → 😍   smiling face with heart-eyes
  LISTEN → 🤗   hugging face
  THINK  → 🤔   thinking face
  SPEAK  → 😄   grinning face with smiling eyes
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from ...hardware.base import Frame
from ...log import get_logger
from ...runtime.state_machine import LumiState
from .twemoji import codepoint_for, ensure_cached

log = get_logger(__name__)

_BG: tuple[int, int, int] = (26, 26, 26)


class VectorFaceRenderer:
    """Per-state Twemoji blitter with subtle float animation.

    `fg_color` is kept on the constructor for API compatibility with the
    pixel + terminal renderers — Twemoji are full-color PNGs so it's only
    used for the fallback drawn circle when fetch fails offline.
    """

    def __init__(
        self,
        width: int,
        height: int,
        fg_color: tuple[int, int, int] = (245, 166, 35),
        models_dir: Path | None = None,
    ) -> None:
        self._w = width
        self._h = height
        self._fg = fg_color
        self._models_dir = models_dir if models_dir is not None else Path("./models")
        self._emoji_size = int(min(width, height) * 0.60)
        self._cache: dict[LumiState, object] = {}  # state → pygame.Surface
        self._load()

    def _load(self) -> None:
        import pygame  # noqa: PLC0415

        # Fetch at 2x render size so smoothscale-down looks crisp.
        paths = ensure_cached(self._models_dir, size=max(self._emoji_size * 2, 256))
        for state, path in paths.items():
            try:
                surf = pygame.image.load(str(path)).convert_alpha()
                surf = pygame.transform.smoothscale(surf, (self._emoji_size, self._emoji_size))
                self._cache[state] = surf
            except Exception as exc:
                log.warning("twemoji.load_failed", state=state.value, error=str(exc))

    def render(self, state: LumiState, tick: int) -> Frame:
        import pygame  # noqa: PLC0415

        surface = pygame.Surface((self._w, self._h))
        surface.fill(_BG)

        emoji = self._cache.get(state) or self._cache.get(LumiState.IDLE)
        if emoji is not None:
            # Gentle ±4 px float synced to tick.
            float_y = int(4 * math.sin(tick / 10.0))
            x = (self._w - self._emoji_size) // 2
            y = (self._h - self._emoji_size) // 2 + float_y
            surface.blit(emoji, (x, y))
        else:
            # Offline fallback when Twemoji couldn't be cached and there's no
            # prior download. Draws a simple amber face so something renders.
            self._draw_fallback(surface, state, tick)

        pixels = np.transpose(pygame.surfarray.array3d(surface), (1, 0, 2))
        return Frame(pixels=pixels)

    def _draw_fallback(self, surface: object, state: LumiState, tick: int) -> None:
        import pygame  # noqa: PLC0415

        log.debug("vector_face.fallback", state=state.value, codepoint=codepoint_for(state))
        cx, cy = self._w // 2, self._h // 2
        r = min(self._w, self._h) // 4
        # Soft pulse so the offline fallback still feels alive.
        pulse = int(2 * math.sin(tick / 8.0))
        pygame.draw.circle(surface, self._fg, (cx, cy), r + pulse, 3)
        # Two dot eyes; smile arc.
        pygame.draw.circle(surface, self._fg, (cx - r // 3, cy - r // 4), max(3, r // 10))
        pygame.draw.circle(surface, self._fg, (cx + r // 3, cy - r // 4), max(3, r // 10))
        mouth = pygame.Rect(cx - r // 2, cy - r // 4, r, r // 2)
        pygame.draw.arc(surface, self._fg, mouth, math.pi + 0.4, 2 * math.pi - 0.4, 3)
