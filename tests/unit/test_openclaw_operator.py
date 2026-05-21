"""Tests for openclaw_operator — cloud-provider sync + revert.

Focus: the security-critical behaviour. The cloud API key is mirrored into
~/.openclaw/openclaw.json (OpenClaw doesn't support keychain refs yet), so
the file must be 0600 and writes must be atomic; clearing the key must
also purge the providers block, not just flip the default agent.
"""

from __future__ import annotations

import json
import stat
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch


def _fake_keyring(values: dict[str, str] | None = None) -> MagicMock:
    store = dict(values or {})
    fake = MagicMock()
    fake.set_password.side_effect = lambda svc, k, v: store.update({(svc, k): v})
    fake.get_password.side_effect = lambda svc, k: store.get((svc, k))
    def _delete(svc, k):
        store.pop((svc, k), None)
    fake.delete_password.side_effect = _delete
    fake._store = store
    return fake


def _seed_config(home: Path) -> Path:
    """Write a minimal OpenClaw config and return its path."""
    cfg_dir = home / ".openclaw"
    cfg_dir.mkdir(parents=True)
    cfg = cfg_dir / "openclaw.json"
    cfg.write_text(json.dumps({"models": {"providers": {}}, "agents": {}}))
    return cfg


def test_sync_writes_provider_with_0600_perms(tmp_path: Path, monkeypatch) -> None:
    """The plaintext API key file must be unreadable by anyone but the owner."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    cfg_path = _seed_config(tmp_path)

    fake = _fake_keyring({("lumi", "cloud_llm_api_key"): "sk-ant-xyz"})
    with (
        patch.dict(sys.modules, {"keyring": fake}),
        patch("lumi.skills.openclaw_operator._restart_gateway", return_value=True),
    ):
        from lumi.skills.openclaw_operator import sync_to_openclaw  # noqa: PLC0415

        ok, msg = sync_to_openclaw("anthropic", "claude-opus-4-7")

    assert ok, msg
    written = json.loads(cfg_path.read_text())
    assert written["models"]["providers"]["anthropic"]["apiKey"] == "sk-ant-xyz"

    # 0600 only — no group, no other read.
    mode = cfg_path.stat().st_mode & 0o777
    assert mode == stat.S_IRUSR | stat.S_IWUSR, f"expected 0600, got {oct(mode)}"


def test_sync_write_is_atomic(tmp_path: Path, monkeypatch) -> None:
    """A crash mid-write must not leave openclaw.json partially populated."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    cfg_path = _seed_config(tmp_path)
    original_content = cfg_path.read_text()

    fake = _fake_keyring({("lumi", "cloud_llm_api_key"): "sk-ant-xyz"})

    # Make os.replace blow up so we can verify the original file is untouched.
    with (
        patch.dict(sys.modules, {"keyring": fake}),
        patch("lumi.skills.openclaw_operator._restart_gateway", return_value=True),
        patch("lumi.skills.openclaw_operator.os.replace", side_effect=OSError("disk full")),
    ):
        from lumi.skills.openclaw_operator import sync_to_openclaw  # noqa: PLC0415

        try:
            sync_to_openclaw("anthropic")
        except OSError:
            pass

    assert cfg_path.read_text() == original_content, "config corrupted by failed write"
    # No leftover tmpfile in the .openclaw directory either.
    leftover = list(cfg_path.parent.glob("openclaw.json.*.tmp"))
    assert leftover == [], f"tmpfile not cleaned up: {leftover}"


