"""Sprite-pack metadata + upload helpers.

The pygame face renderers (pixel/vector/terminal/chrome compositor +
the FaceEngine that drove them) lived here until the 2026-05-24 pivot
to React. The React device display (`src/lumi/ui/device_display/`)
owns face rendering now; what remains in this package is the data
layer: bundled-vs-uploaded sprite-pack resolution, the upload
validator, and the bundled `assets/sprites/` directory.
"""

from .idle_scenes import (
    BUNDLED_SPRITE_PACKS,
    list_sprite_packs,
    make_scene,
)

__all__ = ["BUNDLED_SPRITE_PACKS", "list_sprite_packs", "make_scene"]
