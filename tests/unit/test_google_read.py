"""Tests for read-only Gmail access over IMAP.

The read-only guarantees are the point of these tests. IMAP is a protocol
where *reading* mail mutates it unless you explicitly opt out, so "we only
call read methods" isn't sufficient and can't be verified by inspection —
`BODY[...]` and `BODY.PEEK[...]` look nearly identical and differ in whether
they mark the user's mail as read. See skills/google_read.py.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from lumi.skills import google_read
from lumi.skills.google_read import (
    GMAIL_ADDRESS_KEY,
    GMAIL_APP_PASSWORD_KEY,
    GMAIL_PERSONAL_ADDRESS_KEY,
    GMAIL_PERSONAL_APP_PASSWORD_KEY,
    configured,
    configured_accounts,
    gmail_recent,
)


def _header_bytes(sender: str, subject: str, date: str = "Mon, 3 Aug 2026 10:00:00 +0000") -> bytes:
    return f"From: {sender}\r\nSubject: {subject}\r\nDate: {date}\r\n\r\n".encode()


class _FakeIMAP:
    """Records every command so the tests can assert on what was NOT sent."""

    def __init__(self, messages: list[bytes] | None = None) -> None:
        self.messages = messages if messages is not None else []
        self.calls: list[tuple] = []
        self.select_kwargs: dict = {}
        self.closed = False
        self.logged_out = False

    def login(self, user, password):
        self.calls.append(("login", user))
        return ("OK", [b""])

    def select(self, mailbox, readonly=False):
        self.calls.append(("select", mailbox))
        self.select_kwargs = {"readonly": readonly}
        return ("OK", [b"1"])

    def search(self, charset, criterion):
        self.calls.append(("search", criterion))
        ids = b" ".join(str(i + 1).encode() for i in range(len(self.messages)))
        return ("OK", [ids])

    def fetch(self, msg_id, spec):
        self.calls.append(("fetch", spec))
        idx = int(msg_id) - 1
        return ("OK", [(b"1 (...)", self.messages[idx])])

    def close(self):
        self.closed = True

    def logout(self):
        self.logged_out = True

    # Deliberately absent from normal use — present so a test can assert they
    # are never called. Any of these would be a write to the user's mailbox.
    def store(self, *a, **k):  # pragma: no cover
        raise AssertionError("store() is a WRITE — must never be called")

    def expunge(self, *a, **k):  # pragma: no cover
        raise AssertionError("expunge() is a WRITE — must never be called")

    def copy(self, *a, **k):  # pragma: no cover
        raise AssertionError("copy() is a WRITE — must never be called")

    def append(self, *a, **k):  # pragma: no cover
        raise AssertionError("append() is a WRITE — must never be called")


# The default account is "mine" (the owner's inbox), so the general-purpose
# fixture configures that one; `both_creds` wires up Lumi's as well.
@pytest.fixture
def creds(monkeypatch):
    store = {
        GMAIL_PERSONAL_ADDRESS_KEY: "owner.personal@gmail.com",
        GMAIL_PERSONAL_APP_PASSWORD_KEY: "abcd" * 4,
    }
    monkeypatch.setattr(google_read.secrets, "get_secret", store.get)
    return store


@pytest.fixture
def lumi_creds(monkeypatch):
    store = {GMAIL_ADDRESS_KEY: "lumi.dedicated@gmail.com", GMAIL_APP_PASSWORD_KEY: "abcd" * 4}
    monkeypatch.setattr(google_read.secrets, "get_secret", store.get)
    return store


@pytest.fixture
def both_creds(monkeypatch):
    store = {
        GMAIL_PERSONAL_ADDRESS_KEY: "owner.personal@gmail.com",
        GMAIL_PERSONAL_APP_PASSWORD_KEY: "abcd" * 4,
        GMAIL_ADDRESS_KEY: "lumi.dedicated@gmail.com",
        GMAIL_APP_PASSWORD_KEY: "efgh" * 4,
    }
    monkeypatch.setattr(google_read.secrets, "get_secret", store.get)
    return store


@pytest.fixture
def no_creds(monkeypatch):
    monkeypatch.setattr(google_read.secrets, "get_secret", lambda _k: None)


def _run(fake: _FakeIMAP, **kwargs) -> str:
    with patch.object(google_read.imaplib, "IMAP4_SSL", return_value=fake):
        return gmail_recent(**kwargs)


# ── read-only guarantees ─────────────────────────────────────────────────


def test_opens_the_mailbox_readonly(creds) -> None:
    """readonly=True makes it an EXAMINE, so the server itself refuses state
    changes on this connection — a belt to the braces of not calling writes."""
    fake = _FakeIMAP([_header_bytes("a@b.com", "hi")])
    _run(fake)
    assert fake.select_kwargs == {"readonly": True}


def test_uses_body_peek_so_mail_is_not_marked_read(creds) -> None:
    """The subtle one. A plain `BODY[...]` fetch sets the \\Seen flag as a side
    effect, so Lumi glancing at the inbox would mark the user's mail as read —
    a write to their mailbox, and invisible from the code unless you know the
    difference between BODY and BODY.PEEK."""
    fake = _FakeIMAP([_header_bytes("a@b.com", "hi")])
    _run(fake)
    fetches = [spec for kind, spec in fake.calls if kind == "fetch"]
    assert fetches, "expected at least one fetch"
    for spec in fetches:
        assert "BODY.PEEK[" in spec, f"non-PEEK fetch would mark mail read: {spec}"
        assert "BODY[" not in spec.replace("BODY.PEEK[", "")


def test_never_fetches_message_bodies(creds) -> None:
    """Bodies are the highest-PII surface in the product and a spoken summary
    doesn't need them. Only From/Subject/Date are requested."""
    fake = _FakeIMAP([_header_bytes("a@b.com", "hi")])
    _run(fake)
    for kind, spec in fake.calls:
        if kind == "fetch":
            assert "HEADER.FIELDS" in spec
            assert "TEXT" not in spec


