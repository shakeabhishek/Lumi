"""Read-only Google access for Lumi, without OAuth.

Why no OAuth, despite "Google Workspace" being the ask (researched 2026-08-06
against Google's current docs, not assumed):

  * **The OOB copy/paste flow is gone** and custom URI schemes are deprecated.
    Installed apps get loopback redirects only — `http://127.0.0.1:port` or
    `http://[::1]:port`. `http://lumi.local/...` cannot be registered, so the
    dashboard can't host the callback, and a headless Pi has no browser to
    complete a loopback flow in.
  * **Refresh tokens expire after 7 days** while the OAuth consent screen is
    in "Testing" status, for any scope beyond basic profile. An always-on desk
    appliance that needs re-authorising weekly isn't shippable.
  * Removing that means publishing to production, and `gmail.readonly` is a
    **restricted** scope — that triggers Google's verification including a
    security assessment. Disproportionate for a personal companion reading one
    dedicated mailbox.

So Gmail is read over **IMAP with an App Password**. Plain-password IMAP died
in March 2025 along with CalDAV/CardDAV/POP, but App Passwords (16 characters,
requires 2-Step Verification on the account) explicitly still work for IMAP.
No token to expire, no consent screen, no verification.

This also keeps CLAUDE.md's V1 invariant literally true rather than
approximately true — "all read-only at the protocol level (no write endpoints
configured)". See the read-only notes on `gmail_recent` below; there are two
distinct ways an IMAP client silently writes to a mailbox, and both are
avoided deliberately.

**Calendar and Drive are not here yet.** Calendar is next, over the secret
iCal (ICS) address Google Calendar exposes per calendar — a plain HTTPS GET,
no OAuth, and read-only by protocol since an ICS feed has no write verb. It
needs RRULE expansion to be honest about recurring events (a calendar skill
that silently omits your weekly standup is worse than no calendar skill), so
it wants `icalendar` + `recurring-ical-events` rather than a hand-rolled
parser. Drive is deferred: `drive.readonly` is a restricted scope, so it's the
7-day re-auth treadmill or a security audit, and neither is worth it for Drive
alone.
"""

from __future__ import annotations

import contextlib
import email
import email.header
import email.utils
import imaplib
from dataclasses import dataclass

from ..log import get_logger
from ..runtime import secrets

log = get_logger(__name__)

_IMAP_HOST = "imap.gmail.com"
_IMAP_PORT = 993

# Skills are killed at 10s by the router (CLAUDE.md's skill-timeout default),
# so the socket must give up before that or the timeout fires on a connection
# that's still politely waiting.
_IMAP_TIMEOUT_S = 6.0

_MAX_MESSAGES = 10
_MAX_SUBJECT_CHARS = 120

# Secret names. Registered in main.py's `lumi keys` KNOWN tuple and in
# settings.py's _KNOWN_SECRET_KEYS so factory reset deletes them — without the
# latter, "Forget everything" would leave mailbox credentials on disk.
GMAIL_ADDRESS_KEY = "gmail_address"
GMAIL_APP_PASSWORD_KEY = "gmail_app_password"


@dataclass(frozen=True)
class MailHeader:
    sender: str
    subject: str
    date: str


def _decode_header(raw: str | None) -> str:
    """MIME-decode a header value (=?UTF-8?B?...?=) into plain text."""
    if not raw:
        return ""
    parts = []
    for chunk, charset in email.header.decode_header(raw):
        if isinstance(chunk, bytes):
            parts.append(chunk.decode(charset or "utf-8", errors="replace"))
        else:
            parts.append(chunk)
    return "".join(parts).strip()


def _friendly_sender(raw: str | None) -> str:
    """'Jane Doe <jane@x.com>' -> 'Jane Doe'; bare addresses pass through."""
    decoded = _decode_header(raw)
    name, addr = email.utils.parseaddr(decoded)
    return name or addr or decoded


def configured() -> bool:
    return bool(
        secrets.get_secret(GMAIL_ADDRESS_KEY) and secrets.get_secret(GMAIL_APP_PASSWORD_KEY),
    )


