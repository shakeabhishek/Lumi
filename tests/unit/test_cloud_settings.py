"""Tests for the cloud-LLM admin console settings."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from lumi.ui.web.app import create_app


def _client_with_dir() -> tuple[TestClient, Path]:
    d = Path(tempfile.mkdtemp(prefix="lumi_cloud_"))
    return TestClient(create_app(d)), d


def test_cloud_page_renders() -> None:
    c, _ = _client_with_dir()
    r = c.get("/settings/cloud")
    assert r.status_code == 200
    assert "Cloud LLM" in r.text
    # Each supported provider option must be present in the dropdown
    for provider in ("anthropic", "openai", "gemini"):
        assert f'value="{provider}"' in r.text


def test_cloud_post_persists_settings() -> None:
    c, d = _client_with_dir()
    r = c.post(
        "/settings/cloud",
        data={
            "cloud_llm_provider": "openai",
            "cloud_llm_api_key": "sk-test-123",
            "cloud_llm_model": "gpt-5",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    saved = json.loads((d / "user_settings.json").read_text())
    assert saved["cloud_llm_provider"] == "openai"
    assert saved["cloud_llm_api_key"] == "sk-test-123"
    assert saved["cloud_llm_model"] == "gpt-5"


def test_cloud_post_rejects_unknown_provider() -> None:
    c, d = _client_with_dir()
    c.post("/settings/cloud", data={"cloud_llm_provider": "not-a-real-provider"})
    saved = json.loads((d / "user_settings.json").read_text())
    # Unknown provider stored as empty string, not the bogus input.
    assert saved["cloud_llm_provider"] == ""


def test_cloud_post_strips_whitespace_and_lowercases_provider() -> None:
    c, d = _client_with_dir()
    c.post(
        "/settings/cloud",
        data={
            "cloud_llm_provider": "  ANTHROPIC  ",
            "cloud_llm_api_key": "  sk-ant-keep-me  ",
            "cloud_llm_model": "  claude-opus-4-7  ",
        },
    )
    saved = json.loads((d / "user_settings.json").read_text())
    assert saved["cloud_llm_provider"] == "anthropic"
    assert saved["cloud_llm_api_key"] == "sk-ant-keep-me"
    assert saved["cloud_llm_model"] == "claude-opus-4-7"


def test_cloud_provider_empty_means_local_only() -> None:
    c, d = _client_with_dir()
    c.post("/settings/cloud", data={"cloud_llm_provider": ""})
    saved = json.loads((d / "user_settings.json").read_text())
    assert saved["cloud_llm_provider"] == ""
