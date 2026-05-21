"""Ambient idle scenes — what Lumi shows when she's not actively talking.

The brief: tamagotchi-ish, soothing, alive without being busy. Rather than
just floating the face, when IDLE Lumi can play an ambient scene.

Each scene implements:

    class Scene:
        def render(self, surface: pygame.Surface, tick: int, w: int, h: int) -> None: ...

The ScreenCompositor swaps a scene in for the face area when state == IDLE
and a scene is configured. State transitions (LISTEN/THINK/SPEAK) bring
the face back.

Scenes available now:
  - RainScene  : ambient rainfall on a deep night palette. Procedural,
                 zero assets, very soothing. Default for V1.

Sketched out (not yet implemented — easy to add):
  - AuroraScene  : color washes drifting across the screen
  - SnowScene    : winter variant of rain
  - CatScene     : sprite-based "sleeping cat that occasionally twitches"
  - MarioScene   : sprite-based pixel character walking left↔right
  - ClockOnlyScene : just a big serif clock, no face

Add a new scene by subclassing nothing (it's just a duck-typed protocol)
and registering it in `SCENES` below.
"""

from __future__ import annotations

import random
from typing import Protocol


class IdleScene(Protocol):
    def render(self, surface: object, tick: int, w: int, h: int) -> None: ...


# ── Rain ────────────────────────────────────────────────────────────────────


class RainScene:
    """Soft rainfall against a deep blue gradient. Drops vary in length,
    speed, and brightness so it feels like a layered rain field rather than
    identical pixels. Subtle low-amplitude pulse so it's not boring."""

    _N_DROPS = 60
    _PALETTE_TOP = (10, 14, 30)        # deep night blue at the top
    _PALETTE_BOT = (24, 28, 56)        # slightly warmer at the bottom
    _DROP_COLOR = (170, 200, 240)

    def __init__(self) -> None:
        self._drops: list[dict] = []      # lazy-init on first render (need w/h)
        self._w = 0
        self._h = 0

    def _ensure_drops(self, w: int, h: int) -> None:
        if self._drops and self._w == w and self._h == h:
            return
        self._w = w
        self._h = h
        rng = random.Random(0xCAFE)
        self._drops = [
            {
                "x": rng.uniform(0, w),
                "y": rng.uniform(0, h),
                "speed": rng.uniform(2.2, 5.5),
                "length": rng.randint(6, 14),
                "alpha": rng.randint(140, 220),
            }
            for _ in range(self._N_DROPS)
        ]

    def render(self, surface: object, tick: int, w: int, h: int) -> None:
        import pygame  # noqa: PLC0415

        self._ensure_drops(w, h)

        # vertical gradient backdrop
        for y in range(h):
            t = y / max(h - 1, 1)
            r = int(self._PALETTE_TOP[0] * (1 - t) + self._PALETTE_BOT[0] * t)
            g = int(self._PALETTE_TOP[1] * (1 - t) + self._PALETTE_BOT[1] * t)
            b = int(self._PALETTE_TOP[2] * (1 - t) + self._PALETTE_BOT[2] * t)
            pygame.draw.line(surface, (r, g, b), (0, y), (w, y))

        # raindrops
        for d in self._drops:
            d["y"] += d["speed"]
            if d["y"] > h + d["length"]:
                d["y"] = -d["length"]
                d["x"] = random.uniform(0, w)
            x = int(d["x"])
            y = int(d["y"])
            color = (
                min(255, self._DROP_COLOR[0]),
                min(255, self._DROP_COLOR[1]),
                min(255, self._DROP_COLOR[2]),
            )
            pygame.draw.line(surface, color, (x, y), (x, y + d["length"]))

        # subtle wash to suggest depth
        if tick % 2 == 0:
            wash = pygame.Surface((w, h), pygame.SRCALPHA)
            wash.fill((255, 255, 255, 6))
            surface.blit(wash, (0, 0))


# ── Snow (small variant, free) ──────────────────────────────────────────────


class SnowScene:
    """Lazy snowfall on a slate backdrop. Same skeleton as RainScene but
    flakes drift diagonally and shimmer."""

    _N_FLAKES = 50
    _BG = (14, 18, 26)

    def __init__(self) -> None:
        self._flakes: list[dict] = []
        self._w = 0
        self._h = 0

    def _ensure_flakes(self, w: int, h: int) -> None:
        if self._flakes and self._w == w and self._h == h:
            return
        self._w = w
        self._h = h
        rng = random.Random(0xBEEF)
        self._flakes = [
            {
                "x": rng.uniform(0, w),
                "y": rng.uniform(0, h),
                "speed": rng.uniform(0.6, 1.8),
                "drift": rng.uniform(-0.4, 0.4),
                "size": rng.randint(1, 3),
                "phase": rng.uniform(0, 6.28),
            }
            for _ in range(self._N_FLAKES)
        ]

    def render(self, surface: object, tick: int, w: int, h: int) -> None:
        import math  # noqa: PLC0415
        import pygame  # noqa: PLC0415

        self._ensure_flakes(w, h)
        surface.fill(self._BG)
        for f in self._flakes:
            f["y"] += f["speed"]
            f["x"] += f["drift"] + math.sin((tick + f["phase"] * 20) / 40) * 0.5
            if f["y"] > h + 2:
                f["y"] = -2
                f["x"] = random.uniform(0, w)
            if f["x"] < -2: f["x"] = w + 2
            if f["x"] > w + 2: f["x"] = -2
            shimmer = 200 + int(40 * math.sin((tick + f["phase"] * 30) / 18))
            pygame.draw.circle(
                surface, (shimmer, shimmer, min(255, shimmer + 10)),
                (int(f["x"]), int(f["y"])), f["size"],
            )


# ── Registry ────────────────────────────────────────────────────────────────


SCENES: dict[str, type] = {
    "none":   type("_NoScene", (), {"render": lambda self, s, t, w, h: None}),
    "rain":   RainScene,
    "snow":   SnowScene,
}


def make_scene(name: str) -> IdleScene | None:
    """Build a scene by name. None / 'none' / unknown → None (just the face)."""
    if not name or name == "none":
        return None
    cls = SCENES.get(name.lower())
    return cls() if cls else None
