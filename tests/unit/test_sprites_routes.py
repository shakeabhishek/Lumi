"""Integration tests for /settings/sprites — upload, list, delete via HTTP.

The validation rules are tested at the function level in
test_sprite_upload.py. This file confirms the FastAPI plumbing is
correct: CSRF enforced, multipart upload handled, list reflects on-disk
state, delete actually wipes, idle_scene falls back when the active
pack is removed.
"""

from __future__ import annotations

import io
import struct
import tempfile
import zipfile
import zlib
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from lumi.ui.web.app import create_app


def _tiny_png() -> bytes:
    sig = b"\x89PNG\r\n\x1a\n"
    def _chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))
    ihdr = struct.pack(">IIBBBBB", 4, 4, 8, 6, 0, 0, 0)
    idat = zlib.compress(b"\x00" + b"\x00" * 16)
    return sig + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", idat) + _chunk(b"IEND", b"")


def _pack_zip(frames: int = 2, manifest: dict | None = None) -> bytes:
    import json  # noqa: PLC0415
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for i in range(1, frames + 1):
            zf.writestr(f"frame_{i:03d}.png", _tiny_png())
        if manifest is not None:
            zf.writestr("manifest.json", json.dumps(manifest))
    return buf.getvalue()


@pytest.fixture(autouse=True)
def _isolate_openclaw():
    # Sprites routes don't touch openclaw, but the app factory still
    # builds the middleware stack; stub the gateway restart so an
    # unrelated test pollution can't slow us down.
    with patch("lumi.skills.openclaw_operator._restart_gateway", return_value=True):
        yield


@pytest.fixture
def client():
    d = Path(tempfile.mkdtemp(prefix="lumi_sprites_"))
    c = TestClient(create_app(d))
    c.get("/")          # warm CSRF cookie
    return c, d


def _csrf(c: TestClient) -> str:
    return c.cookies.get("csrf_token", "")


# ── GET /settings/sprites ──────────────────────────────────────────────────


def test_sprites_page_renders_with_bundled_pack_listed(client) -> None:
    c, _ = client
    r = c.get("/settings/sprites")
    assert r.status_code == 200
    # The bundled "cat" pack ships with Lumi and should always appear.
    assert "cat" in r.text
    assert "bundled" in r.text.lower()


def test_sprites_page_shows_uploaded_packs(client) -> None:
    c, data_dir = client
    # Stash a user pack directly so we don't depend on the upload path.
    pack = data_dir / "sprites" / "my-fox"
    pack.mkdir(parents=True)
    (pack / "frame_001.png").write_bytes(_tiny_png())

    r = c.get("/settings/sprites")
    assert r.status_code == 200
    assert "my-fox" in r.text
    assert "uploaded" in r.text.lower()


# ── POST /settings/sprites/upload ──────────────────────────────────────────


def test_upload_requires_csrf(client) -> None:
    c, _ = client
    # No CSRF token → 403 from the middleware before the route runs.
    r = c.post(
        "/settings/sprites/upload",
        data={"pack_name": "anything"},
        files={"zipfile": ("p.zip", _pack_zip(2), "application/zip")},
    )
    assert r.status_code == 403


def test_upload_happy_path_creates_pack_and_lists_it(client) -> None:
    c, data_dir = client
    csrf = _csrf(c)
    r = c.post(
        "/settings/sprites/upload",
        data={"pack_name": "blinking-bird", "csrf_token": csrf},
        files={"zipfile": ("p.zip", _pack_zip(3), "application/zip")},
        headers={"X-CSRF-Token": csrf},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "ok=blinking-bird" in r.headers["location"]
    # And the pack landed on disk
    pack = data_dir / "sprites" / "blinking-bird"
    assert pack.is_dir()
    assert (pack / "frame_001.png").exists()


def test_upload_bad_zip_redirects_with_error(client) -> None:
    c, _ = client
    csrf = _csrf(c)
    r = c.post(
        "/settings/sprites/upload",
        data={"pack_name": "broken", "csrf_token": csrf},
        files={"zipfile": ("p.zip", b"not a zip", "application/zip")},
        headers={"X-CSRF-Token": csrf},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "err=" in r.headers["location"]


def test_upload_overrides_bundled_pack_with_same_name(client) -> None:
    """A user can replace 'cat' with their own art by uploading under the
    same name — list_sprite_packs then reports source=user for it."""
    c, data_dir = client
    csrf = _csrf(c)
    c.post(
        "/settings/sprites/upload",
        data={"pack_name": "cat", "csrf_token": csrf},
        files={"zipfile": ("c.zip", _pack_zip(2), "application/zip")},
        headers={"X-CSRF-Token": csrf},
        follow_redirects=False,
    )
    r = c.get("/settings/sprites")
    # Both bundled and uploaded "cat" can't coexist in the listing —
    # the user one wins, so the row shows "uploaded" not "bundled".
    assert (data_dir / "sprites" / "cat" / "frame_001.png").exists()
    # The sprites page shows the user override
    lower = r.text.lower()
    assert "cat" in lower and "uploaded" in lower


# ── POST /settings/sprites/delete ──────────────────────────────────────────


def test_delete_removes_user_pack(client) -> None:
    c, data_dir = client
    pack = data_dir / "sprites" / "doomed"
    pack.mkdir(parents=True)
    (pack / "frame_001.png").write_bytes(_tiny_png())

    csrf = _csrf(c)
    r = c.post(
        "/settings/sprites/delete",
        data={"pack_name": "doomed", "csrf_token": csrf},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "deleted=doomed" in r.headers["location"]
    assert not pack.exists()


def test_deleting_active_pack_falls_back_idle_scene_to_none(client) -> None:
    """If the user's idle_scene == the pack they're deleting, the renderer
    would otherwise try to load a vanished folder. Settings should
    drop back to 'none' as part of the same request."""
    from lumi.ui.web.persistence import UserSettings, save_settings  # noqa: PLC0415
    c, data_dir = client

    pack = data_dir / "sprites" / "doomed"
    pack.mkdir(parents=True)
    (pack / "frame_001.png").write_bytes(_tiny_png())

    s = UserSettings(idle_scene="doomed")
    save_settings(data_dir, s)

    csrf = _csrf(c)
    c.post(
        "/settings/sprites/delete",
        data={"pack_name": "doomed", "csrf_token": csrf},
        follow_redirects=False,
    )

    from lumi.ui.web.persistence import load_settings  # noqa: PLC0415
    assert load_settings(data_dir).idle_scene == "none"


def test_delete_bundled_pack_is_a_no_op_with_clear_error(client) -> None:
    """The 'cat' bundled pack lives in the wheel — deleting it from
    /settings/sprites would do nothing useful (it'd come back on
    reinstall). The route should reject quietly."""
    c, data_dir = client
    csrf = _csrf(c)
    r = c.post(
        "/settings/sprites/delete",
        data={"pack_name": "cat", "csrf_token": csrf},
        follow_redirects=False,
    )
    assert r.status_code == 303
    # No user pack named "cat" exists in data_dir, so delete reports
    # "not found" — bundled pack is untouched.
    assert "err=" in r.headers["location"]
    # And it's still listed (bundled source remains).
    r2 = c.get("/settings/sprites")
    assert "cat" in r2.text