def test_no_write_commands_are_issued(creds) -> None:
    """_FakeIMAP raises on store/expunge/copy/append, so reaching any of them
    fails loudly rather than silently mutating a real mailbox later."""
    fake = _FakeIMAP([_header_bytes("a@b.com", "hi")])
    _run(fake)  # would raise AssertionError from the fake if a write happened
    kinds = {kind for kind, _ in fake.calls}
    assert kinds <= {"login", "select", "search", "fetch"}


def test_connection_is_closed_and_logged_out(creds) -> None:
    fake = _FakeIMAP([_header_bytes("a@b.com", "hi")])
    _run(fake)
    assert fake.closed and fake.logged_out


def test_teardown_still_runs_when_fetch_explodes(creds) -> None:
    """A leaked IMAP connection on a long-lived appliance accumulates until
    Gmail starts refusing new ones."""
    fake = _FakeIMAP([_header_bytes("a@b.com", "hi")])
    fake.fetch = MagicMock(side_effect=OSError("boom"))
    result = _run(fake)
    assert fake.closed and fake.logged_out
    assert "couldn't reach Gmail" in result


# ── behaviour ────────────────────────────────────────────────────────────


def test_summarises_senders_and_subjects(creds) -> None:
    fake = _FakeIMAP([
        _header_bytes("Jane Doe <jane@x.com>", "Lunch?"),
        _header_bytes("bob@y.com", "Invoice attached"),
    ])
    out = _run(fake, limit=5)
    assert "Jane Doe" in out
    assert "Lunch?" in out
    assert "bob@y.com" in out


def test_prefers_display_name_over_raw_address(creds) -> None:
    fake = _FakeIMAP([_header_bytes("Jane Doe <jane@x.com>", "Hi")])
    out = _run(fake)
    assert "Jane Doe" in out
    assert "jane@x.com" not in out, "spoken output should read the name, not the address"


def test_decodes_mime_encoded_headers(creds) -> None:
    """Real subject lines arrive RFC 2047-encoded; unrendered =?UTF-8?B?...
    would be read aloud verbatim."""
    fake = _FakeIMAP([
        b"From: =?UTF-8?B?Su+/vXJnZW4=?= <j@x.com>\r\n"
        b"Subject: =?UTF-8?Q?Caf=C3=A9_meeting?=\r\n\r\n",
    ])
    out = _run(fake)
    assert "Café meeting" in out
    assert "=?UTF-8?" not in out


def test_missing_subject_gets_a_placeholder(creds) -> None:
    fake = _FakeIMAP([b"From: a@b.com\r\n\r\n"])
    out = _run(fake)
    assert "(no subject)" in out


def test_newest_messages_first(creds) -> None:
    fake = _FakeIMAP([
        _header_bytes("old@x.com", "oldest"),
        _header_bytes("new@x.com", "newest"),
    ])
    out = _run(fake)
    assert out.index("newest") < out.index("oldest")


def test_limit_is_clamped_to_a_sane_range(creds) -> None:
    fake = _FakeIMAP([_header_bytes(f"a{i}@x.com", f"s{i}") for i in range(30)])
    out = _run(fake, limit=999)
    assert len(out.splitlines()) - 1 <= 10


def test_limit_below_one_still_returns_something(creds) -> None:
    fake = _FakeIMAP([_header_bytes("a@x.com", "s")])
    out = _run(fake, limit=0)
    assert "a@x.com" in out


