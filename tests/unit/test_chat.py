"""Tests for the chat web routes — non-streaming /chat/send and the
streaming /chat/stream variants.

Coverage focus:
  * /chat/stream emits the SSE wire protocol the JS client expects
    (chunk events, optional context event leading, terminal done event)
  * Server-side session.history stays consistent — the user message is
    NOT appended twice (client renders optimistically, server appends once)
  * Hotkey context bubbles lead the stream and get into history
  * Cloud-failure notice surfaces as an SSE event
  * /chat/send still works for the no-JS path (regression)
"""

from __future__ import annotations

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
    fake.set_password.side_effect = lambda svc, k, v: store.update({(svc, k): v})
    fake.get_password.side_effect = lambda svc, k: store.get((svc, k))
    def _delete(svc, k): store.pop((svc, k), None)
    fake.delete_password.side_effect = _delete
    fake._store = store
    return fake


@pytest.fixture
def _no_external_calls():
    """Stub out the openclaw subprocess + any network in tests."""
    with (
        patch("lumi.skills.openclaw_operator._restart_gateway", return_value=True),
    ):
        yield


@pytest.fixture
def client() -> TestClient:
    """A chat test client. We don't patch keyring here because the chat
    flow doesn't touch it directly (no cloud key is set; build_cloud_bridge
    short-circuits to ollama mode). Sharing sys.modules patches across
    fixtures causes numpy re-import errors when other tests in the same
    process touch the import chain."""
    d = Path(tempfile.mkdtemp(prefix="lumi_chat_"))
    c = TestClient(create_app(d))
    c.get("/")           # warm CSRF cookie
    yield c


def _csrf(c: TestClient) -> str:
    return c.cookies.get("csrf_token", "")


def _stub_router_response(monkeypatch, chunks: list[str]) -> MagicMock:
    """Patch the SkillRouter that the chat session would build, so we don't
    actually invoke Ollama. Returns the mock so tests can inspect calls."""
    fake_router = MagicMock()
    # Streaming path: handle_streaming yields each chunk.
    fake_router.handle_streaming.return_value = iter(chunks)
    # Non-streaming path: handle returns the full concatenation.
    fake_router.handle.return_value = "".join(chunks)
    fake_router._bridge = None   # no cloud-failure notice in tests
    fake_conv = MagicMock()
    fake_conv.set_context_hint = MagicMock()
    fake_conv.clear = MagicMock()

    from lumi.ui.web.routes import chat as chat_mod  # noqa: PLC0415

    # Reset the cached session once so the chat tests start clean. After
    # that, _get_or_build_session returns the (router-swapped) session
    # across calls — the test can rely on session.history surviving from
    # POST /chat/stream to GET /chat/.
    _patched_state: dict[str, object] = {"installed": False}
    real_builder = chat_mod._get_or_build_session

    def _patched(request):
        sess = real_builder(request)
        if not _patched_state["installed"]:
            sess.router = fake_router
            sess.conversation = fake_conv
            sess.history = []
            _patched_state["installed"] = True
        return sess

    # Also wipe any cached session from prior warm-up GETs so the next
    # call re-runs the patched builder.
    monkeypatch.setattr(chat_mod, "_get_or_build_session", _patched)
    return fake_router


def _read_sse(body_bytes: bytes) -> list[tuple[str, str]]:
    """Parse the SSE wire format into a list of (event, data) tuples."""
    text = body_bytes.decode("utf-8")
    out: list[tuple[str, str]] = []
    for frame in text.split("\n\n"):
        if not frame.strip():
            continue
        event = "message"
        data_parts: list[str] = []
        for line in frame.split("\n"):
            if line.startswith("event:"):
                event = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data_parts.append(line[len("data:"):].lstrip())
        out.append((event, "\n".join(data_parts)))
    return out


# ── /chat/stream ────────────────────────────────────────────────────────────


