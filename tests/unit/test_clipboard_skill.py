"""Tests for the ClipboardSkill native skill."""

from __future__ import annotations

from unittest.mock import patch

from lumi.skills.native.clipboard_skill import ClipboardSkill


def test_matches_clipboard_phrases() -> None:
    skill = ClipboardSkill(enabled=True)
    assert skill.matches("what's in my clipboard")
    assert skill.matches("read my clipboard")
    assert skill.matches("what did i copy")
    assert skill.matches("show my clipboard")


def test_does_not_match_unrelated() -> None:
    skill = ClipboardSkill(enabled=True)
    assert not skill.matches("what time is it")
    assert not skill.matches("set a timer for 5 minutes")


def test_disabled_returns_message_without_reading() -> None:
    skill = ClipboardSkill(enabled=False)
    with patch("lumi.host_helper.clipboard.read") as mock_read:
        result = skill.execute("what's in my clipboard")
    mock_read.assert_not_called()
    assert "disabled" in result.text.lower()
    assert result.handled is True


def test_enabled_returns_clipboard_content() -> None:
    skill = ClipboardSkill(enabled=True)
    with patch("lumi.host_helper.clipboard.read", return_value="hello world"):
        result = skill.execute("what's in my clipboard")
    assert "hello world" in result.text
    assert result.handled is True


def test_enabled_empty_clipboard() -> None:
    skill = ClipboardSkill(enabled=True)
    with patch("lumi.host_helper.clipboard.read", return_value="   "):
        result = skill.execute("clipboard")
    assert "empty" in result.text.lower()


def test_enabled_clipboard_read_failure() -> None:
    skill = ClipboardSkill(enabled=True)
    with patch("lumi.host_helper.clipboard.read", return_value=None):
        result = skill.execute("clipboard")
    assert "couldn't" in result.text.lower()


def test_long_clipboard_is_truncated() -> None:
    skill = ClipboardSkill(enabled=True)
    long_text = "x" * 600
    with patch("lumi.host_helper.clipboard.read", return_value=long_text):
        result = skill.execute("clipboard")
    assert len(result.text) < 600
    assert "…" in result.text


def test_router_includes_clipboard_skill() -> None:
    """ClipboardSkill appears in the router's native skill list when enabled."""
    from unittest.mock import MagicMock

    from lumi.skills.router import SkillRouter

    conv = MagicMock()
    tts = MagicMock()
    router = SkillRouter(conversation=conv, tts=tts, clipboard_enabled=True)
    names = [type(s).__name__ for s in router._native]
    assert "ClipboardSkill" in names
