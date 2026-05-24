"""Validation + extraction for user-uploaded sprite packs.

A sprite pack is a directory with N PNG frames named `frame_NNN.png`
(zero-padded so they sort) and an optional `manifest.json`. Users upload
either:
  - a ZIP archive containing those files at the top level, OR
  - one PNG at a time (rare; ZIP is the main path).

This module owns the rules. Routes thread input through here so the
upload code path can be tested without spinning up FastAPI.
"""

from __future__ import annotations

import json
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

# Caps — protect the device from a hostile or accidental large upload.
_MAX_FRAMES = 240                  # ~40 sec at 6 fps
_MAX_FRAME_BYTES = 256 * 1024      # 256 KB per PNG — plenty for pixel art
_MAX_PACK_BYTES = 8 * 1024 * 1024  # 8 MB total per pack
_MAX_PACK_NAME_LEN = 48
_PACK_NAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,46}[a-z0-9])?$")  # safe folder name
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_FRAME_NAME_RE = re.compile(r"^frame_\d{3,4}\.png$")


@dataclass
class UploadResult:
    ok: bool
    pack_name: str = ""
    frames: int = 0
    bytes: int = 0
    error: str = ""


def normalize_pack_name(raw: str) -> str:
    """Lowercase + collapse whitespace/punct to dashes. Returns empty if
    nothing survives the cleanup; caller treats empty as invalid."""
    if not raw:
        return ""
    lowered = raw.strip().lower()
    cleaned = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
    if len(cleaned) > _MAX_PACK_NAME_LEN:
        cleaned = cleaned[:_MAX_PACK_NAME_LEN].rstrip("-")
    return cleaned


def _is_safe_zip_member(name: str) -> bool:
    """Reject path-traversal and absolute paths in ZIP entries."""
    if not name or name.startswith("/") or ".." in Path(name).parts:
        return False
    # Refuse anything other than top-level files — packs are flat.
    if "/" in name.rstrip("/") and not name.endswith("/"):
        # `frames/foo.png` and similar nested layouts confuse the loader;
        # frames have to live at the pack root.
        return False
    return True


def validate_and_extract_zip(
    zip_bytes: bytes,
    desired_name: str,
    sprites_root: Path,
) -> UploadResult:
    """Validate `zip_bytes` and write a clean pack to
    `sprites_root / <pack_name>/`. Atomic-ish: writes to a temp
    sibling first, then renames into place, so a partial extract
    can't leave a half-pack live.
    """
    pack_name = normalize_pack_name(desired_name)
    if not pack_name or not _PACK_NAME_RE.match(pack_name):
        return UploadResult(False, error="invalid pack name (lowercase alphanumerics + dashes, 1-48 chars)")

    if len(zip_bytes) > _MAX_PACK_BYTES:
        return UploadResult(False, error=f"upload too large (>{_MAX_PACK_BYTES // (1024*1024)} MB)")

    try:
        zf = zipfile.ZipFile(__import__("io").BytesIO(zip_bytes))
    except zipfile.BadZipFile:
        return UploadResult(False, error="not a valid ZIP archive")

    members = [m for m in zf.namelist() if not m.endswith("/")]
    if not members:
        return UploadResult(False, error="ZIP is empty")

    frame_names: list[str] = []
    manifest_bytes: bytes | None = None
    total_bytes = 0

    for name in members:
        if not _is_safe_zip_member(name):
            return UploadResult(False, error=f"unsafe path in ZIP: {name!r}")
        # Strip any leading directory component — accept "frame_001.png"
        # at the root or inside a single-folder ZIP (most ZIP creators
        # wrap contents in a top-level dir).
        leaf = Path(name).name
        info = zf.getinfo(name)
        if info.file_size > _MAX_FRAME_BYTES:
            return UploadResult(False, error=f"{leaf}: file too large ({info.file_size} > {_MAX_FRAME_BYTES} bytes)")
        total_bytes += info.file_size
        if total_bytes > _MAX_PACK_BYTES:
            return UploadResult(False, error="pack exceeds total size cap")

        if leaf == "manifest.json":
            manifest_bytes = zf.read(name)
            continue
        if _FRAME_NAME_RE.match(leaf):
            data = zf.read(name)
            if not data.startswith(_PNG_MAGIC):
                return UploadResult(False, error=f"{leaf}: not a valid PNG (magic bytes mismatch)")
            frame_names.append(leaf)
            continue
        # Anything else is rejected — keeps the pack format clean.
        return UploadResult(False, error=f"unrecognised file in ZIP: {leaf!r}")

    if not frame_names:
        return UploadResult(False, error="no frame_NNN.png files found in ZIP")
    if len(frame_names) > _MAX_FRAMES:
        return UploadResult(False, error=f"too many frames ({len(frame_names)} > {_MAX_FRAMES})")

    if manifest_bytes is not None:
        try:
            manifest = json.loads(manifest_bytes)
        except json.JSONDecodeError:
            return UploadResult(False, error="manifest.json is not valid JSON")
        if not isinstance(manifest, dict):
            return UploadResult(False, error="manifest.json must be an object")
        # Cap manifest values to safe ranges so a hostile manifest can't
        # crash the renderer (e.g., fps=0 div-by-zero, scale=999 OOM).
        for key, lo, hi in (("fps", 1, 60), ("scale", 1, 16)):
            if key in manifest:
                try:
                    v = int(manifest[key])
                except (TypeError, ValueError):
                    return UploadResult(False, error=f"manifest.{key} must be an integer")
                if not (lo <= v <= hi):
                    return UploadResult(False, error=f"manifest.{key} out of range ({lo}..{hi})")

    # ── Write to a temp dir then rename ─────────────────────────────────
    sprites_root.mkdir(parents=True, exist_ok=True)
    target = sprites_root / pack_name
    tmp = sprites_root / f".{pack_name}.tmp"
    if tmp.exists():
        _rmtree(tmp)
    tmp.mkdir()
    try:
        for name in sorted(members):
            leaf = Path(name).name
            (tmp / leaf).write_bytes(zf.read(name))
        if target.exists():
            _rmtree(target)
        tmp.rename(target)
    except OSError as exc:
        _rmtree(tmp)
        return UploadResult(False, error=f"write failed: {exc}")

    return UploadResult(True, pack_name=pack_name, frames=len(frame_names), bytes=total_bytes)


def delete_user_pack(name: str, sprites_root: Path) -> tuple[bool, str]:
    """Remove a previously-uploaded pack. Bundled packs aren't here so
    can't be deleted from this path — the caller checks first."""
    cleaned = normalize_pack_name(name)
    if not cleaned or not _PACK_NAME_RE.match(cleaned):
        return False, "invalid pack name"
    target = sprites_root / cleaned
    if not target.is_dir() or not str(target.resolve()).startswith(str(sprites_root.resolve())):
        return False, "pack not found"
    try:
        _rmtree(target)
    except OSError as exc:
        return False, f"delete failed: {exc}"
    return True, ""


def _rmtree(p: Path) -> None:
    """Tiny shutil.rmtree replacement so this module has zero stdlib
    imports beyond what's already at the top — keeps test surface tight."""
    if not p.exists():
        return
    if p.is_file() or p.is_symlink():
        p.unlink()
        return
    for child in p.iterdir():
        _rmtree(child)
    p.rmdir()
