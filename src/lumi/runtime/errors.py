"""User-facing error helpers.

Internal exceptions carry information that's useful to a developer (file
paths, internal URLs, library traceback fragments) but useless or
confusing to a user — and a potential information leak if it ever makes
it onto a shared screen, a screenshot, or a server-side log dump someone
emails around.

`safe_error_message(exc)` is the single place that decides what users
see when something internal blows up. It always logs the full exception
context to the structured logger; the return string is a short,
generic, friendly sentence with no exception text in it.
"""

from __future__ import annotations

from ..log import get_logger

log = get_logger(__name__)


def safe_error_message(
    exc: BaseException,
    *,
    where: str,
    user_text: str = "Sorry, something went wrong. Please try again.",
) -> str:
    """Log the exception (with full info) and return a generic user string.

    `where` is a short structured-log field — e.g. "chat.send",
    "voice.router" — so devs can grep the log to find the original.
    `user_text` is what to actually show; defaults to a friendly generic.
    """
    log.warning("user_facing_error", where=where, type=type(exc).__name__, error=str(exc)[:300])
    return user_text