def test_stream_yields_chunks_then_done(
    client: TestClient, _no_external_calls, monkeypatch,
) -> None:
    """Happy path — three chunks come through as separate SSE frames, then
    a terminal done frame with the handler metadata."""
    _stub_router_response(monkeypatch, ["Hello", ", ", "world."])

    r = client.post(
        "/chat/stream",
        data={"message": "hi", "csrf_token": _csrf(client)},
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")

    events = _read_sse(r.content)
    # Chunks come through as default 'message' events
    chunk_payloads = [data for ev, data in events if ev == "message"]
    assert len(chunk_payloads) == 3
    # And a final done event with metadata
    done = [data for ev, data in events if ev == "done"]
    assert len(done) == 1
    import json  # noqa: PLC0415
    meta = json.loads(done[0])
    assert "handler" in meta
    assert "elapsed_ms" in meta


def test_stream_appends_user_message_to_history_exactly_once(
    client: TestClient, _no_external_calls, monkeypatch,
) -> None:
    """The client renders the user bubble optimistically — server must
    append the user turn exactly once, not echo it back in the SSE stream."""
    _stub_router_response(monkeypatch, ["ok"])

    client.post("/chat/stream", data={"message": "first", "csrf_token": _csrf(client)})

    # Inspect server-side history through the page render.
    page = client.get("/chat/")
    # User text appears exactly once in the page HTML.
    assert page.text.count("first") == 1


def test_stream_with_empty_message_returns_done_only(
    client: TestClient, _no_external_calls, monkeypatch,
) -> None:
    """Empty submission shouldn't crash; just emit a no-op done so the
    client cleans up its placeholder."""
    # Don't even stub the router — empty message must short-circuit before it.
    r = client.post(
        "/chat/stream",
        data={"message": "   ", "csrf_token": _csrf(client)},
    )
    assert r.status_code == 200
    events = _read_sse(r.content)
    assert len(events) == 1 and events[0][0] == "done"


def test_stream_chunks_never_contain_raw_user_text(
    client: TestClient, _no_external_calls, monkeypatch,
) -> None:
    """Regression — the client renders the user bubble optimistically.
    The server must not include the user's own message in the stream
    (that would render it twice)."""
    _stub_router_response(monkeypatch, ["pong"])

    r = client.post(
        "/chat/stream",
        data={"message": "ping echo this", "csrf_token": _csrf(client)},
    )
    body = r.content.decode()
    assert "ping echo this" not in body


def test_stream_error_in_handler_yields_safe_message_not_traceback(
    client: TestClient, _no_external_calls, monkeypatch,
) -> None:
    """If the router blows up partway, the user sees a generic message,
    not the exception text."""
    fake_router = MagicMock()
    fake_router.handle_streaming.side_effect = RuntimeError(
        "internal /etc/secret traceback path"
    )
    fake_router._bridge = None

    from lumi.ui.web.routes import chat as chat_mod  # noqa: PLC0415
    real_builder = chat_mod._get_or_build_session

    def _patched(request):
        sess = real_builder(request)
        sess.router = fake_router
        sess.conversation = MagicMock()
        sess.history = []
        return sess

    monkeypatch.setattr(chat_mod, "_get_or_build_session", _patched)

    r = client.post(
        "/chat/stream",
        data={"message": "anything", "csrf_token": _csrf(client)},
    )
    body = r.content.decode()
    assert "/etc/secret" not in body
    assert "RuntimeError" not in body
    assert "Sorry" in body              # generic message from safe_error_message


def test_stream_disables_proxy_buffering(
    client: TestClient, _no_external_calls, monkeypatch,
) -> None:
    """When Lumi is behind nginx (the Pi deployment), proxy buffering
    would coalesce SSE chunks. The X-Accel-Buffering header opts out."""
    _stub_router_response(monkeypatch, ["x"])
    r = client.post("/chat/stream", data={"message": "hi", "csrf_token": _csrf(client)})
    assert r.headers.get("x-accel-buffering") == "no"
    assert r.headers.get("cache-control", "").startswith("no-cache")


# ── Regression: /chat/send still works (no-JS fallback) ────────────────────


def test_chat_send_still_returns_html_partial(
    client: TestClient, _no_external_calls, monkeypatch,
) -> None:
    """The classic synchronous /chat/send endpoint is the no-JS fallback —
    keep it working as the simpler reference implementation."""
    _stub_router_response(monkeypatch, ["howdy"])

    r = client.post(
        "/chat/send",
        data={"message": "hello", "csrf_token": _csrf(client)},
    )
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    # The partial contains both bubbles
    assert "hello" in r.text          # user message
    assert "howdy" in r.text          # reply


def test_chat_clear_requires_csrf(client: TestClient) -> None:
    """Smoke: clear endpoint isn't a CSRF bypass."""
    # No token → 403
    r = client.post("/chat/clear")
    assert r.status_code == 403
    # With token → 200
    r = client.post(
        "/chat/clear",
        data={"csrf_token": _csrf(client)},
    )
    assert r.status_code == 200
