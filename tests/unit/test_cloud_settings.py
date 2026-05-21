"""Tests for the cloud-LLM admin console settings."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

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
    return TestClient(create_app(d)), d, fake


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
        c.post("/settings/cloud", data={
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
        c.post("/settings/cloud", data={
            "cloud_llm_provider": "openai",
            "cloud_llm_api_key": "sk-keep-me",
            "cloud_llm_model": "gpt-5",
        })
        # Second submission with blank key → only provider/model change
        c.post("/settings/cloud", data={
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
        c.post("/settings/cloud", data={
            "cloud_llm_provider": "openai",
            "cloud_llm_api_key": "sk-to-be-cleared",
            "cloud_llm_model": "gpt-5",
        })
        c.post("/settings/cloud", data={
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
        c.post("/settings/cloud", data={
            "cloud_llm_provider": "openai",
            "cloud_llm_api_key": "sk-must-survive",
            "cloud_llm_model": "gpt-5",
        })
        c.post("/settings/cloud", data={
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
        c.post("/settings/cloud", data={
            "cloud_llm_provider": "openai",
            "cloud_llm_api_key": "sk-keep",
            "cloud_llm_model": "gpt-5",
        })
        c.post("/settings/cloud", data={
            "clear_key": "1",
            "clear_confirm": "yes",        # wrong magic word
        })

    assert fake._store[("lumi", "cloud_llm_api_key")] == "sk-keep"


def test_cloud_post_rejects_unknown_provider() -> None:
    c, d, fake = _client()
    with patch.dict(sys.modules, {"keyring": fake}):
        c.post("/settings/cloud", data={"cloud_llm_provider": "not-a-real-provider"})
    on_disk = json.loads((d / "user_settings.json").read_text())
    assert on_disk["cloud_llm_provider"] == ""


def test_cloud_get_shows_masked_key_when_set() -> None:
    c, _, fake = _client()
    with patch.dict(sys.modules, {"keyring": fake}):
        c.post("/settings/cloud", data={
            "cloud_llm_provider": "anthropic",
            "cloud_llm_api_key": "sk-ant-api03-AbCdEfGh1234",
        })
        r = c.get("/settings/cloud")
    assert "sk-a" in r.text and "1234" in r.text     # masked indicator visible
    assert "sk-ant-api03-AbCdEfGh1234" not in r.text  # full key never rendered
