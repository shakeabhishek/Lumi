"""Tests for the PII pseudonymizer.

This is security-critical: a regression here would leak PII to the cloud
LLM. Each pattern is exercised with positive + negative cases.
"""

from __future__ import annotations

import pytest

from lumi.runtime.privacy import Pseudonymizer, _luhn_ok, mask_messages


@pytest.fixture
def pz() -> Pseudonymizer:
    return Pseudonymizer(use_presidio=False)   # regex-only for deterministic tests


# ── Email ────────────────────────────────────────────────────────────────────


def test_masks_email(pz: Pseudonymizer) -> None:
    out = pz.mask("ping me at alice@example.com tomorrow")
    assert "alice@example.com" not in out
    assert "<EMAIL_1>" in out


def test_email_stable_across_occurrences(pz: Pseudonymizer) -> None:
    out = pz.mask("alice@example.com and again alice@example.com")
    # Same email → same pseudonym
    assert out.count("<EMAIL_1>") == 2
    assert "<EMAIL_2>" not in out


def test_different_emails_get_different_tokens(pz: Pseudonymizer) -> None:
    out = pz.mask("alice@x.com bob@y.com")
    assert "<EMAIL_1>" in out and "<EMAIL_2>" in out


def test_unmask_email_round_trip(pz: Pseudonymizer) -> None:
    text = "email alice@example.com to confirm"
    masked = pz.mask(text)
    assert pz.unmask(masked) == text


# ── Phone ────────────────────────────────────────────────────────────────────


def test_masks_us_phone(pz: Pseudonymizer) -> None:
    out = pz.mask("call me at (415) 555-2671")
    assert "555-2671" not in out
    assert "<PHONE_" in out


def test_masks_intl_phone(pz: Pseudonymizer) -> None:
    out = pz.mask("number: +44 20 7946 0958")
    assert "<PHONE_" in out


def test_does_not_mask_short_digit_runs(pz: Pseudonymizer) -> None:
    """We shouldn't be masking room numbers, prices, etc."""
    out = pz.mask("room 412 is $30 for 2 hours")
    assert "<PHONE_" not in out
    assert "412" in out


# ── SSN ──────────────────────────────────────────────────────────────────────


def test_masks_ssn(pz: Pseudonymizer) -> None:
    out = pz.mask("ssn 123-45-6789 on file")
    assert "123-45-6789" not in out
    assert "<SSN_1>" in out


# ── Credit card (with Luhn check) ───────────────────────────────────────────


def test_masks_valid_credit_card(pz: Pseudonymizer) -> None:
    # 4111 1111 1111 1111 is a known Luhn-valid test number
    out = pz.mask("card 4111 1111 1111 1111 expires soon")
    assert "4111 1111 1111 1111" not in out
    assert "<CARD_1>" in out


def test_does_not_mask_luhn_invalid_long_number(pz: Pseudonymizer) -> None:
    # Random 16 digits that don't pass Luhn — likely an ID, not a card
    out = pz.mask("transaction id 1234567890123456 received")
    assert "1234567890123456" in out
    assert "<CARD_" not in out


def test_luhn_ok_known_values() -> None:
    assert _luhn_ok("4111111111111111")     # valid Visa test
    assert _luhn_ok("5500 0000 0000 0004")  # valid Mastercard test
    assert not _luhn_ok("4111111111111112") # off-by-one fails
    assert not _luhn_ok("1234567890123456") # arbitrary number — Luhn-fails
    assert not _luhn_ok("12")               # too short


# ── IP / ZIP ────────────────────────────────────────────────────────────────


def test_masks_ipv4(pz: Pseudonymizer) -> None:
    out = pz.mask("server at 192.168.1.42 is up")
    assert "192.168.1.42" not in out
    assert "<IP_1>" in out


def test_masks_zip(pz: Pseudonymizer) -> None:
    out = pz.mask("ship to 94103 by friday")
    assert "94103" not in out
    assert "<ZIP_1>" in out


def test_masks_zip_plus_four(pz: Pseudonymizer) -> None:
    out = pz.mask("address 94103-1234")
    assert "94103-1234" not in out
    assert "<ZIP_1>" in out


# ── API keys ────────────────────────────────────────────────────────────────


