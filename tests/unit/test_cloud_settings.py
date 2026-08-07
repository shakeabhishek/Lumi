"""Tests for the cloud-LLM admin console settings."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from lumi.ui.web.app import create_app


def _fake_keyring() -> MagicMock:
    store: dict[tuple[str, str], str] = {}
    fake = MagicMock()
    fake.set_password.side_effect = lambda svc, key, value: store.update({(svc, key): value})
    fake.get_password.side_effect = lambda svc, key: store.get((svc, key))
    def _delete(svc, key): store.pop((svc, key), None)
    fake.delete_password.side_effect = _delete
    fake.get_keyring.return_value = MagicMock(__class__=type("MacOSKeychain", (), {}))
    fake._store = store
    return fake


def _client() -> tuple[TestClient, Path, MagicMock]:
    d = Path(tempfile.mkdtemp(prefix="lumi_cloud_"))
    fake = _fake_keyring()
    c = TestClient(create_app(d))
    # Warm-up GET so the CSRF cookie lands on the client's jar.
    # Subsequent POSTs need to include the same value as a form field.
    c.get("/")
    return c, d, fake


@pytest.fixture(autouse=True)
def _isolate_openclaw_config(tmp_path_factory, monkeypatch):
    """Two things must NEVER touch the developer's real ~/.openclaw:
       (a) the gateway-restart subprocess (npx openclaw — slow + real),
       (b) sync_to_openclaw writing into ~/.openclaw/openclaw.json.
    The /settings/cloud route triggers both, and once upon a time a
    test fixture's "sk-survives-csrf-check" placeholder ended up in
    the developer's real config — caught during V2 verification.
    Sandbox HOME for the duration of every test in this file."""
    fake_home = tmp_path_factory.mktemp("fake_home")
    (fake_home / ".openclaw").mkdir()
    (fake_home / ".openclaw" / "openclaw.json").write_text(
        '{"models": {"providers": {"ollama": {"baseUrl": "http://x", "api": "ollama"}}},'
        ' "agents": {"defaults": {"model": {"primary": "ollama/qwen2.5:7b"}}}}'
    )
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    with patch("lumi.skills.openclaw_operator._restart_gateway", return_value=True):
        yield


def _csrf(c: TestClient) -> str:
    """Read the CSRF token that the middleware issued on the warm-up GET."""
    return c.cookies.get("csrf_token", "")


def _post(c: TestClient, url: str, data: dict | None = None) -> object:
    """POST with the CSRF token attached. The middleware enforces it on
    every mutating method; bare TestClient.post() would 403."""
    body = dict(data or {})
    body.setdefault("csrf_token", _csrf(c))
    return c.post(url, data=body)


def test_cloud_page_renders() -> None:
    c, _, fake = _client()
    with patch.dict(sys.modules, {"keyring": fake}):
        r = c.get("/settings/cloud")
    assert r.status_code == 200
    assert "Cloud LLM" in r.text
    for provider in ("anthropic", "openai", "gemini"):
        assert f'value="{provider}"' in r.text


def test_cloud_post_writes_key_to_keychain_not_to_disk() -> None:
    c, d, fake = _client()
    with patch.dict(sys.modules, {"keyring": fake}):
        _post(c, "/settings/cloud", data={
            "cloud_llm_provider": "openai",
            "cloud_llm_api_key": "sk-test-123",
            "cloud_llm_model": "gpt-5",
        })

    on_disk = json.loads((d / "user_settings.json").read_text())
    assert "cloud_llm_api_key" not in on_disk      # never in plaintext
    assert on_disk["cloud_llm_api_key_set"] is True
    assert on_disk["cloud_llm_provider"] == "openai"
    assert on_disk["cloud_llm_model"] == "gpt-5"
    # And the secret IS in the keychain.
    assert fake._store[("lumi", "cloud_llm_api_key")] == "sk-test-123"


def test_cloud_post_blank_key_preserves_existing() -> None:
    """Re-saving the form with the key field blank must NOT wipe the keychain entry."""
    c, d, fake = _client()
    with patch.dict(sys.modules, {"keyring": fake}):
        _post(c, "/settings/cloud", data={
            "cloud_llm_provider": "openai",
            "cloud_llm_api_key": "sk-keep-me",
            "cloud_llm_model": "gpt-5",
        })
        # Second submission with blank key → only provider/model change
        _post(c, "/settings/cloud", data={
            "cloud_llm_provider": "anthropic",
            "cloud_llm_api_key": "",
            "cloud_llm_model": "claude-opus-4-7",
        })

    assert fake._store[("lumi", "cloud_llm_api_key")] == "sk-keep-me"
    on_disk = json.loads((d / "user_settings.json").read_text())
    assert on_disk["cloud_llm_provider"] == "anthropic"
    assert on_disk["cloud_llm_model"] == "claude-opus-4-7"
    assert on_disk["cloud_llm_api_key_set"] is True


def test_cloud_post_clear_key_with_confirmation_removes_from_keychain() -> None:
    """Audit #18 — clearing now requires `clear_confirm=clear` in the body."""
    c, d, fake = _client()
    with patch.dict(sys.modules, {"keyring": fake}):
        _post(c, "/settings/cloud", data={
            "cloud_llm_provider": "openai",
            "cloud_llm_api_key": "sk-to-be-cleared",
            "cloud_llm_model": "gpt-5",
        })
        _post(c, "/settings/cloud", data={
            "cloud_llm_provider": "openai",
            "cloud_llm_api_key": "",
            "cloud_llm_model": "gpt-5",
            "clear_key": "1",
            "clear_confirm": "clear",
        })

    assert ("lumi", "cloud_llm_api_key") not in fake._store
    on_disk = json.loads((d / "user_settings.json").read_text())
    assert on_disk["cloud_llm_api_key_set"] is False


