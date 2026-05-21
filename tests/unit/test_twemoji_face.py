"""Tests for the Twemoji asset loader behind the vector face."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch


from lumi.runtime.state_machine import LumiState
from lumi.ui.face import twemoji as tw
from lumi.ui.face.twemoji import (
    _BUNDLED_DIR,
    cache_dir,
    codepoint_for,
    ensure_cached,
)


def test_codepoint_per_state() -> None:
    assert codepoint_for(LumiState.IDLE) == "1f60d"      # 😍
    assert codepoint_for(LumiState.LISTEN) == "1f917"    # 🤗
    assert codepoint_for(LumiState.THINK) == "1f914"     # 🤔
    assert codepoint_for(LumiState.SPEAK) == "1f604"     # 😄


def test_cache_dir_under_models(tmp_path: Path) -> None:
    assert cache_dir(tmp_path) == tmp_path / "twemoji"


# ── Bundled-first behaviour (audit #7) ──────────────────────────────────────


def test_all_four_default_size_pngs_are_bundled() -> None:
    """The wheel must ship the four state emojis at the default size — that's
    what makes first-boot offline-clean."""
    for cp in ("1f60d", "1f917", "1f914", "1f604"):
        bundled = _BUNDLED_DIR / f"{cp}_320.png"
        assert bundled.exists(), f"missing bundled asset: {bundled}"
        # Validate it's actually a PNG.
        assert bundled.read_bytes()[:4] == b"\x89PNG", f"not a PNG: {bundled}"


def test_ensure_cached_uses_bundled_assets_without_network(tmp_path: Path) -> None:
    """At the default size, ensure_cached must NEVER hit the network.
    httpx.get raising would fail this test if the bundled path was bypassed."""
    with patch("httpx.get", side_effect=AssertionError("network must not be touched")):
        result = ensure_cached(tmp_path, size=320)

    assert set(result.keys()) == set(LumiState)
    # All returned paths come from the bundle, not the per-user cache dir.
    for path in result.values():
        assert _BUNDLED_DIR in path.parents


def test_ensure_cached_falls_back_to_network_for_unbundled_size(tmp_path: Path) -> None:
    """Non-default sizes aren't pre-rasterized; we still go to the CDN."""
    fake_resp = MagicMock()
    fake_resp.content = b"\x89PNG" + b"fake"
    fake_resp.raise_for_status.return_value = None
    with patch("httpx.get", return_value=fake_resp) as mock_get:
        result = ensure_cached(tmp_path, size=128)        # not in bundle

    assert set(result.keys()) == set(LumiState)
    # All four were fetched, written into the user cache dir.
    assert mock_get.call_count == 4
    for path in result.values():
        assert path.parent == cache_dir(tmp_path)
        assert "_128.png" in path.name


def test_ensure_cached_uses_user_cache_before_network(tmp_path: Path) -> None:
    """If a previous run cached a custom-size PNG, the second call must NOT
    re-fetch it."""
    fake_resp = MagicMock()
    fake_resp.content = b"\x89PNG" + b"ok"
    fake_resp.raise_for_status.return_value = None
    with patch("httpx.get", return_value=fake_resp) as mock_get:
        ensure_cached(tmp_path, size=128)
        first = mock_get.call_count
        ensure_cached(tmp_path, size=128)        # second call
        second = mock_get.call_count

    assert first == 4
    assert second == first


def test_ensure_cached_rejects_non_png_response(tmp_path: Path) -> None:
    """If wsrv.nl returns HTML or junk for an unbundled size, we don't cache."""
    fake_resp = MagicMock()
    fake_resp.content = b"<html>error</html>"
    fake_resp.raise_for_status.return_value = None
    with patch("httpx.get", return_value=fake_resp):
        result = ensure_cached(tmp_path, size=128)
    assert result == {}


def test_ensure_cached_omits_failed_states_at_unbundled_size(tmp_path: Path) -> None:
    """Network failure on one codepoint must not block the others, but the
    default size still falls back to the bundle so this only matters for
    custom sizes."""
    fake_ok = MagicMock()
    fake_ok.content = b"\x89PNG" + b"ok"
    fake_ok.raise_for_status.return_value = None

    call_count = {"n": 0}
    def side_effect(*_args, **_kwargs):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise RuntimeError("network down")
        return fake_ok

    with patch("httpx.get", side_effect=side_effect):
        result = ensure_cached(tmp_path, size=128)

    assert len(result) == 3            # one missing
    assert LumiState.IDLE in result


def test_cdn_url_pins_a_specific_twemoji_version() -> None:
    """`twemoji@latest` is a moving target that can silently change
    asset paths. Make sure we pin a concrete tag."""
    assert "@latest" not in tw._CDN_URL
    assert "twemoji@" in tw._CDN_URL