def test_masks_openai_key(pz: Pseudonymizer) -> None:
    key = "sk-proj-AbCdEfGhIjKlMnOpQrStUvWxYz1234567890"
    out = pz.mask(f"my key is {key}")
    assert key not in out
    assert "<API_KEY_1>" in out


def test_masks_anthropic_key(pz: Pseudonymizer) -> None:
    key = "sk-ant-api03-abcdefghijklmnopqrstuv1234567890"
    out = pz.mask(f"set key {key}")
    assert key not in out


def test_masks_github_pat(pz: Pseudonymizer) -> None:
    key = "ghp_abcdefghijklmnopqrstuvwxyz123456"
    out = pz.mask(f"github pat {key}")
    assert key not in out


def test_masks_google_key(pz: Pseudonymizer) -> None:
    key = "AIzaSyDfgL1IqUg3lkj_xYz_VeryFakeKey1234567"
    out = pz.mask(f"google key {key}")
    assert key not in out


# ── Names (extra_names) ─────────────────────────────────────────────────────


def test_masks_owner_name_anywhere() -> None:
    pz = Pseudonymizer(use_presidio=False, extra_names=["Alex"])
    out = pz.mask("Alex needs to call alex@x.com")
    # Both should be replaced; first-name match is case-insensitive
    assert "Alex" not in out and "alex" not in out.split("<EMAIL")[0]
    assert "<PERSON_1>" in out


def test_owner_name_does_not_substring_other_words() -> None:
    """Owner 'Pat' shouldn't mask 'pattern' or 'patio'."""
    pz = Pseudonymizer(use_presidio=False, extra_names=["Pat"])
    out = pz.mask("the pattern matches the patio")
    # Should not mask 'pat' inside 'pattern' / 'patio' (word boundary)
    assert "pattern" in out
    assert "patio" in out


def test_extra_names_longest_first() -> None:
    """Longer names should be matched before shorter ones to avoid partials."""
    pz = Pseudonymizer(use_presidio=False, extra_names=["Anna", "Anna-Marie"])
    out = pz.mask("Anna-Marie said hi")
    # "Anna-Marie" should mask as ONE token, not "Anna" + "-Marie"
    assert out.count("<PERSON_") == 1


# ── Unmask ──────────────────────────────────────────────────────────────────


def test_unmask_handles_two_digit_indices() -> None:
    pz = Pseudonymizer(use_presidio=False)
    text = " ".join(f"user{i}@x.com" for i in range(12))
    masked = pz.mask(text)
    assert "<EMAIL_12>" in masked   # ensures we generated two-digit token
    unmasked = pz.unmask(masked)
    # Round-trip: every original email present
    for i in range(12):
        assert f"user{i}@x.com" in unmasked


def test_unmask_with_empty_mapping_is_passthrough(pz: Pseudonymizer) -> None:
    assert pz.unmask("hello world") == "hello world"


def test_reset_clears_mapping(pz: Pseudonymizer) -> None:
    pz.mask("alice@x.com")
    assert pz.mapping
    pz.reset()
    assert pz.mapping == {}
    # Next mask starts counters at 1 again
    out = pz.mask("bob@y.com")
    assert "<EMAIL_1>" in out


# ── mask_messages helper ────────────────────────────────────────────────────


def test_mask_messages_each_content(pz: Pseudonymizer) -> None:
    msgs = [
        {"role": "system", "content": "You are Lumi."},
        {"role": "user", "content": "email alice@x.com"},
        {"role": "assistant", "content": "OK, will do."},
    ]
    out = mask_messages(msgs, pz)
    assert out[0]["content"] == "You are Lumi."   # nothing to mask
    assert "alice@x.com" not in out[1]["content"]
    assert "<EMAIL_1>" in out[1]["content"]
    assert out[2]["content"] == "OK, will do."


def test_mask_messages_does_not_mutate_input(pz: Pseudonymizer) -> None:
    msgs = [{"role": "user", "content": "email alice@x.com"}]
    mask_messages(msgs, pz)
    assert msgs[0]["content"] == "email alice@x.com"


# ── Negative / safety cases ─────────────────────────────────────────────────


def test_empty_string_is_safe(pz: Pseudonymizer) -> None:
    assert pz.mask("") == ""
    assert pz.unmask("") == ""


