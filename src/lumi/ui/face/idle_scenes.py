"""Sprite-pack metadata + resolution.

Before the React device-display pivot (2026-05-24) this module also
held pygame-based scene classes (RainScene, SnowScene,
SleepingCatPlaceholderScene, SpriteLoopScene). All four are now dead
— the React `SpriteSceneFace` component fetches frames over HTTP, and
the rain/snow/cat-placeholder were procedural pygame drawings we no
longer need. What's left here is the lookup layer the FastAPI
sprite-serving route (`/device-display/sprite/<pack>/<file>`) and the
`/settings/sprites` upload UI both depend on.

A sprite pack is a directory under either:
  * data_dir/sprites/<name>/   (user-uploaded — overrides bundled)
  * src/lumi/ui/face/assets/sprites/<bundled-name>/

…containing `frame_NNN.png` files + an optional `manifest.json`.
User uploads with the same logical name as a bundled pack win.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

# Bundled assets live in the wheel alongside this file.
_SPRITES_DIR = Path(__file__).parent / "assets" / "sprites"

# Logical pack name → bundled directory name. Decouples the dropdown
# label / API key (`cat`) from the on-disk folder (`sleeping-cat`) so
# we can keep a stable URL even if the asset is rebranded.
_BUNDLED_DIR_FOR: dict[str, str] = {
    "cat": "sleeping-cat",
}

BUNDLED_SPRITE_PACKS: tuple[str, ...] = tuple(_BUNDLED_DIR_FOR.keys())


def list_sprite_packs(data_dir: Path | None = None) -> list[dict[str, str]]:
    """Enumerate every sprite pack the device-display UI can offer.

    Each entry: `{"name": <key>, "source": "bundled" | "user",
    "label": <display>}`. User uploads override bundled packs with the
    same name — only one entry per name is returned.
    """
    packs: dict[str, dict[str, str]] = {}
    for key in BUNDLED_SPRITE_PACKS:
        dirname = _BUNDLED_DIR_FOR.get(key, key)
        if (_SPRITES_DIR / dirname).is_dir():
            packs[key] = {
                "name": key,
                "source": "bundled",
                "label": key.replace("-", " ").title(),
            }
    if data_dir is not None:
        user_root = data_dir / "sprites"
        if user_root.is_dir():
            for sub in sorted(user_root.iterdir()):
                if sub.is_dir() and any(sub.glob("frame_*.png")):
                    packs[sub.name] = {
                        "name": sub.name,
                        "source": "user",
                        "label": sub.name.replace("-", " ").title(),
                    }
    return list(packs.values())


def _resolve_sprite_path(name: str, data_dir: Path | None) -> Path | None:
    """Return the directory holding `frame_*.png` files for `name`, or
    None. Checks the user dir first so uploaded packs override bundled."""
    if data_dir is not None:
        user_path = data_dir / "sprites" / name
        if user_path.is_dir() and any(user_path.glob("frame_*.png")):
            return user_path
    bundled_dirname = _BUNDLED_DIR_FOR.get(name, name)
    bundled_path = _SPRITES_DIR / bundled_dirname
    if bundled_path.is_dir() and any(bundled_path.glob("frame_*.png")):
        return bundled_path
    return None


def make_scene(name: str, data_dir: Path | None = None) -> dict[str, Any] | None:
    """Return a small descriptor for the named sprite pack — used by
    the FastAPI device-display route to tell the React client which
    folder to fetch frames from. Returns None for "none" / unknown.
    """
    if not name or name == "none":
        return None
    key = name.lower()
    path = _resolve_sprite_path(key, data_dir)
    if path is None:
        return None
    return {
        "name": key,
        "path": str(path),
    }
