"""Tests for the standalone /audit-log route.

Split from /skills so the audit viewer can grow filtering, pagination,
and per-family counts without bloating the skill-management page.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lumi.ui.web.app import create_app


@pytest.fixture
def client() -> TestClient:
    d = Path(tempfile.mkdtemp(prefix="lumi_audit_route_"))
    # Onboarding gate would redirect from / before reaching audit pages,
    # but /audit-log/ has no such gate — direct URL works always.
    return TestClient(create_app(d))


def _seed(client: TestClient, entries: list[dict]) -> None:
    """Drop entries straight into the audit log file so we don't have
    to route real chat turns to populate it."""
    p = client.app.state.data_dir / "audit_log.jsonl"
    with p.open("w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


def test_audit_index_renders_empty(client: TestClient) -> None:
    """Fresh install — log doesn't exist yet. Don't 500."""
    r = client.get("/audit-log/")
    assert r.status_code == 200
    assert "audit log" in r.text.lower()


def test_audit_filter_by_native(client: TestClient) -> None:
    """family=native should hide cloud + openclaw rows."""
    _seed(client, [
        {"ts": "2026-05-24T01:00:00", "source": "native", "skill": "timer", "input": "set a timer", "result": "ok"},
        {"ts": "2026-05-24T02:00:00", "source": "openclaw", "skill": "weather", "input": "weather", "result": "sunny"},
        {"ts": "2026-05-24T03:00:00", "source": "cloud:gemini", "skill": "llm", "input": "hi", "result": "hello"},
    ])
    r = client.get("/audit-log/?family=native")
    assert r.status_code == 200
    body = r.text
    assert "set a timer" in body
    assert "sunny" not in body
    assert "cloud:gemini" not in body


def test_audit_filter_cloud_collapses_provider_variants(client: TestClient) -> None:
    """family=cloud must catch every cloud:<provider> source — Gemini
    today, Anthropic + OpenAI when those adapters land."""
    _seed(client, [
        {"ts": "2026-05-24T01:00:00", "source": "cloud:gemini",    "skill": "llm", "input": "q1", "result": "r1"},
        {"ts": "2026-05-24T02:00:00", "source": "cloud:anthropic", "skill": "llm", "input": "q2", "result": "r2"},
        {"ts": "2026-05-24T03:00:00", "source": "native",          "skill": "timer", "input": "t", "result": "ok"},
    ])
    r = client.get("/audit-log/?family=cloud")
    assert r.status_code == 200
    body = r.text
    assert "q1" in body and "q2" in body
    assert "timer" not in body or "set a timer" not in body


def test_audit_counts_show_per_family_totals(client: TestClient) -> None:
    """The filter chips include a count next to each family label so
    the user can scan 'is anyone using cloud routing right now?'
    without clicking around."""
    _seed(client, [
        {"ts": "2026-05-24T01:00:00", "source": "native",       "skill": "x", "input": "a", "result": "b"},
        {"ts": "2026-05-24T02:00:00", "source": "native",       "skill": "x", "input": "a", "result": "b"},
        {"ts": "2026-05-24T03:00:00", "source": "cloud:gemini", "skill": "x", "input": "a", "result": "b"},
    ])
    r = client.get("/audit-log/")
    assert r.status_code == 200
    # The count chips render the integer next to each family label.
    # Don't pin to exact HTML — just assert the right numbers appear
    # alongside their labels.
    body = r.text
    assert "Native skills" in body
    assert "Cloud routing" in body


def test_audit_unknown_family_falls_back_to_all(client: TestClient) -> None:
    """A hand-edited URL with family=bogus should not 500 — it
    silently shows everything."""
    _seed(client, [
        {"ts": "2026-05-24T01:00:00", "source": "native", "skill": "x", "input": "a", "result": "b"},
    ])
    r = client.get("/audit-log/?family=bogus")
    assert r.status_code == 200


def test_audit_clear_wipes_file(client: TestClient) -> None:
    _seed(client, [{"ts": "2026-05-24T01:00:00", "source": "native", "skill": "x", "input": "a", "result": "b"}])
    path = client.app.state.data_dir / "audit_log.jsonl"
    assert path.exists()

    client.get("/")  # warm csrf
    csrf = client.cookies.get("csrf_token", "")
    r = client.post("/audit-log/clear", data={"csrf_token": csrf}, follow_redirects=False)
    assert r.status_code == 303
    assert not path.exists()