def test_cloud_post_clear_key_without_confirmation_keeps_key(tmp_path: Path) -> None:
    """A hand-rolled form post with clear_key=1 but no clear_confirm must
    NOT remove the key. The UI does the typed-confirm; the server enforces
    it as defence-in-depth."""
    c, d, fake = _client()
    with patch.dict(sys.modules, {"keyring": fake}):
        _post(c, "/settings/cloud", data={
            "cloud_llm_provider": "openai",
            "cloud_llm_api_key": "sk-must-survive",
            "cloud_llm_model": "gpt-5",
        })
        _post(c, "/settings/cloud", data={
            "cloud_llm_provider": "openai",
            "cloud_llm_api_key": "",
            "cloud_llm_model": "gpt-5",
            "clear_key": "1",
            # NO clear_confirm sent
        })

    assert fake._store[("lumi", "cloud_llm_api_key")] == "sk-must-survive"
    on_disk = json.loads((d / "user_settings.json").read_text())
    assert on_disk["cloud_llm_api_key_set"] is True


def test_cloud_post_clear_key_wrong_confirmation_keeps_key() -> None:
    """Anything other than the literal "clear" (case-insensitive) is rejected."""
    c, d, fake = _client()
    with patch.dict(sys.modules, {"keyring": fake}):
        _post(c, "/settings/cloud", data={
            "cloud_llm_provider": "openai",
            "cloud_llm_api_key": "sk-keep",
            "cloud_llm_model": "gpt-5",
        })
        _post(c, "/settings/cloud", data={
            "clear_key": "1",
            "clear_confirm": "yes",        # wrong magic word
        })

    assert fake._store[("lumi", "cloud_llm_api_key")] == "sk-keep"


def test_cloud_post_rejects_unknown_provider() -> None:
    c, d, fake = _client()
    with patch.dict(sys.modules, {"keyring": fake}):
        _post(c, "/settings/cloud", data={"cloud_llm_provider": "not-a-real-provider"})
    on_disk = json.loads((d / "user_settings.json").read_text())
    assert on_disk["cloud_llm_provider"] == ""


def test_cloud_get_shows_masked_key_when_set() -> None:
    c, _, fake = _client()
    with patch.dict(sys.modules, {"keyring": fake}):
        _post(c, "/settings/cloud", data={
            "cloud_llm_provider": "anthropic",
            "cloud_llm_api_key": "sk-ant-api03-AbCdEfGh1234",
        })
        r = c.get("/settings/cloud")
    assert "sk-a" in r.text and "1234" in r.text     # masked indicator visible
    assert "sk-ant-api03-AbCdEfGh1234" not in r.text  # full key never rendered


# ── the page must report verified state, not a cached mirror ──────────────
#
# Found on the device 2026-08-06: user_settings.json said
# cloud_llm_api_key_set=True while nothing could read a key back, so the
# dashboard reported cloud routing as configured while every reply came from
# the local 1.5B model. The template branched on the cached boolean.


def _cloud_page(tmp_path, monkeypatch, *, flag: bool, stored_key: str) -> str:
    from fastapi.testclient import TestClient

    import lumi.runtime.secrets as sec
    from lumi.ui.web.app import create_app
    from lumi.ui.web.persistence import UserSettings, save_settings

    save_settings(
        tmp_path,
        UserSettings(
            onboarding_complete=True,
            cloud_llm_provider="gemini",
            cloud_llm_api_key_set=flag,
            cloud_routing_enabled=True,
        ),
    )
    monkeypatch.setattr(sec, "get_secret", lambda k: stored_key if k == "cloud_llm_api_key" else "")
    client = TestClient(create_app(tmp_path), follow_redirects=True)
    return client.get("/settings/cloud").text


def test_warns_when_the_flag_claims_a_key_that_cannot_be_read(tmp_path, monkeypatch) -> None:
    page = _cloud_page(tmp_path, monkeypatch, flag=True, stored_key="")
    assert "not actually active" in page
    assert "local model" in page


def test_no_warning_when_the_key_is_genuinely_readable(tmp_path, monkeypatch) -> None:
    page = _cloud_page(tmp_path, monkeypatch, flag=True, stored_key="AIzaREALKEY1234")
    assert "not actually active" not in page


def test_no_warning_when_nothing_is_configured(tmp_path, monkeypatch) -> None:
    """A fresh install shouldn't be scolded — the flag and the store agree."""
    page = _cloud_page(tmp_path, monkeypatch, flag=False, stored_key="")
    assert "not actually active" not in page


def test_clear_button_follows_the_readable_key_not_the_flag(tmp_path, monkeypatch) -> None:
    """Offering "Clear key" for a key that isn't there is a dead control."""
    stale = _cloud_page(tmp_path, monkeypatch, flag=True, stored_key="")
    assert "Clear key" not in stale

    real = _cloud_page(tmp_path, monkeypatch, flag=True, stored_key="AIzaREALKEY1234")
    assert "Clear key" in real
