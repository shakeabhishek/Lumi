"""Tests for CSRFMiddleware — protects every mutating route on the dashboard
from cross-origin form posts once Lumi is reachable over a LAN (audit #21)."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from lumi.ui.web.app import create_app


def _fake_keyring() -> MagicMock:
    store: dict[tuple[str, str], str] = {}
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
def client() -> TestClient:
    d = Path(tempfile.mkdtemp(prefix="lumi_csrf_"))
    return TestClient(create_app(d))


def test_first_get_sets_csrf_cookie(client: TestClient) -> None:
    """A fresh browser visit gets a token cookie that subsequent POSTs must echo."""
    r = client.get("/")
    assert r.status_code == 200
    assert client.cookies.get("csrf_token")
    # Inspect the SameSite attribute via the cookie jar — httpx strips
    # Set-Cookie from r.headers once it's merged into the jar.
    cookie = next(
        (c for c in client.cookies.jar if c.name == "csrf_token"),
        None,
    )
    assert cookie is not None
    # CookieJar stashes extension attributes in cookie._rest; SameSite is one.
    same_site = (cookie._rest or {}).get("SameSite", "") or (cookie._rest or {}).get("samesite", "")
    assert same_site.lower() == "strict"


def test_post_without_token_returns_403(client: TestClient) -> None:
    """The whole point: bare cross-origin POST is rejected."""
    # No warm-up GET — no cookie, no header, no field.
    r = client.post("/settings/personality", data={"system_prompt_override": "evil"})
    assert r.status_code == 403


def test_post_with_token_in_form_field_succeeds(client: TestClient) -> None:
    client.get("/")
    token = client.cookies.get("csrf_token", "")
    r = client.post(
        "/settings/personality",
        data={"csrf_token": token, "system_prompt_override": "ok"},
        follow_redirects=False,
    )
    assert r.status_code in (200, 303)


def test_post_with_token_in_header_succeeds(client: TestClient) -> None:
    """HTMX / JS callers use the X-CSRF-Token header instead of a form field."""
    client.get("/")
    token = client.cookies.get("csrf_token", "")
    fake = _fake_keyring()
    import sys  # noqa: PLC0415
    with patch.dict(sys.modules, {"keyring": fake}):
        r = client.post(
            "/settings/personality",
            data={"system_prompt_override": "ok"},
            headers={"X-CSRF-Token": token},
            follow_redirects=False,
        )
    assert r.status_code in (200, 303)


def test_post_with_wrong_token_returns_403(client: TestClient) -> None:
    """A stale or attacker-supplied token fails the constant-time compare."""
    client.get("/")
    r = client.post(
        "/settings/personality",
        data={"csrf_token": "not-the-real-token", "system_prompt_override": "x"},
    )
    assert r.status_code == 403


def test_route_handler_still_sees_form_fields_after_csrf_check(client: TestClient) -> None:
    """The CSRF middleware reads the request body to extract the token. It
    must not consume the form — the route still needs to read the other
    fields. Regression test against the original 'body drained' bug."""
    client.get("/")
    token = client.cookies.get("csrf_token", "")
    fake = _fake_keyring()
    import sys  # noqa: PLC0415
    with patch.dict(sys.modules, {"keyring": fake}):
        r = client.post(
            "/settings/cloud",
            data={
                "csrf_token": token,
                "cloud_llm_provider": "openai",
                "cloud_llm_api_key": "sk-survives-csrf-check",
                "cloud_llm_model": "gpt-5",
            },
            follow_redirects=False,
        )
    assert r.status_code == 303
    # If the body had been drained, the route would have seen blank
    # cloud_llm_api_key and the keychain would still be empty.
    assert fake._store.get(("lumi", "cloud_llm_api_key")) == "sk-survives-csrf-check"


def test_api_context_bypass_does_not_require_token(client: TestClient) -> None:
    """The send-to-Lumi hotkey daemon is a local trusted process with no
    browser — /api/context is in the bypass list so it can POST without
    a token."""
    # No GET warm-up: simulate the daemon firing immediately on a cold start.
    r = client.post("/api/context", json={"text": "hello"})
    # Whatever the route returns, it must NOT 403.
    assert r.status_code != 403


def test_get_requests_are_never_blocked(client: TestClient) -> None:
    """Reading state should never require a CSRF token. Only mutating
    methods are guarded."""
    for path in ("/", "/chat", "/settings/personality", "/skills"):
        assert client.get(path).status_code in (200, 303, 304)