def test_revert_purges_all_cloud_provider_blocks(tmp_path: Path, monkeypatch) -> None:
    """Clearing the cloud key in /settings/cloud must wipe the providers
    block — not just flip the agent default. Otherwise the API key
    survives on disk after the user explicitly cleared it."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    cfg_path = tmp_path / ".openclaw" / "openclaw.json"
    cfg_path.parent.mkdir(parents=True)
    cfg_path.write_text(json.dumps({
        "models": {"providers": {
            "anthropic": {"apiKey": "sk-ant-xyz", "baseUrl": "x"},
            "openai":    {"apiKey": "sk-openai-zzz", "baseUrl": "y"},
            "custom":    {"apiKey": "should-stay", "baseUrl": "z"},   # not in _PROVIDERS
        }},
        "agents": {"defaults": {"model": {"primary": "anthropic/claude-opus-4-7"}}},
    }))

    with patch("lumi.skills.openclaw_operator._restart_gateway", return_value=True):
        from lumi.skills.openclaw_operator import sync_to_openclaw  # noqa: PLC0415

        ok, msg = sync_to_openclaw("")        # empty provider → revert

    assert ok, msg
    cfg = json.loads(cfg_path.read_text())
    providers = cfg["models"]["providers"]
    # The two cloud providers we know about are gone — keys included.
    assert "anthropic" not in providers
    assert "openai" not in providers
    # A non-Lumi provider entry is left alone (we only purge ones we manage).
    assert providers["custom"]["apiKey"] == "should-stay"
    # Agent default flipped back to local.
    assert cfg["agents"]["defaults"]["model"]["primary"] == "ollama/qwen2.5:7b"


def test_sync_without_keychain_key_returns_clear_error(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    _seed_config(tmp_path)
    fake = _fake_keyring()       # empty store

    with patch.dict(sys.modules, {"keyring": fake}):
        from lumi.skills.openclaw_operator import sync_to_openclaw  # noqa: PLC0415

        ok, msg = sync_to_openclaw("anthropic")

    assert not ok
    assert "keychain" in msg.lower()


def test_ensure_config_perms_tightens_existing_leaky_config(tmp_path: Path, monkeypatch) -> None:
    """Legacy installs may have a world-readable openclaw.json on disk with an
    API key in it. On next launch, ensure_config_perms() must lock it down
    without otherwise touching the file."""
    import os  # noqa: PLC0415

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    cfg_path = tmp_path / ".openclaw" / "openclaw.json"
    cfg_path.parent.mkdir(parents=True)
    cfg_path.write_text(json.dumps({
        "models": {"providers": {"anthropic": {"apiKey": "sk-ant-leaky", "baseUrl": "x"}}},
    }))
    os.chmod(cfg_path, 0o644)         # leaky

    from lumi.skills.openclaw_operator import ensure_config_perms  # noqa: PLC0415

    ensure_config_perms()

    mode = cfg_path.stat().st_mode & 0o777
    assert mode == stat.S_IRUSR | stat.S_IWUSR
    # File contents untouched — we only tightened perms.
    cfg = json.loads(cfg_path.read_text())
    assert cfg["models"]["providers"]["anthropic"]["apiKey"] == "sk-ant-leaky"


def test_ensure_config_perms_noop_when_no_cloud_providers(tmp_path: Path, monkeypatch) -> None:
    """A config with no cloud provider blocks (e.g. local-only Ollama default)
    isn't worth tightening — leave perms alone so we don't fight pi-gen / user."""
    import os  # noqa: PLC0415

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    cfg_path = tmp_path / ".openclaw" / "openclaw.json"
    cfg_path.parent.mkdir(parents=True)
    cfg_path.write_text(json.dumps({"models": {"providers": {}}}))
    os.chmod(cfg_path, 0o644)

    from lumi.skills.openclaw_operator import ensure_config_perms  # noqa: PLC0415

    ensure_config_perms()
    # Mode unchanged.
    assert (cfg_path.stat().st_mode & 0o777) == 0o644


def test_sync_missing_config_file_returns_clear_error(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    # No ~/.openclaw/openclaw.json present.

    fake = _fake_keyring({("lumi", "cloud_llm_api_key"): "sk-ant-xyz"})
    with patch.dict(sys.modules, {"keyring": fake}):
        from lumi.skills.openclaw_operator import sync_to_openclaw  # noqa: PLC0415

        ok, msg = sync_to_openclaw("anthropic")

    assert not ok
    assert "not found" in msg.lower()
