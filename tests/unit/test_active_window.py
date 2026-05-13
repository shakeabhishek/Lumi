"""Tests for host_helper.active_window — mocks subprocess so no OS calls needed."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from lumi.host_helper.active_window import ActiveWindow, _get_linux, _get_macos, get


def test_active_window_str_with_different_app_and_title() -> None:
    w = ActiveWindow(title="README.md", app="VS Code")
    assert "README.md" in str(w)
    assert "VS Code" in str(w)


def test_active_window_str_same_app_and_title() -> None:
    w = ActiveWindow(title="Finder", app="Finder")
    assert str(w) == "Finder"


def test_active_window_str_empty() -> None:
    w = ActiveWindow(title="", app="")
    assert str(w) == "unknown"


def test_get_macos_returns_window(monkeypatch: object) -> None:
    monkeypatch.setattr("sys.platform", "darwin")
    responses = [
        MagicMock(returncode=0, stdout="Visual Studio Code\n"),
        MagicMock(returncode=0, stdout="main.py — lumi\n"),
    ]
    with patch("lumi.host_helper.active_window.subprocess.run", side_effect=responses):
        result = _get_macos()
    assert result is not None
    assert result.app == "Visual Studio Code"
    assert "main.py" in result.title


def test_get_macos_falls_back_to_app_on_no_window() -> None:
    responses = [
        MagicMock(returncode=0, stdout="Finder\n"),
        MagicMock(returncode=1, stdout=""),  # no open windows
    ]
    with patch("lumi.host_helper.active_window.subprocess.run", side_effect=responses):
        result = _get_macos()
    assert result is not None
    assert result.app == "Finder"
    assert result.title == "Finder"


def test_get_macos_returns_none_on_failure() -> None:
    with patch("lumi.host_helper.active_window.subprocess.run",
               return_value=MagicMock(returncode=1, stdout="")):
        result = _get_macos()
    assert result is None


def test_get_linux_uses_xdotool() -> None:
    mock = MagicMock(return_value=MagicMock(returncode=0, stdout="My App\n"))
    with patch("lumi.host_helper.active_window.subprocess.run", mock):
        result = _get_linux()
    assert result is not None
    assert result.title == "My App"


def test_get_linux_returns_none_when_tools_missing() -> None:
    with patch("lumi.host_helper.active_window.subprocess.run", side_effect=FileNotFoundError):
        result = _get_linux()
    assert result is None


def test_get_returns_none_on_unexpected_error(monkeypatch: object) -> None:
    monkeypatch.setattr("sys.platform", "darwin")
    with patch("lumi.host_helper.active_window.subprocess.run", side_effect=RuntimeError("boom")):
        result = get()
    assert result is None
