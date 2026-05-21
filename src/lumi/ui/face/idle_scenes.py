"""Ambient idle scenes — what Lumi shows when she's not actively talking.

The brief: tamagotchi-ish, soothing, alive without being busy. Rather than
just floating the face, when IDLE Lumi can play an ambient scene. The
ScreenCompositor swaps a scene in for the face area when state == IDLE.
State transitions (LISTEN/THINK/SPEAK) bring the face back instantly.

Scene catalog
─────────────

Procedural (zero assets, ship today):
  - RainScene   : rainfall on a deep blue night gradient
  - SnowScene   : drifting snow on slate

Sprite-based (drop in PNG frames at src/lumi/ui/face/assets/sprites/<name>/):
  - SpriteLoopScene : generic frame loop. Add a directory with frame_001.png,
                      frame_002.png, … and a small `manifest.json`:
                      {"fps": 6, "scale": 4, "anchor": "center", "background": "#0a0e1e"}
                      then register it in SCENES below.

Free/CC0 sprite sources worth pulling from:
  - kenney.nl/assets (CC0) — "1-Bit Pack", "Toon Characters", "Pixel Platformer"
  - opengameart.org (CC0/CC-BY) — search "sleeping cat", "idle creature"
  - itch.io (filter free) — Pixel Frog, Penzilla, MrBubbleWand are reliable
  - The shut-down Glitch game's art dump (public domain) — softer storybook
    style, less pixel-y

To wire a downloaded sprite pack:
  1. Drop frames in src/lumi/ui/face/assets/sprites/sleeping-cat/
     (frame_001.png, frame_002.png, … all same size)
  2. Add a manifest.json in that directory
  3. Add to SCENES: "cat": lambda: SpriteLoopScene("sleeping-cat")
  4. Add "cat" to FACE_THEMES' idle_scene dropdown options in
     src/lumi/ui/web/templates/settings/face.html

Add a new procedural scene by subclassing nothing (it's just a duck-typed
protocol) and registering it in SCENES below.
"""

from __future__ import annotations

