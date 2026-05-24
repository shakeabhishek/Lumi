"""Tests for sprite-pack upload validation and extraction.

The validation rules are documented in src/lumi/ui/face/sprite_upload.py.
This file locks each rule down with a positive and a negative case so a
hostile or malformed pack can never end up on disk.
"""

from __future__ import annotations

import io
import json
import struct
import zipfile
import zlib
from pathlib import Path

from lumi.ui.face.sprite_upload import (
    delete_user_pack,
    normalize_pack_name,
    validate_and_extract_zip,
)


# ── Test helpers ───────────────────────────────────────────────────────────


def _tiny_png(width: int = 4, height: int = 4) -> bytes:
    """A valid 4×4 PNG (transparent). Real binary; not a stub. The
    PIL-free approach keeps the test fixtures self-contained."""
    sig = b"\x89PNG\r\n\x1a\n"

    def _chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data)
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)  # RGBA
    raw = b"".join(b"\x00" + b"\x00" * (width * 4) for _ in range(height))
    idat = zlib.compress(raw)
    return sig + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", idat) + _chunk(b"IEND", b"")


def _zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


# ── normalize_pack_name ────────────────────────────────────────────────────


def test_normalize_drops_unsafe_chars() -> None:
    assert normalize_pack_name("Sleeping Cat!") == "sleeping-cat"
    assert normalize_pack_name("  my//pack  ") == "my-pack"
    assert normalize_pack_name("../escape") == "escape"   # path-traversal stripped


def test_normalize_empty_input_returns_empty() -> None:
    assert normalize_pack_name("") == ""
    assert normalize_pack_name("...") == ""
    assert normalize_pack_name("@#$%") == ""


def test_normalize_caps_long_names() -> None:
    out = normalize_pack_name("a" * 200)
    assert len(out) <= 48


# ── Happy path ─────────────────────────────────────────────────────────────


def test_upload_minimal_pack_succeeds(tmp_path: Path) -> None:
    png = _tiny_png()
    zip_bytes = _zip({
        "frame_001.png": png,
        "frame_002.png": png,
        "frame_003.png": png,
    })

    result = validate_and_extract_zip(zip_bytes, "sleepy-fox", tmp_path)

    assert result.ok, result.error
    assert result.pack_name == "sleepy-fox"
    assert result.frames == 3
    pack_dir = tmp_path / "sleepy-fox"
    assert pack_dir.is_dir()
    assert sorted(p.name for p in pack_dir.iterdir()) == [
        "frame_001.png", "frame_002.png", "frame_003.png",
    ]


def test_upload_with_manifest_keeps_it(tmp_path: Path) -> None:
    png = _tiny_png()
    manifest = json.dumps({"fps": 8, "scale": 2, "background": "#112233"})
    zip_bytes = _zip({
        "frame_001.png": png,
        "frame_002.png": png,
        "manifest.json": manifest.encode(),
    })

    result = validate_and_extract_zip(zip_bytes, "blinking-bird", tmp_path)

    assert result.ok
    saved = json.loads((tmp_path / "blinking-bird" / "manifest.json").read_text())
    assert saved["fps"] == 8


# ── Validation rejections — each rule has a dedicated test ────────────────


def test_rejects_non_zip_input(tmp_path: Path) -> None:
    result = validate_and_extract_zip(b"not a zip", "pack", tmp_path)
    assert not result.ok
    assert "zip" in result.error.lower()


def test_rejects_empty_or_unnameable_pack_name(tmp_path: Path) -> None:
    """Input that normalises to nothing — pure punctuation, empty string —
    is rejected. The validator is otherwise lenient: it cleans up
    user-friendly input ('Has Spaces' → 'has-spaces') rather than yelling."""
    png = _tiny_png()
    zip_bytes = _zip({"frame_001.png": png})

    for bad in ("", "...", "@#$%", "/", "----"):
        result = validate_and_extract_zip(zip_bytes, bad, tmp_path)
        assert not result.ok, f"expected rejection for name {bad!r}"
        assert "name" in result.error.lower()


def test_accepts_and_normalises_human_friendly_names(tmp_path: Path) -> None:
    """The validator should NOT yell at obvious typos. It cleans up and
    proceeds, but the final pack ends up at a SAFE name inside sprites_root."""
    png = _tiny_png()
    zip_bytes = _zip({"frame_001.png": png})

    for raw, expected in [
        ("Has Spaces", "has-spaces"),
        ("../escape", "escape"),                 # path-traversal cleaned away
        ("A" * 200, "a" * 48),                   # long input truncated
        ("My/Pack/123", "my-pack-123"),
    ]:
        result = validate_and_extract_zip(zip_bytes, raw, tmp_path)
        assert result.ok, f"unexpected rejection for {raw!r}: {result.error}"
        assert result.pack_name == expected
        # The pack landed strictly inside sprites_root.
        final = tmp_path / result.pack_name
        assert final.is_dir()
        assert str(final.resolve()).startswith(str(tmp_path.resolve()))
        # Cleanup so we don't pollute later assertions in the same tmp_path.
        for f in final.iterdir():
            f.unlink()
        final.rmdir()


def test_rejects_path_traversal_in_zip_entries(tmp_path: Path) -> None:
    png = _tiny_png()
    zip_bytes = _zip({
        "frame_001.png": png,
        "../../../etc/passwd": b"oops",
    })
    result = validate_and_extract_zip(zip_bytes, "evil", tmp_path)
    assert not result.ok
    assert "unsafe path" in result.error.lower() or "passwd" in result.error.lower()


