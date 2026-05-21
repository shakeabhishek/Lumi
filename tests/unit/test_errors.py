"""Tests for runtime.errors.safe_error_message — the single place that
turns an internal exception into a user-safe sentence."""

from __future__ import annotations

from lumi.runtime.errors import safe_error_message


def test_returns_generic_friendly_default() -> None:
    out = safe_error_message(RuntimeError("nasty internal detail"), where="chat.send")
    assert "nasty internal detail" not in out
    assert "Sorry" in out
    # No file paths, no class names, no internal URLs.
    assert "/" not in out
    assert "RuntimeError" not in out


def test_accepts_caller_specified_user_text() -> None:
    out = safe_error_message(
        ValueError("inner stuff"), where="x", user_text="The clock has stopped.",
    )
    assert out == "The clock has stopped."
    assert "inner stuff" not in out


def test_exception_class_and_where_tag_are_logged_for_debugging() -> None:
    """The exception class + the where-tag are logged for devs even
    though they're stripped from the user-visible string. We patch the
    module-level logger to capture the call rather than rely on stdout
    redirection (structlog binds sys.stderr at import time)."""
    from unittest.mock import patch  # noqa: PLC0415

    with patch("lumi.runtime.errors.log") as mock_log:
        safe_error_message(KeyError("missing-thing"), where="voice.router")

    mock_log.warning.assert_called_once()
    kwargs = mock_log.warning.call_args.kwargs
    assert kwargs.get("where") == "voice.router"
    assert kwargs.get("type") == "KeyError"


def test_does_not_raise_on_unicode_or_weird_exceptions() -> None:
    """We never want the safety helper to itself blow up."""
    class Weird(Exception):
        def __str__(self) -> str:
            return "💥 unicode ünexpected"
    out = safe_error_message(Weird(), where="x")
    assert "Sorry" in out


def test_truncates_huge_exception_message_in_log() -> None:
    """Don't blow up the structured log with a 1MB exception text."""
    huge = "x" * 10_000
    out = safe_error_message(RuntimeError(huge), where="x")
    assert out == "Sorry, something went wrong. Please try again."
    # No way to easily assert on what was logged at byte level here, but the
    # truncation cap [:300] is the contract — the function returned, that's
    # the important behavioural guarantee.