import json
import math
import random
from pathlib import Path
from typing import Any, Protocol


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
        # Cached surfaces — recomputed only on resize, NOT per frame.
        # Re-rendering the per-line gradient and allocating a fresh SRCALPHA
        # surface every two frames was the dominant cost on the Pi (~9.6k
        # line calls per second at 30fps).
        self._gradient: object | None = None
        self._wash: object | None = None
        self._rng = random.Random(0xCAFE)

    def _ensure_caches(self, w: int, h: int) -> None:
        import pygame  # noqa: PLC0415

        if self._drops and self._w == w and self._h == h:
            return
        self._w = w
        self._h = h
        self._rng = random.Random(0xCAFE)
        self._drops = [
            {
                "x": self._rng.uniform(0, w),
                "y": self._rng.uniform(0, h),
                "speed": self._rng.uniform(2.2, 5.5),
                "length": self._rng.randint(6, 14),
                "alpha": self._rng.randint(140, 220),
            }
            for _ in range(self._N_DROPS)
        ]
        # Render the gradient once into a backing surface.
        self._gradient = pygame.Surface((w, h))
        for y in range(h):
            t = y / max(h - 1, 1)
            r = int(self._PALETTE_TOP[0] * (1 - t) + self._PALETTE_BOT[0] * t)
            g = int(self._PALETTE_TOP[1] * (1 - t) + self._PALETTE_BOT[1] * t)
            b = int(self._PALETTE_TOP[2] * (1 - t) + self._PALETTE_BOT[2] * t)
            pygame.draw.line(self._gradient, (r, g, b), (0, y), (w, y))
        # And the alpha wash — one allocation, reused every frame it's drawn.
        self._wash = pygame.Surface((w, h), pygame.SRCALPHA)
        self._wash.fill((255, 255, 255, 6))

    def render(self, surface: object, tick: int, w: int, h: int) -> None:
        import pygame  # noqa: PLC0415

        self._ensure_caches(w, h)

        # Blit the cached gradient — one operation, not 320 line draws.
        surface.blit(self._gradient, (0, 0))

        # raindrops
        for d in self._drops:
            d["y"] += d["speed"]
            if d["y"] > h + d["length"]:
                d["y"] = -d["length"]
                d["x"] = self._rng.uniform(0, w)
            x = int(d["x"])
            y = int(d["y"])
            pygame.draw.line(surface, self._DROP_COLOR, (x, y), (x, y + d["length"]))

        # subtle wash to suggest depth — cached surface, no allocation.
        if tick % 2 == 0:
            surface.blit(self._wash, (0, 0))


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
        self._rng = random.Random(0xBEEF)

    def _ensure_flakes(self, w: int, h: int) -> None:
        if self._flakes and self._w == w and self._h == h:
            return
        self._w = w
        self._h = h
        self._rng = random.Random(0xBEEF)
        self._flakes = [
            {
                "x": self._rng.uniform(0, w),
                "y": self._rng.uniform(0, h),
                "speed": self._rng.uniform(0.6, 1.8),
                "drift": self._rng.uniform(-0.4, 0.4),
                "size": self._rng.randint(1, 3),
                "phase": self._rng.uniform(0, 6.28),
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
                f["x"] = self._rng.uniform(0, w)
            if f["x"] < -2: f["x"] = w + 2
            if f["x"] > w + 2: f["x"] = -2
            shimmer = 200 + int(40 * math.sin((tick + f["phase"] * 30) / 18))
            pygame.draw.circle(
                surface, (shimmer, shimmer, min(255, shimmer + 10)),
                (int(f["x"]), int(f["y"])), f["size"],
            )


# ── Generic sprite-loop scene (drop PNG frames in, no code) ────────────────


_SPRITES_DIR = Path(__file__).parent / "assets" / "sprites"


class SpriteLoopScene:
    """Loops PNG frames from <repo>/src/lumi/ui/face/assets/sprites/<name>/.

    Directory layout:
        sleeping-cat/
            manifest.json    (optional — fps/scale/background/anchor)
            frame_001.png
            frame_002.png
            …

    manifest.json (all keys optional):
        {
            "fps": 6,
            "scale": 4,
            "anchor": "center" | "bottom" | "top",
            "background": "#0a0e1e"
        }
    """

    def __init__(self, sprite_dir_name: str) -> None:
        self._dir = _SPRITES_DIR / sprite_dir_name
        self._frames: list[object] = []     # pygame.Surface
        self._loaded = False
        # Manifest defaults
        self._fps = 6
        self._scale = 4
        self._anchor = "center"
        self._bg = (10, 14, 30)

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not self._dir.is_dir():
            return
        # Load manifest
        mf = self._dir / "manifest.json"
        if mf.exists():
            try:
                m: dict[str, Any] = json.loads(mf.read_text())
                self._fps = int(m.get("fps", self._fps))
                self._scale = int(m.get("scale", self._scale))
                self._anchor = m.get("anchor", self._anchor)
                if isinstance(m.get("background"), str) and m["background"].startswith("#"):
                    h = m["background"].lstrip("#")
                    self._bg = (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
            except (json.JSONDecodeError, OSError, ValueError):
                pass

        import pygame  # noqa: PLC0415

        frame_paths = sorted(p for p in self._dir.iterdir() if p.suffix.lower() == ".png")
        for p in frame_paths:
            try:
                img = pygame.image.load(str(p))
                if self._scale > 1:
                    img = pygame.transform.scale(
                        img, (img.get_width() * self._scale, img.get_height() * self._scale),
                    )
                self._frames.append(img)
            except Exception:
                continue

    def render(self, surface: object, tick: int, w: int, h: int) -> None:
        import pygame  # noqa: PLC0415

        self._ensure_loaded()
        surface.fill(self._bg)
        if not self._frames:
            # No sprites available — show a soft placeholder so it's obvious why
            font = pygame.font.Font(None, 14)
            msg = font.render(
                f"sprite folder is empty: {self._dir.name}", True, (160, 160, 170),
            )
            surface.blit(msg, ((w - msg.get_width()) // 2, h // 2))
            return
        # Advance one frame every (30 / fps) ticks (render loop is ~30Hz)
        ticks_per_frame = max(1, 30 // self._fps)
        idx = (tick // ticks_per_frame) % len(self._frames)
        sprite = self._frames[idx]
        x = (w - sprite.get_width()) // 2
        if self._anchor == "bottom":
            y = h - sprite.get_height() - 20
        elif self._anchor == "top":
            y = 20
        else:
            y = (h - sprite.get_height()) // 2
        surface.blit(sprite, (x, y))


# ── Procedural placeholder: "Sleeping cat" until real sprites land ─────────


class SleepingCatPlaceholderScene:
    """Tiny procedurally-drawn cat curled up on a windowsill, breathing slowly.

    Pure pygame primitives — no sprite assets needed. Serves as a working
    'cat' scene users can pick today; replace with a real CC0 sprite later
    by adding src/lumi/ui/face/assets/sprites/sleeping-cat/ and switching the
    SCENES['cat'] entry to SpriteLoopScene('sleeping-cat').
    """

    _BG_TOP = (28, 36, 64)
    _BG_BOT = (12, 16, 32)
    _CAT_BODY = (255, 184, 130)        # warm peachy ginger
    _CAT_STRIPE = (210, 130, 80)
    _CAT_EAR = (235, 160, 110)

    def render(self, surface: object, tick: int, w: int, h: int) -> None:
        import pygame  # noqa: PLC0415

        # Cozy gradient backdrop
        for y in range(h):
            t = y / max(h - 1, 1)
            r = int(self._BG_TOP[0] * (1 - t) + self._BG_BOT[0] * t)
            g = int(self._BG_TOP[1] * (1 - t) + self._BG_BOT[1] * t)
            b = int(self._BG_TOP[2] * (1 - t) + self._BG_BOT[2] * t)
            pygame.draw.line(surface, (r, g, b), (0, y), (w, y))

        # A few drifting stars
        for i in range(8):
            sx = int((i * 73 + tick // 6) % w)
            sy = int((i * 41) % (h // 2))
            pygame.draw.circle(surface, (220, 220, 240), (sx, sy), 1)

        # Windowsill — a flat band
        sill_y = int(h * 0.78)
        pygame.draw.rect(surface, (40, 30, 24), (0, sill_y, w, h - sill_y))

        # Cat — breathing ellipse on the sill
        breath = int(2 * math.sin(tick / 28))
        cx = w // 2
        cy = sill_y - 28 + breath
        body_w = 80
        body_h = 38

        # Body
        pygame.draw.ellipse(surface, self._CAT_BODY,
                             (cx - body_w // 2, cy - body_h // 2, body_w, body_h))
        # Stripes
        for i in range(-1, 2):
            ex = cx + i * 18
            pygame.draw.ellipse(surface, self._CAT_STRIPE,
                                 (ex - 4, cy - body_h // 2 + 2, 8, body_h - 4))
        # Head (a small circle to the left so it looks curled up)
        head_x = cx - body_w // 2 + 16
        head_y = cy - 6
        pygame.draw.circle(surface, self._CAT_BODY, (head_x, head_y), 16)
        # Ears
        pygame.draw.polygon(surface, self._CAT_EAR,
                             [(head_x - 12, head_y - 8), (head_x - 4, head_y - 16), (head_x - 4, head_y - 4)])
        pygame.draw.polygon(surface, self._CAT_EAR,
                             [(head_x + 4, head_y - 4), (head_x + 4, head_y - 16), (head_x + 12, head_y - 8)])
        # Closed eyes (two small arcs)
        pygame.draw.line(surface, (60, 30, 20), (head_x - 6, head_y - 1), (head_x - 1, head_y - 1), 2)
        pygame.draw.line(surface, (60, 30, 20), (head_x + 2, head_y - 1), (head_x + 7, head_y - 1), 2)

        # A small "Z" floating up to suggest sleep, every ~3s
        if (tick // 5) % 20 < 6:
            zfont = pygame.font.Font(None, 18)
            phase = (tick // 5) % 20
            z_alpha = max(0, 255 - phase * 30)
            z_img = zfont.render("z", True, (220, 220, 255))
            z_img.set_alpha(z_alpha)
            surface.blit(z_img, (head_x + 12, head_y - 20 - phase))


# ── Registry ────────────────────────────────────────────────────────────────


SCENES: dict[str, Any] = {
    "none":  type("_NoScene", (), {"render": lambda self, s, t, w, h: None}),
    "rain":  RainScene,
    "snow":  SnowScene,
    "cat":   SleepingCatPlaceholderScene,
}


def make_scene(name: str) -> IdleScene | None:
    """Build a scene by name. None / 'none' / unknown → None (just the face)."""
    if not name or name == "none":
        return None
    cls = SCENES.get(name.lower())
    return cls() if cls else None
