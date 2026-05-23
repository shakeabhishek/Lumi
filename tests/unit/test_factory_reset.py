"""Tests for /settings/data/reset — the 'Forget everything' factory reset.

The privacy promise is that this button restores the device to first-boot.
That includes purging:
  * Every file in data_dir
  * Every known keychain entry (cloud LLM key, OpenWeatherMap key)
  * The plaintext API-key mirror in ~/.openclaw/openclaw.json
  * The in-memory chat session (and its Pseudonymizer mapping)
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from lumi.ui.web.app import create_app


def _fake_keyring(values: dict[str, str] | None = None) -> MagicMock:
    store = dict(values or {})
    fake = MagicMock()
    fake.set_password.side_effect = lambda svc, k, v: store.update({(svc, k): v})
    fake.get_password.side_effect = lambda svc, k: store.get((svc, k))
    def _delete(svc, k): store.pop((svc, k), None)
    fake.delete_password.side_effect = _delete
    fake._store = store
    return fake


@pytest.fixture(autouse=True)
def _no_real_gateway_restart():
    with patch("lumi.skills.openclaw_operator._restart_gateway", return_value=True):
        yield


@pytest.fixture
def env(tmp_path: Path, monkeypatch):
    """A TestClient + a fake HOME so ~/.openclaw/openclaw.json lives in tmp."""
    data_dir = tmp_path / "data"
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    c = TestClient(create_app(data_dir))
    c.get("/")                # warm CSRF cookie
    return c, data_dir, home


def _csrf(c: TestClient) -> str:
    return c.cookies.get("csrf_token", "")


# ── data_dir wipe ──────────────────────────────────────────────────────────


def test_reset_wipes_all_files_under_data_dir(env) -> None:
    c, data_dir, _ = env
    # Seed every category of user file.
    (data_dir / "user_settings.json").write_text('{"lumi_name":"Atlas"}')
    (data_dir / "audit_log.jsonl").write_text('{"x":1}\n')
    (data_dir / "owner_embedding.npy").write_text("voice bio")
    (data_dir / "notes.jsonl").write_text("notes")
    (data_dir / "journal.jsonl").write_text("journal")
    (data_dir / "chroma").mkdir()
    (data_dir / "chroma" / "lumi.db").write_text("vectors")

    r = c.post("/settings/data/reset", data={"csrf_token": _csrf(c)}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/onboarding/1"

    # data_dir itself stays; its children are gone.
    assert data_dir.exists()
    assert list(data_dir.iterdir()) == []


# ── keychain wipe ──────────────────────────────────────────────────────────


def test_reset_deletes_known_keychain_entries(env) -> None:
    """Without this, API keys survived 'Forget everything' — silently
    re-enabling cloud mode on next launch."""
    c, _, _ = env
    fake = _fake_keyring({
        ("lumi", "cloud_llm_api_key"): "sk-ant-survivor",
        ("lumi", "openweathermap_api_key"): "owm-survivor",
        ("lumi", "unrelated_key"): "stays — we only purge known names",
    })

    with patch.dict(sys.modules, {"keyring": fake}):
        r = c.post("/settings/data/reset", data={"csrf_token": _csrf(c)}, follow_redirects=False)
    assert r.status_code == 303

    assert ("lumi", "cloud_llm_api_key") not in fake._store
    assert ("lumi", "openweathermap_api_key") not in fake._store
    # Untracked keys are intentionally left alone — keychain is shared
    # with other apps, we only touch names we wrote.
    assert ("lumi", "unrelated_key") in fake._store


def test_reset_survives_missing_keychain_backend(env) -> None:
    """If the keychain backend is unreachable (CI sandbox, etc.) the rest
    of the reset must still complete."""
    c, data_dir, _ = env
    (data_dir / "user_settings.json").write_text("{}")

    with patch.dict(sys.modules, {"keyring": None}):
        r = c.post("/settings/data/reset", data={"csrf_token": _csrf(c)}, follow_redirects=False)
    assert r.status_code == 303
    assert list(data_dir.iterdir()) == []        # data_dir still wiped


# ── OpenClaw config wipe ───────────────────────────────────────────────────


def test_reset_purges_cloud_provider_block_from_openclaw_config(env) -> None:
    """The factory reset privacy promise extends to the plaintext key mirror
    in ~/.openclaw/openclaw.json — clearing the user data without clearing
    that file would leave the API key on disk after a 'Forget everything'."""
    c, _, home = env
    oc_dir = home / ".openclaw"
    oc_dir.mkdir()
    (oc_dir / "openclaw.json").write_text(json.dumps({
        "models": {"providers": {
            "anthropic": {"apiKey": "sk-ant-leak", "baseUrl": "x"},
        }},
        "agents": {"defaults": {"model": {"primary": "anthropic/claude-opus-4-7"}}},
    }))

    r = c.post("/settings/data/reset", data={"csrf_token": _csrf(c)}, follow_redirects=False)
    assert r.status_code == 303

    cfg = json.loads((oc_dir / "openclaw.json").read_text())
    assert "anthropic" not in cfg.get("models", {}).get("providers", {})
    # And the agent default flipped back to local Ollama
    assert cfg["agents"]["defaults"]["model"]["primary"].startswith("ollama/")


def test_reset_skips_openclaw_step_if_config_absent(env) -> None:
    """Users who never enabled cloud may not have ~/.openclaw at all —
    don't crash; just wipe the rest."""
    c, data_dir, _ = env
    (data_dir / "user_settings.json").write_text("{}")

    r = c.post("/settings/data/reset", data={"csrf_token": _csrf(c)}, follow_redirects=False)
    assert r.status_code == 303
    assert list(data_dir.iterdir()) == []


# ── In-memory state wipe ───────────────────────────────────────────────────


def test_reset_drops_cached_chat_session(env) -> None:
    """The Pseudonymizer's mapping lives on the chat session in-process.
    Reset must drop the cached session so a subsequent turn rebuilds from
    a fresh user file — otherwise the new (post-reset) session would
    inherit the old mapping."""
    c, _, _ = env

    # Force a chat session to be cached by hitting the chat page.
    c.get("/chat/")
    assert hasattr(c.app.state, "chat_session")

    r = c.post("/settings/data/reset", data={"csrf_token": _csrf(c)}, follow_redirects=False)
    assert r.status_code == 303
    assert not hasattr(c.app.state, "chat_session")


# ── End-to-end: real onboarding flow after reset ───────────────────────────


def test_after_reset_user_is_routed_back_to_onboarding_step_1(env) -> None:
    c, data_dir, _ = env
    (data_dir / "user_settings.json").write_text(
        '{"lumi_name":"Atlas","onboarding_complete":true}'
    )

    r = c.post("/settings/data/reset", data={"csrf_token": _csrf(c)}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/onboarding/1"

    # Loading settings now returns DEFAULTS (lumi_name="Lumi", onboarding incomplete)
    from lumi.ui.web.persistence import load_settings  # noqa: PLC0415
    fresh = load_settings(data_dir)
    assert fresh.lumi_name == "Lumi"
    assert fresh.onboarding_complete is False


def test_reset_requires_csrf(env) -> None:
    """Defence-in-depth: factory reset is the worst possible CSRF target
    (any cross-origin tab could nuke the user's data). Confirm the CSRF
    middleware applies here too."""
    c, _, _ = env
    r = c.post("/settings/data/reset")        # no token
    assert r.status_code == 403
