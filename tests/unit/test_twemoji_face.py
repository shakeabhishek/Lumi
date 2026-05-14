"""Tests for the Twemoji asset loader behind the vector face."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from lumi.runtime.state_machine import LumiState
from lumi.ui.face.twemoji import (
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


def test_ensure_cached_writes_each_state(tmp_path: Path) -> None:
    """Mock httpx.get → ensure_cached writes a file per state and returns them."""
    fake_resp = MagicMock()
    fake_resp.content = b"\x89PNGfake"
    fake_resp.raise_for_status.return_value = None
    with patch("httpx.get", return_value=fake_resp) as mock_get:
        result = ensure_cached(tmp_path)

    assert set(result.keys()) == set(LumiState)
    for state in LumiState:
        assert result[state].exists()
        assert result[state].read_bytes() == b"\x89PNGfake"
    assert mock_get.call_count == 4


def test_ensure_cached_skips_existing(tmp_path: Path) -> None:
    """A second call shouldn't re-fetch files that are already on disk."""
    fake_resp = MagicMock()
    fake_resp.content = b"\x89PNGfake"
    fake_resp.raise_for_status.return_value = None
    with patch("httpx.get", return_value=fake_resp) as mock_get:
        ensure_cached(tmp_path)
        first_calls = mock_get.call_count
        ensure_cached(tmp_path)
        second_calls = mock_get.call_count

    assert first_calls == 4
    assert second_calls == first_calls   # zero additional network calls


def test_ensure_cached_omits_failed_states(tmp_path: Path) -> None:
    """Network failure on one codepoint should not block the others."""
    fake_ok = MagicMock(); fake_ok.content = b"png"; fake_ok.raise_for_status.return_value = None

    call_count = {"n": 0}
    def side_effect(*_args, **_kwargs):
        call_count["n"] += 1
        if call_count["n"] == 2:  # second codepoint fails
            raise RuntimeError("network down")
        return fake_ok

    with patch("httpx.get", side_effect=side_effect):
        result = ensure_cached(tmp_path)

    assert len(result) == 3            # one missing
    assert LumiState.IDLE in result    # first succeeded
