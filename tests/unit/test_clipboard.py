"""Tests for host_helper.clipboard — mocks subprocess so no real clipboard needed."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from lumi.host_helper.clipboard import _read_linux, _read_macos, read


def test_read_returns_string_on_success(monkeypatch: object) -> None:
    monkeypatch.setattr("sys.platform", "darwin")
    mock = MagicMock(return_value=MagicMock(returncode=0, stdout="hello world"))
    with patch("lumi.host_helper.clipboard.subprocess.run", mock):
        result = read()
    assert result == "hello world"


def test_read_returns_none_on_nonzero_exit(monkeypatch: object) -> None:
    monkeypatch.setattr("sys.platform", "darwin")
    mock = MagicMock(return_value=MagicMock(returncode=1, stdout=""))
    with patch("lumi.host_helper.clipboard.subprocess.run", mock):
        result = read()
    assert result is None


def test_read_returns_none_on_exception(monkeypatch: object) -> None:
    monkeypatch.setattr("sys.platform", "darwin")
    with patch("lumi.host_helper.clipboard.subprocess.run", side_effect=OSError("no pbpaste")):
        result = read()
    assert result is None


def test_read_macos_calls_pbpaste() -> None:
    mock = MagicMock(return_value=MagicMock(returncode=0, stdout="clipboard text"))
    with patch("lumi.host_helper.clipboard.subprocess.run", mock) as m:
        result = _read_macos()
    assert result == "clipboard text"
    m.assert_called_once()
    assert m.call_args[0][0] == ["pbpaste"]


def test_read_linux_tries_xclip_first() -> None:
    mock = MagicMock(return_value=MagicMock(returncode=0, stdout="linux clipboard"))
    with patch("lumi.host_helper.clipboard.subprocess.run", mock) as m:
        result = _read_linux()
    assert result == "linux clipboard"
    first_cmd = m.call_args_list[0][0][0]
    assert "xclip" in first_cmd


def test_read_linux_falls_back_to_xsel() -> None:
    def _side_effect(cmd: list, **_: object) -> MagicMock:
        if "xclip" in cmd:
            raise FileNotFoundError
        return MagicMock(returncode=0, stdout="xsel text")

    with patch("lumi.host_helper.clipboard.subprocess.run", side_effect=_side_effect):
        result = _read_linux()
    assert result == "xsel text"


def test_read_linux_returns_none_when_all_missing() -> None:
    with patch("lumi.host_helper.clipboard.subprocess.run", side_effect=FileNotFoundError):
        result = _read_linux()
    assert result is None