def test_unread_only_uses_the_unseen_criterion(creds) -> None:
    fake = _FakeIMAP([_header_bytes("a@x.com", "s")])
    _run(fake, unread_only=True)
    assert ("search", "(UNSEEN)") in fake.calls


def test_unread_only_false_searches_all(creds) -> None:
    fake = _FakeIMAP([_header_bytes("a@x.com", "s")])
    _run(fake, unread_only=False)
    assert ("search", "ALL") in fake.calls


def test_empty_inbox_reads_naturally(creds) -> None:
    out = _run(_FakeIMAP([]))
    assert "No unread mail" in out


# ── failure modes: spoken aloud, so never a raw exception ─────────────────


def test_unconfigured_explains_the_app_password_requirement(no_creds) -> None:
    """The most likely setup mistake is using the account password. Google
    requires a 16-char App Password with 2-Step Verification for IMAP. The hint
    names the exact secret for the account asked about, not a generic one."""
    out = gmail_recent()
    assert "App Password" in out
    assert "lumi keys set gmail_personal_app_password" in out

    lumi_hint = gmail_recent(account="lumi")
    assert "lumi keys set gmail_app_password" in lumi_hint


def test_single_account_errors_are_unprefixed(creds) -> None:
    """No point saying "your inbox:" when only one mailbox was consulted —
    matches the success and empty-inbox paths."""
    fake = _FakeIMAP([])
    fake.login = MagicMock(side_effect=TimeoutError("timed out"))
    assert _run(fake) == "I couldn't reach Gmail just now."


def test_multi_account_errors_say_which_mailbox_failed(both_creds) -> None:
    fake = _FakeIMAP([])
    fake.login = MagicMock(side_effect=TimeoutError("timed out"))
    out = _run(fake, account="both")
    assert "your inbox: I couldn't reach Gmail" in out
    assert "Lumi's inbox: I couldn't reach Gmail" in out


def test_configured_reflects_secret_presence(creds, monkeypatch) -> None:
    assert configured() is True
    monkeypatch.setattr(google_read.secrets, "get_secret", lambda _k: None)
    assert configured() is False


# ── two mailboxes ────────────────────────────────────────────────────────


def test_only_configured_accounts_are_reachable(lumi_creds) -> None:
    """Absence of a credential IS the access control. With only Lumi's account
    wired, there is no code path that reaches the owner's inbox."""
    assert configured_accounts() == ["lumi"]


def test_both_accounts_when_both_are_wired(both_creds) -> None:
    assert set(configured_accounts()) == {"mine", "lumi"}


def test_unconfigured_personal_inbox_is_not_read(lumi_creds) -> None:
    """Asking for the owner's mail with no personal credential must decline,
    never silently fall back to reading Lumi's inbox instead — a mailbox mixup
    on a spoken summary is a privacy failure, not a UX wrinkle."""
    fake = _FakeIMAP([_header_bytes("a@b.com", "should not be read")])
    out = _run(fake, account="mine")
    assert "isn't set up yet" in out
    assert "should not be read" not in out
    assert fake.calls == [], "no IMAP connection should have been made at all"


def test_default_account_is_the_owners_inbox(creds) -> None:
    """"Check my email" is the overwhelmingly common request."""
    fake = _FakeIMAP([_header_bytes("a@b.com", "hello")])
    out = _run(fake)
    assert "hello" in out
    assert ("login", "owner.personal@gmail.com") in fake.calls


def test_lumi_account_can_be_addressed_explicitly(both_creds) -> None:
    fake = _FakeIMAP([_header_bytes("a@b.com", "hello")])
    _run(fake, account="lumi")
    assert ("login", "lumi.dedicated@gmail.com") in fake.calls


def test_both_labels_each_section_so_ownership_is_never_ambiguous(both_creds) -> None:
    """Spoken aloud, an unlabelled combined summary would leave you unsure
    whose mail you just heard."""
    fake = _FakeIMAP([_header_bytes("a@b.com", "shared subject")])
    out = _run(fake, account="both")
    assert "your inbox" in out
    assert "Lumi's inbox" in out
    logins = [v for k, v in fake.calls if k == "login"]
    assert "owner.personal@gmail.com" in logins
    assert "lumi.dedicated@gmail.com" in logins