def test_no_pii_returns_unchanged(pz: Pseudonymizer) -> None:
    text = "what's the weather like today"
    assert pz.mask(text) == text
    assert pz.mapping == {}


def test_pseudonymizer_does_not_leak_across_instances() -> None:
    a = Pseudonymizer(use_presidio=False)
    b = Pseudonymizer(use_presidio=False)
    a.mask("alice@x.com")
    assert b.mapping == {}   # b should have nothing of a's PII


# ── Expanded pattern coverage (audit #6) ────────────────────────────────────


def test_masks_aws_access_key_id() -> None:
    pz = Pseudonymizer(use_presidio=False)
    out = pz.mask("AWS key AKIAIOSFODNN7EXAMPLE was leaked")
    assert "AKIAIOSFODNN7EXAMPLE" not in out
    assert "<API_KEY_1>" in out


def test_masks_aws_temp_access_key() -> None:
    pz = Pseudonymizer(use_presidio=False)
    out = pz.mask("ASIAIOSFODNN7EXAMPLE is the session key")
    assert "ASIAIOSFODNN7EXAMPLE" not in out


def test_masks_jwt_token() -> None:
    pz = Pseudonymizer(use_presidio=False)
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36"
    out = pz.mask(f"my token is {jwt} please rotate it")
    assert jwt not in out
    assert "<JWT_1>" in out


def test_masks_bearer_token_header() -> None:
    pz = Pseudonymizer(use_presidio=False)
    out = pz.mask("curl -H 'Authorization: Bearer abc123def456ghi789jkl012mno345pqr'")
    assert "abc123def456" not in out
    assert "<BEARER_1>" in out


def test_masks_ipv6_address() -> None:
    pz = Pseudonymizer(use_presidio=False)
    out = pz.mask("server is at 2001:0db8:85a3:0000:0000:8a2e:0370:7334 on port 8080")
    assert "2001:0db8" not in out


def test_masks_mac_address() -> None:
    pz = Pseudonymizer(use_presidio=False)
    out = pz.mask("device MAC is 3C:22:FB:7D:E1:42 — block it")
    assert "3C:22:FB:7D:E1:42" not in out
    assert "<MAC_1>" in out


def test_masks_iban() -> None:
    pz = Pseudonymizer(use_presidio=False)
    out = pz.mask("transfer to DE89 3704 0044 0532 0130 00 immediately")
    assert "0532 0130 00" not in out
    assert "<IBAN_1>" in out


def test_masks_github_fine_grained_pat() -> None:
    pz = Pseudonymizer(use_presidio=False)
    out = pz.mask("token github_pat_11AAAAAAA0abcdefghijklmnopqrstuvwxyzABCD is rotated")
    assert "github_pat_11AAAAA" not in out


def test_masks_us_street_address_obvious_forms() -> None:
    pz = Pseudonymizer(use_presidio=False)
    out = pz.mask("ship to 123 Main Street, Springfield")
    assert "123 Main Street" not in out
    assert "<ADDRESS_1>" in out


def test_does_not_mask_unlabelled_dates() -> None:
    """Plain dates aren't necessarily PII. We only mask DOB-labelled forms."""
    pz = Pseudonymizer(use_presidio=False)
    out = pz.mask("the meeting is on 2026-05-21 at noon")
    # Date stays as-is — too aggressive to scrub all dates.
    assert "2026-05-21" in out


def test_masks_labelled_dob() -> None:
    pz = Pseudonymizer(use_presidio=False)
    out = pz.mask("DOB: 04/12/1990 on file")
    assert "04/12/1990" not in out
    assert "<DOB_1>" in out


def test_high_entropy_keys_mask_before_lower_entropy_patterns() -> None:
    """If a JWT happens to contain things that look like phone digits,
    it should still be masked AS a JWT, not partially eaten by phone."""
    pz = Pseudonymizer(use_presidio=False)
    jwt = "eyJhbGc1234567890.eyJzdWIiOiJ123.SflKxwRJ4567890"
    out = pz.mask(f"token: {jwt}")
    assert "<JWT_1>" in out
    # And nothing inside it was double-tagged
    assert jwt not in out
