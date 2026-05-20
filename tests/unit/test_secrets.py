"""Tests for the OS-keychain secret store and the cloud-LLM settings migration."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from lumi.runtime import secrets


# ── mask() ──────────────────────────────────────────────────────────────────


def test_mask_empty_returns_not_set() -> None:
    assert secrets.mask("") == "(not set)"


def test_mask_short_secret_fully_hidden() -> None:
    assert secrets.mask("short") == "•••••"


def test_mask_long_secret_shows_first_and_last_4() -> None:
    s = "sk-ant-api03-AbCdEfGh12345678"
    out = secrets.mask(s)
    assert out.startswith("sk-a")
    assert out.endswith("5678")
    assert "…" in out


# ── set / get / delete via the keyring API ─────────────────────────────────


def _fake_keyring_module() -> MagicMock:
    """A stand-in for the `keyring` package — stores values in a dict."""
    store: dict[tuple[str, str], str] = {}
    fake = MagicMock()
    fake.set_password.side_effect = lambda svc, key, value: store.update({(svc, key): value})
    fake.get_password.side_effect = lambda svc, key: store.get((svc, key))
    def _delete(svc, key):
        store.pop((svc, key), None)
    fake.delete_password.side_effect = _delete
    fake._store = store  # for tests to peek
    return fake


def test_set_and_get_round_trip() -> None:
    fake = _fake_keyring_module()
    with patch.dict(sys.modules, {"keyring": fake}):
        secrets.set_secret("cloud_llm_api_key", "sk-ant-test")
        assert secrets.get_secret("cloud_llm_api_key") == "sk-ant-test"
    assert fake._store[("lumi", "cloud_llm_api_key")] == "sk-ant-test"


def test_set_empty_value_deletes() -> None:
    fake = _fake_keyring_module()
    with patch.dict(sys.modules, {"keyring": fake}):
        secrets.set_secret("k", "first-value")
        secrets.set_secret("k", "")          # empty value should clear
        assert secrets.get_secret("k") == ""


def test_get_returns_empty_when_unset() -> None:
    fake = _fake_keyring_module()
    with patch.dict(sys.modules, {"keyring": fake}):
        assert secrets.get_secret("never-set") == ""


def test_get_returns_empty_when_keyring_missing() -> None:
    """If `keyring` isn't installed, get_secret must return "" (not crash)."""
    with patch.dict(sys.modules, {"keyring": None}):
        assert secrets.get_secret("anything") == ""


def test_set_raises_when_keyring_missing() -> None:
    """set_secret must NOT silently swallow — caller needs to know it failed."""
    with patch.dict(sys.modules, {"keyring": None}):
        with pytest.raises(secrets.BackendUnavailable):
            secrets.set_secret("k", "v")


# ── migration: lift plaintext key out of user_settings.json into keychain ──


def test_migrates_plaintext_api_key_on_load(tmp_path: Path) -> None:
    """A user_settings.json with the legacy `cloud_llm_api_key` field should
    be quietly migrated: key moved to the keychain, JSON rewritten without it."""
    from lumi.ui.web.persistence import load_settings

    legacy = {
        "lumi_name": "Lumi",
        "cloud_llm_provider": "anthropic",
        "cloud_llm_api_key": "sk-ant-legacy-XYZ",     # plaintext, old format
    }
    (tmp_path / "user_settings.json").write_text(json.dumps(legacy))

    fake = _fake_keyring_module()
    with patch.dict(sys.modules, {"keyring": fake}):
        s = load_settings(tmp_path)

    # Plaintext field is gone; flag is set.
    on_disk = json.loads((tmp_path / "user_settings.json").read_text())
    assert "cloud_llm_api_key" not in on_disk
    assert on_disk["cloud_llm_api_key_set"] is True
    assert s.cloud_llm_api_key_set is True
    # And the keychain now holds the secret.
    assert fake._store[("lumi", "cloud_llm_api_key")] == "sk-ant-legacy-XYZ"


def test_migration_no_op_when_no_legacy_key(tmp_path: Path) -> None:
    """A clean settings file with the new schema should not be touched."""
    from lumi.ui.web.persistence import load_settings

    clean = {"lumi_name": "Lumi", "cloud_llm_provider": "anthropic", "cloud_llm_api_key_set": True}
    (tmp_path / "user_settings.json").write_text(json.dumps(clean))

    fake = _fake_keyring_module()
    with patch.dict(sys.modules, {"keyring": fake}):
        s = load_settings(tmp_path)

    # No keychain writes; flag is preserved.
    assert fake._store == {}
    assert s.cloud_llm_api_key_set is True
