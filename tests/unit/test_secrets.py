"""Tests for the OS-keychain secret store and the cloud-LLM settings migration."""

from __future__ import annotations

import json
import sys
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


def test_set_falls_back_to_file_when_keyring_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """On a headless device with no OS keychain (e.g. the Pi appliance),
    set_secret must fall back to the 0600 file store rather than raising —
    otherwise cloud setup is impossible on that hardware."""
    monkeypatch.setenv("LUMI_DATA_DIR", str(tmp_path))
    with patch.dict(sys.modules, {"keyring": None}):
        assert secrets.backend_kind() == "file"
        secrets.set_secret("k", "v")
        assert secrets.get_secret("k") == "v"
    secrets_file = tmp_path / secrets.SECRETS_FILENAME
    assert secrets_file.exists()
    assert oct(secrets_file.stat().st_mode)[-3:] == "600"


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


# ── `lumi keys set` name validation ──────────────────────────────────────

from typer.testing import CliRunner  # noqa: E402

import lumi.runtime.secrets as secrets_module  # noqa: E402
from lumi.main import app  # noqa: E402


def test_keys_set_rejects_an_unknown_name(monkeypatch, tmp_path) -> None:
    """Found on the device 2026-08-06: data/.secrets.json held a single entry
    named `k` while `cloud_llm_api_key` was absent, so the cloud LLM had been
    silently falling back to the local 1.5B model for every conversational
    reply. `lumi keys set` accepted any name and still printed "Stored ...",
    so a typo left the operator believing the key was configured."""
    stored: dict[str, str] = {}
    monkeypatch.setattr(secrets_module, "set_secret", stored.__setitem__)
    result = CliRunner().invoke(app, ["keys", "set", "k"])
    assert result.exit_code != 0
    assert stored == {}, "an unknown key name must store nothing"
    assert "Unknown key name" in result.output


def test_keys_delete_accepts_an_unknown_name(monkeypatch) -> None:
    """Validation is write-only. Blocking delete would make a stray entry —
    exactly the `k` this guard exists because of — impossible to clean up
    through the CLI."""
    deleted: list[str] = []
    monkeypatch.setattr(secrets_module, "delete_secret", deleted.append)
    result = CliRunner().invoke(app, ["keys", "delete", "k"])
    assert result.exit_code == 0, result.output
    assert deleted == ["k"]


def test_keys_set_accepts_a_known_name(monkeypatch) -> None:
    stored: dict[str, str] = {}
    monkeypatch.setattr(secrets_module, "set_secret", stored.__setitem__)
    result = CliRunner().invoke(
        app, ["keys", "set", "cloud_llm_api_key"], input="some-value\n",
    )
    assert result.exit_code == 0, result.output
    assert stored.get("cloud_llm_api_key") == "some-value"


# ── the file backend must never destroy secrets it didn't touch ───────────
#
# Found on the device 2026-08-06: data/.secrets.json contained a single entry
# named `k` with cloud_llm_api_key gone, and the cloud LLM had been silently
# falling back to the local 1.5B model as a result. Two mechanisms could do
# that, and both are now closed.


@pytest.fixture
def file_store(tmp_path, monkeypatch):
    """Force the file backend into tmp_path (the dev laptop has a keychain)."""
    import lumi.runtime.secrets as sec

    monkeypatch.setattr(sec, "_keychain_ok", lambda: False)
    monkeypatch.setattr(sec, "_secrets_file", lambda: tmp_path / ".secrets.json")
    return tmp_path / ".secrets.json"


def test_set_preserves_other_secrets(file_store) -> None:
    from lumi.runtime.secrets import get_secret, set_secret

    set_secret("cloud_llm_api_key", "cloud-value")
    set_secret("gmail_app_password", "gmail-value")
    assert get_secret("cloud_llm_api_key") == "cloud-value"
    assert get_secret("gmail_app_password") == "gmail-value"


def test_a_corrupt_store_is_never_silently_overwritten(file_store) -> None:
    """The exact destruction path. `set_secret` does read-modify-write; if the
    read swallows a JSON error and returns {}, the write persists ONLY the new
    key and erases every other secret. It must refuse instead."""
    from lumi.runtime.secrets import SecretStoreUnreadable, set_secret

    file_store.write_text("{this is not json", encoding="utf-8")
    with pytest.raises(SecretStoreUnreadable):
        set_secret("k", "whatever")
    # The damaged file is left exactly as it was, for a human to inspect —
    # better than a store that looks fine and is missing credentials.
    assert file_store.read_text(encoding="utf-8") == "{this is not json"


def test_a_non_object_store_is_also_refused(file_store) -> None:
    from lumi.runtime.secrets import SecretStoreUnreadable, set_secret

    file_store.write_text('["a", "list"]', encoding="utf-8")
    with pytest.raises(SecretStoreUnreadable):
        set_secret("k", "v")


def test_delete_skips_rather_than_wiping_a_corrupt_store(file_store) -> None:
    """delete_secret still swallows errors (callers use it for cleanup and
    factory reset), but must not turn "delete one key" into "delete all"."""
    from lumi.runtime.secrets import delete_secret

    file_store.write_text("{broken", encoding="utf-8")
    delete_secret("cloud_llm_api_key")  # must not raise
    assert file_store.read_text(encoding="utf-8") == "{broken"


def test_absent_and_empty_files_are_treated_as_legitimately_empty(file_store) -> None:
    """"No file yet" and "unparseable file" are different situations — first
    run must still work."""
    from lumi.runtime.secrets import get_secret, set_secret

    assert get_secret("anything") == ""
    set_secret("first", "value")          # no file existed
    assert get_secret("first") == "value"

    file_store.write_text("   \n", encoding="utf-8")
    set_secret("second", "value")         # whitespace-only, not corrupt
    assert get_secret("second") == "value"


def test_reads_stay_forgiving_when_the_store_is_damaged(file_store) -> None:
    """A corrupt store must not raise on the READ path — that would take down
    a voice turn over a secret that may not even be configured."""
    from lumi.runtime.secrets import get_secret

    file_store.write_text("{broken", encoding="utf-8")
    assert get_secret("cloud_llm_api_key") == ""


def test_concurrent_writers_do_not_lose_each_others_keys(file_store) -> None:
    """Three processes touch this file — lumi-web, lumi-voice, and the CLI.
    Unlocked read-modify-write means two concurrent set_secret calls both read
    the old store and the second write drops the first's key."""
    import threading

    from lumi.runtime.secrets import get_secret, set_secret

    names = [f"key_{i}" for i in range(24)]
    barrier = threading.Barrier(len(names))

    def writer(name: str) -> None:
        barrier.wait()          # maximise overlap
        set_secret(name, f"value-of-{name}")

    threads = [threading.Thread(target=writer, args=(n,)) for n in names]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    missing = [n for n in names if get_secret(n) != f"value-of-{n}"]
    assert not missing, f"lost {len(missing)} of {len(names)} concurrent writes: {missing[:5]}"