def test_rejects_nested_subfolders_in_zip(tmp_path: Path) -> None:
    """The pack format is flat — frames at the root, no `frames/foo.png`."""
    png = _tiny_png()
    zip_bytes = _zip({
        "frame_001.png": png,
        "subfolder/frame_002.png": png,
    })
    result = validate_and_extract_zip(zip_bytes, "nested", tmp_path)
    assert not result.ok


def test_rejects_non_png_in_zip(tmp_path: Path) -> None:
    """Any file not matching frame_NNN.png or manifest.json is rejected."""
    png = _tiny_png()
    zip_bytes = _zip({
        "frame_001.png": png,
        "README.md": b"# this is fine in a normal zip but not here",
    })
    result = validate_and_extract_zip(zip_bytes, "with-readme", tmp_path)
    assert not result.ok
    assert "unrecognised" in result.error.lower() or "README" in result.error


def test_rejects_fake_png_with_wrong_magic_bytes(tmp_path: Path) -> None:
    """Renaming a JPG to .png shouldn't get past — magic byte check."""
    zip_bytes = _zip({"frame_001.png": b"\xff\xd8\xff\xe0not actually a png"})
    result = validate_and_extract_zip(zip_bytes, "fake", tmp_path)
    assert not result.ok
    assert "png" in result.error.lower()


def test_rejects_zip_with_no_frames(tmp_path: Path) -> None:
    zip_bytes = _zip({"manifest.json": b'{"fps":6}'})
    result = validate_and_extract_zip(zip_bytes, "empty", tmp_path)
    assert not result.ok
    assert "frame" in result.error.lower()


def test_rejects_empty_zip(tmp_path: Path) -> None:
    zip_bytes = _zip({})
    result = validate_and_extract_zip(zip_bytes, "void", tmp_path)
    assert not result.ok


def test_rejects_oversized_individual_frame(tmp_path: Path) -> None:
    """No single frame should be larger than 256 KB."""
    huge = b"\x89PNG\r\n\x1a\n" + b"x" * (300 * 1024)
    zip_bytes = _zip({"frame_001.png": huge})
    result = validate_and_extract_zip(zip_bytes, "bloated", tmp_path)
    assert not result.ok
    assert "large" in result.error.lower()


def test_rejects_malformed_manifest_json(tmp_path: Path) -> None:
    png = _tiny_png()
    zip_bytes = _zip({
        "frame_001.png": png,
        "manifest.json": b"{not json,",
    })
    result = validate_and_extract_zip(zip_bytes, "broken-manifest", tmp_path)
    assert not result.ok
    assert "json" in result.error.lower()


def test_rejects_out_of_range_manifest_values(tmp_path: Path) -> None:
    """A hostile manifest can't crash the renderer with fps=0 (div-by-zero)
    or scale=999 (megabytes of frame buffer per blit)."""
    png = _tiny_png()
    for bad in ('{"fps": 0}', '{"fps": 999}', '{"scale": 0}', '{"scale": 99}'):
        zip_bytes = _zip({
            "frame_001.png": png,
            "manifest.json": bad.encode(),
        })
        result = validate_and_extract_zip(zip_bytes, "hostile", tmp_path)
        assert not result.ok, f"expected rejection for manifest {bad!r}"


# ── Atomicity ──────────────────────────────────────────────────────────────


def test_upload_replaces_existing_pack_atomically(tmp_path: Path) -> None:
    """Re-uploading under the same name swaps the contents — no leftover
    frames from the old pack mixed in with the new."""
    png = _tiny_png()

    # First upload: 3 frames
    first = _zip({f"frame_{i:03d}.png": png for i in range(1, 4)})
    r1 = validate_and_extract_zip(first, "loop", tmp_path)
    assert r1.ok

    # Second upload under the same name: only 2 frames
    second = _zip({f"frame_{i:03d}.png": png for i in range(1, 3)})
    r2 = validate_and_extract_zip(second, "loop", tmp_path)
    assert r2.ok

    pack = tmp_path / "loop"
    assert sorted(p.name for p in pack.iterdir()) == ["frame_001.png", "frame_002.png"]


def test_failed_extract_leaves_no_temp_residue(tmp_path: Path) -> None:
    """If validation fails partway, no half-written tmp dir lingers."""
    validate_and_extract_zip(b"bad", "leftover", tmp_path)
    assert list(tmp_path.glob(".*.tmp")) == []
    assert list(tmp_path.glob(".*")) == []


# ── delete_user_pack ───────────────────────────────────────────────────────


def test_delete_existing_pack(tmp_path: Path) -> None:
    pack = tmp_path / "kitty"
    pack.mkdir()
    (pack / "frame_001.png").write_bytes(_tiny_png())
    ok, err = delete_user_pack("kitty", tmp_path)
    assert ok, err
    assert not pack.exists()


def test_delete_refuses_traversal(tmp_path: Path) -> None:
    """Cannot escape the sprites_root via a clever name."""
    victim = tmp_path.parent / "do_not_delete_me"
    victim.mkdir(exist_ok=True)
    try:
        ok, _ = delete_user_pack("../" + victim.name, tmp_path)
        assert not ok
        assert victim.exists()
    finally:
        victim.rmdir()


def test_delete_missing_pack_is_friendly(tmp_path: Path) -> None:
    ok, err = delete_user_pack("never-existed", tmp_path)
    assert not ok
    assert "not found" in err.lower()