def gmail_recent(limit: int = 5, unread_only: bool = True) -> str:
    """Summarise the most recent messages in the dedicated mailbox's INBOX.

    Returns a short human/LLM-readable string, or a specific, actionable
    message when it can't run — never a raw exception, since this text may be
    spoken aloud.

    **Read-only, deliberately, in three separate ways.** IMAP is a protocol
    where reading mail mutates it unless you opt out, so "we only call read
    methods" is not sufficient:

      1. `select(..., readonly=True)` opens the mailbox as EXAMINE rather than
         SELECT, so the server rejects any state change on this connection.
      2. Headers are fetched with `BODY.PEEK[...]` rather than `BODY[...]`.
         A plain BODY fetch sets the `\\Seen` flag as a side effect — Lumi
         glancing at the inbox would mark the user's mail as read, which is a
         write to their mailbox and exactly the kind of surprise the
         dedicated-account decision exists to prevent.
      3. No STORE, no EXPUNGE, no COPY, no APPEND anywhere in this module.

    Bodies are never fetched at all — only From/Subject/Date. Message bodies
    are the highest-PII surface in the whole product, and a spoken summary
    doesn't need them.
    """
    address = secrets.get_secret(GMAIL_ADDRESS_KEY)
    password = secrets.get_secret(GMAIL_APP_PASSWORD_KEY)
    if not address or not password:
        return (
            "Gmail isn't set up yet. Run `lumi keys set gmail_address` and "
            "`lumi keys set gmail_app_password` — the password must be a Google "
            "App Password (16 characters, needs 2-Step Verification on the "
            "account), not the account password."
        )

    limit = max(1, min(int(limit), _MAX_MESSAGES))

    try:
        headers = _fetch_headers(address, password, limit, unread_only)
    except imaplib.IMAP4.error as exc:
        # Most likely an auth failure. Deliberately does not echo the server
        # string, which can contain the account address.
        log.warning("gmail.imap_error", error=type(exc).__name__)
        return (
            "Gmail rejected the login. Check that gmail_app_password is a "
            "current App Password and that IMAP is enabled on the account."
        )
    except (OSError, TimeoutError) as exc:
        log.warning("gmail.network_error", error=type(exc).__name__)
        return "I couldn't reach Gmail just now."

    if not headers:
        return "No unread mail." if unread_only else "The inbox looks empty."

    scope = "unread" if unread_only else "recent"
    lines = [f"{len(headers)} {scope} message{'s' if len(headers) != 1 else ''}:"]
    lines += [f"- {h.sender}: {h.subject}" for h in headers]
    return "\n".join(lines)


def _fetch_headers(
    address: str, password: str, limit: int, unread_only: bool,
) -> list[MailHeader]:
    conn = imaplib.IMAP4_SSL(_IMAP_HOST, _IMAP_PORT, timeout=_IMAP_TIMEOUT_S)
    try:
        conn.login(address, password)
        # readonly=True => EXAMINE, not SELECT. See gmail_recent's docstring.
        conn.select("INBOX", readonly=True)
        criterion = "(UNSEEN)" if unread_only else "ALL"
        typ, data = conn.search(None, criterion)
        if typ != "OK" or not data or not data[0]:
            return []
        ids = data[0].split()
        # Newest last in IMAP sequence order, so take from the tail and flip.
        wanted = list(reversed(ids[-limit:]))
        out: list[MailHeader] = []
        for msg_id in wanted:
            # PEEK: does NOT set \Seen. A plain BODY[...] fetch would.
            typ, payload = conn.fetch(
                msg_id, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])",
            )
            if typ != "OK" or not payload:
                continue
            raw = next(
                (part[1] for part in payload if isinstance(part, tuple) and len(part) > 1),
                None,
            )
            if not raw:
                continue
            parsed = email.message_from_bytes(raw)
            subject = _decode_header(parsed.get("Subject")) or "(no subject)"
            out.append(
                MailHeader(
                    sender=_friendly_sender(parsed.get("From")) or "(unknown sender)",
                    subject=subject[:_MAX_SUBJECT_CHARS],
                    date=_decode_header(parsed.get("Date")),
                ),
            )
        return out
    finally:
        # close() then logout(), each independently suppressed: a half-open
        # connection on a flaky link shouldn't turn a successful read into an
        # error the user hears about, and a failing close() must not skip the
        # logout that actually releases the server-side session.
        with contextlib.suppress(Exception):
            conn.close()
        with contextlib.suppress(Exception):
            conn.logout()