def test_one_account_failing_does_not_lose_the_other(both_creds) -> None:
    """A dead personal mailbox shouldn't blank out Lumi's, or vice versa."""
    import imaplib as _imaplib  # noqa: PLC0415

    calls = {"n": 0}

    class _FlakyFirst(_FakeIMAP):
        def login(self, user, password):
            calls["n"] += 1
            if calls["n"] == 1:
                raise _imaplib.IMAP4.error("AUTHENTICATIONFAILED")
            return super().login(user, password)

    fake = _FlakyFirst([_header_bytes("a@b.com", "survivor")])
    out = _run(fake, account="both")
    assert "rejected the login" in out
    assert "survivor" in out


def test_unknown_account_name_is_refused_clearly(both_creds) -> None:
    fake = _FakeIMAP([_header_bytes("a@b.com", "x")])
    out = _run(fake, account="nonsense")
    assert "don't know an email account" in out
    assert fake.calls == []


def test_account_name_is_case_and_space_insensitive(creds) -> None:
    fake = _FakeIMAP([_header_bytes("a@b.com", "hello")])
    out = _run(fake, account="  MINE ")
    assert "hello" in out


def test_personal_secrets_are_swept_by_factory_reset() -> None:
    """Read-only or not, these are live credentials to the owner's real
    mailbox — "Forget everything" must remove them."""
    from lumi.ui.web.routes.settings import _KNOWN_SECRET_KEYS  # noqa: PLC0415

    assert GMAIL_PERSONAL_ADDRESS_KEY in _KNOWN_SECRET_KEYS
    assert GMAIL_PERSONAL_APP_PASSWORD_KEY in _KNOWN_SECRET_KEYS


def test_personal_secrets_are_settable_via_the_cli() -> None:
    import inspect  # noqa: PLC0415

    from lumi import main as main_mod  # noqa: PLC0415

    src = inspect.getsource(main_mod.keys)
    assert GMAIL_PERSONAL_ADDRESS_KEY in src
    assert GMAIL_PERSONAL_APP_PASSWORD_KEY in src


def test_auth_failure_is_actionable_and_leaks_nothing(creds) -> None:
    """The IMAP error string can echo the account address; the spoken message
    must not carry it."""
    import imaplib as _imaplib  # noqa: PLC0415

    fake = _FakeIMAP([])
    fake.login = MagicMock(
        side_effect=_imaplib.IMAP4.error("AUTHENTICATIONFAILED for owner.personal@gmail.com"),
    )
    out = _run(fake)
    assert "App Password" in out
    assert "owner.personal@gmail.com" not in out


def test_imap_uses_a_timeout_below_the_skill_deadline(creds) -> None:
    """The router kills a skill at 10s, so the socket has to give up first or
    the timeout fires on a connection that's still politely waiting."""
    assert google_read._IMAP_TIMEOUT_S < 10.0

    captured = {}

    def fake_ctor(host, port, timeout=None):
        captured.update(host=host, port=port, timeout=timeout)
        return _FakeIMAP([])

    with patch.object(google_read.imaplib, "IMAP4_SSL", fake_ctor):
        gmail_recent()
    assert captured["host"] == "imap.gmail.com"
    assert captured["port"] == 993
    assert captured["timeout"] == google_read._IMAP_TIMEOUT_S


# ── registration ─────────────────────────────────────────────────────────
#
# Imports in these three are local on purpose: pulling the web routes in at
# module level would make this entire Gmail test file depend on the [web]
# extra, and the IMAP behaviour above has nothing to do with FastAPI.


def test_gmail_read_is_a_callable_skill() -> None:
    from lumi.skills.openclaw_bridge import _SKILL_IMPLS  # noqa: PLC0415

    assert "gmail_read" in _SKILL_IMPLS, (
        "a catalog entry without a _SKILL_IMPLS handler is documentation, not a "
        "callable tool — which is exactly what email_read/calendar_read were"
    )
    assert _SKILL_IMPLS["gmail_read"]["tool_name"] == "read_email"


def test_gmail_secrets_are_swept_by_factory_reset() -> None:
    """Without this, "Forget everything" leaves working mailbox credentials on
    disk — the same class of bug the cloud-key entry in that list guards."""
    from lumi.ui.web.routes.settings import _KNOWN_SECRET_KEYS  # noqa: PLC0415

    assert GMAIL_ADDRESS_KEY in _KNOWN_SECRET_KEYS
    assert GMAIL_APP_PASSWORD_KEY in _KNOWN_SECRET_KEYS


def test_gmail_secrets_are_settable_via_the_cli() -> None:
    """`lumi keys set` now hard-fails on unknown names, so a secret missing
    from KNOWN can't be set at all."""
    import inspect  # noqa: PLC0415

    from lumi import main as main_mod  # noqa: PLC0415

    src = inspect.getsource(main_mod.keys)
    assert GMAIL_ADDRESS_KEY in src
    assert GMAIL_APP_PASSWORD_KEY in src
