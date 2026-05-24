"""Render the procedural SleepingCatPlaceholderScene into PNG frames.

Lumi's V1 ships a "cat" idle scene drawn at runtime with pygame
primitives. We want the sleeping-cat to flow through the real
`SpriteLoopScene` pipeline instead (so the upload UI we ship in the
same PR can drop in different packs), but we don't have proper
pixel-art assets in-house yet — Figma faces are a separate workstream.

This script bridges the gap: it runs the placeholder scene at a sample
of tick values, captures each rendered surface to PNG, and writes a
manifest.json. The frames are committed as a bundled pack at
`src/lumi/ui/face/assets/sprites/sleeping-cat/`. Future contributors
(or the user with Figma in hand) can replace these by uploading via
`/settings/sprites`.

Re-run after touching the placeholder code:
    uv run python scripts/render_sleeping_cat_frames.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

# Headless pygame: no window, no display required.
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
import pygame  # noqa: E402

from lumi.ui.face.idle_scenes import SleepingCatPlaceholderScene  # noqa: E402

# The base size matches what the chrome leaves for the idle area on the
# 480×320 Waveshare display: full width below the 44px chrome bar.
_FRAME_W = 480
_FRAME_H = 276
_N_FRAMES = 24            # ~4 seconds of breathing at 6fps
_TICKS_PER_FRAME = 5      # 30 Hz render loop / 6 fps target

_OUT_DIR = Path(__file__).resolve().parent.parent / "src" / "lumi" / "ui" / "face" / "assets" / "sprites" / "sleeping-cat"


def main() -> int:
    pygame.init()
    try:
        pygame.font.init()
        scene = SleepingCatPlaceholderScene()
        _OUT_DIR.mkdir(parents=True, exist_ok=True)

        # Wipe any prior frames so a re-run is deterministic.
        for old in _OUT_DIR.glob("frame_*.png"):
            old.unlink()

        for idx in range(_N_FRAMES):
            surface = pygame.Surface((_FRAME_W, _FRAME_H))
            scene.render(surface, idx * _TICKS_PER_FRAME, _FRAME_W, _FRAME_H)
            path = _OUT_DIR / f"frame_{idx:03d}.png"
            pygame.image.save(surface, str(path))

        manifest = {
            "name": "sleeping-cat",
            "fps": 6,
            "scale": 1,
            "anchor": "center",
            "background": "#0a0e1e",
            "source": "rendered from SleepingCatPlaceholderScene",
            "license": "Lumi-internal (replace freely via /settings/sprites)",
            "frames": _N_FRAMES,
        }
        (_OUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2))

        print(f"wrote {_N_FRAMES} frames + manifest to {_OUT_DIR}")
    finally:
        pygame.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
