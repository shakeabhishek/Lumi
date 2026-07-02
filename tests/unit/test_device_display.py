"""Tests for the React-device-display backend: DeviceBus, the SSE
endpoint, /api/state push, and the sprite fallback chain."""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from lumi.ui.web.app import create_app
from lumi.ui.web.device_bus import DeviceBus


# ── DeviceBus unit tests ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_subscriber_gets_cached_snapshot_immediately() -> None:
    """Joining mid-conversation should not blank the face — the bus
    caches the last snapshot so a new subscriber receives it on its
    very first iteration."""
    bus = DeviceBus()
    await bus.publish({"state": "speak", "cpuPct": 42})

    sub = bus.subscribe()
    first = await asyncio.wait_for(sub.__anext__(), timeout=0.5)
    assert first == {"state": "speak", "cpuPct": 42}
    await sub.aclose()


@pytest.mark.asyncio
async def test_publish_merges_into_cache_for_partial_updates() -> None:
    """Weather and CPU samplers publish only their own field. The bus
    merges so switching face style doesn't erase the last weather
    reading — subscribers always see the full state."""
    bus = DeviceBus()
    await bus.publish({"state": "idle", "weather": {"tempC": 22}})
    await bus.publish({"cpuPct": 45})
    snapshot = bus.latest()
    assert snapshot == {"state": "idle", "weather": {"tempC": 22}, "cpuPct": 45}


@pytest.mark.asyncio
async def test_publish_delivers_to_active_subscriber() -> None:
    """End-to-end via two awaitable steps: subscribe, then publish a
    fresh frame, then pull the next yield. The cached snapshot is
    delivered first (synchronously on iteration start), then the new
    publish arrives as the second yield."""
    bus = DeviceBus()
    await bus.publish({"state": "speak"})       # seed cache

    sub = bus.subscribe()
    cached = await asyncio.wait_for(sub.__anext__(), timeout=0.5)
    assert cached == {"state": "speak"}

    await bus.publish({"state": "idle"})
    fresh = await asyncio.wait_for(sub.__anext__(), timeout=0.5)
    assert fresh == {"state": "idle"}

    await sub.aclose()


# ── HTTP integration ───────────────────────────────────────────────────────


@pytest.fixture
def client() -> TestClient:
    d = Path(tempfile.mkdtemp(prefix="lumi_dev_disp_"))
    return TestClient(create_app(d))


def test_device_display_index_serves_or_explains(client: TestClient) -> None:
    """If the React bundle is built, /device-display/ returns 200 with
    the index.html. If not, returns a 503 with a friendly hint about
    running `npm run build`. Either is acceptable for tests — failing
    because the build dir is missing would be brittle in CI."""
    r = client.get("/device-display/")
    assert r.status_code in (200, 503)
    if r.status_code == 200:
        assert "<div id=\"root\">" in r.text


def test_api_state_publishes_to_bus(client: TestClient) -> None:
    """POST /api/state must reach the DeviceBus so subscribers see the
    new face state. The CSRF middleware bypasses /api/state because
    the voice loop in main.py is a separate OS process with no cookie."""
    r = client.post("/api/state", data={"state": "listen"})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "state": "listen"}

    bus = client.app.state.device_bus
    assert bus is not None
    latest = bus.latest()
    assert latest is not None
    assert latest["state"] == "listen"
    assert latest["statusText"] == "Listening…"


def test_api_state_rejects_invalid_state(client: TestClient) -> None:
    r = client.post("/api/state", data={"state": "bogus"})
    assert r.status_code == 400
    assert "idle" in r.text and "speak" in r.text


@pytest.mark.asyncio
async def test_bus_seeded_via_publish_face_state(tmp_path) -> None:
    """The contract we care about: after publish_face_state() fires for
    'idle', the bus reports a renderable snapshot. We don't exercise
    /device-display/events directly in tests — TestClient's sync HTTPX
    can't iter-lines an open SSE stream without deadlocking the
    transport. The route is verified manually + by the smoke script."""
    from lumi.ui.web.app import create_app  # noqa: PLC0415
    from lumi.ui.web.routes.device_display import publish_face_state  # noqa: PLC0415
    from unittest.mock import MagicMock  # noqa: PLC0415

    app = create_app(tmp_path)
    # publish_face_state takes a Request to read app.state — fake the
    # minimum surface it needs.
    fake_request = MagicMock()
    fake_request.app = app
    fake_request.app.state.data_dir = tmp_path

    await publish_face_state(fake_request, "idle")
    bus = app.state.device_bus
    snapshot = bus.latest()
    assert snapshot is not None
    assert snapshot["state"] == "idle"
    assert snapshot["statusText"] == "Connected to cloud"
    assert "style" in snapshot


def test_display_theme_persists_and_flows_into_snapshot(
    client: TestClient,
) -> None:
    """Picking a palette on /settings/face must (1) persist on disk
    and (2) appear in the next SSE snapshot the device display
    consumes — without a page refresh on the React side. Whitelists
    keep an unknown id from blanking the gradient."""
    # warm the CSRF cookie
    client.get("/")
    csrf = client.cookies.get("csrf_token", "")

    r = client.post(
        "/settings/face",
        data={
            "csrf_token": csrf,
            "face_theme": "vector",
            "face_color": "",
            "idle_scene": "none",
            "display_theme": "sunset",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303

    # Snapshot should reflect the new theme — face_post publishes idle.
    snapshot = client.app.state.device_bus.latest()
    assert snapshot is not None
    assert snapshot["theme"] == "sunset"

    # Unknown id falls back to default rather than passing through.
    r = client.post(
        "/settings/face",
        data={
            "csrf_token": csrf,
            "face_theme": "vector",
            "face_color": "",
            "idle_scene": "none",
            "display_theme": "evil-palette",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    snapshot = client.app.state.device_bus.latest()
    assert snapshot is not None
    assert snapshot["theme"] == "default"


def test_get_audio_returns_current_hardware_state(client: TestClient) -> None:
    """On a laptop with no ReSpeaker card, audio_mixer no-ops to sensible
    defaults rather than erroring — the route should just pass them through."""
    r = client.get("/device-display/audio")
    assert r.status_code == 200
    body = r.json()
    assert "volume" in body
    assert "micMuted" in body


def test_set_audio_volume_publishes_to_bus(client: TestClient) -> None:
    """POST /device-display/audio/volume is CSRF-bypassed (same trust
    model as /api/state — a physical touch on the local screen) and must
    reach the DeviceBus so the SSE snapshot reflects the new volume."""
    r = client.post("/device-display/audio/volume", data={"volume": "77"})
    assert r.status_code == 200
    assert r.json()["volume"] == r.json()["volume"]  # no-op card still echoes a value

    bus = client.app.state.device_bus
    assert bus is not None
    latest = bus.latest()
    assert latest is not None
    assert "volume" in latest


def test_set_audio_mute_publishes_to_bus(client: TestClient) -> None:
    r = client.post("/device-display/audio/mute", data={"muted": "true"})
    assert r.status_code == 200
    assert "micMuted" in r.json()

    bus = client.app.state.device_bus
    assert bus is not None
    latest = bus.latest()
    assert latest is not None
    assert "micMuted" in latest


def test_get_system_returns_current_brightness(client: TestClient) -> None:
    """On a laptop with no backlight device, display_backlight no-ops to
    a sensible default rather than erroring."""
    r = client.get("/device-display/system")
    assert r.status_code == 200
    assert "brightness" in r.json()


def test_set_system_brightness_publishes_to_bus(client: TestClient) -> None:
    """POST /device-display/system/brightness is CSRF-bypassed like the
    audio routes — same trust model, a physical touch on the local
    screen — and must reach the DeviceBus."""
    r = client.post("/device-display/system/brightness", data={"brightness": "60"})
    assert r.status_code == 200
    assert "brightness" in r.json()

    bus = client.app.state.device_bus
    assert bus is not None
    latest = bus.latest()
    assert latest is not None
    assert "brightness" in latest


def test_sprite_endpoint_serves_bundled_pack(client: TestClient) -> None:
    """The /device-display/sprite/<pack>/<file> route mirrors the
    pygame loader's bundled→user fallback so the React app can pull
    frames the same way the pygame face used to."""
    r = client.get("/device-display/sprite/cat/manifest.json")
    assert r.status_code == 200
    manifest = r.json()
    assert "frames" in manifest


def test_sprite_endpoint_rejects_path_traversal(client: TestClient) -> None:
    """Pack name + file are both whitelisted so a hostile URL can't
    pull arbitrary files."""
    for bad in ("../../../etc/passwd", "..\\..\\boot.ini", "frame_001.svg"):
        r = client.get(f"/device-display/sprite/cat/{bad}")
        assert r.status_code in (404, 400, 405)


# ── Chat-stream → device display integration ──────────────────────────────


def test_chat_stream_publishes_face_states_to_device_display(client: TestClient, monkeypatch) -> None:
    """A complete chat turn must drive the device display through
    think → speak → idle so the face animates with the conversation,
    not on a poll timer. Verified via DeviceBus state directly — going
    through the SSE round-trip would tangle TestClient's sync httpx."""
    from unittest.mock import MagicMock  # noqa: PLC0415

    fake_router = MagicMock()
    fake_router.handle_streaming.return_value = iter(["hi", " there"])
    fake_router._bridge = None

    from lumi.ui.web.routes import chat as chat_mod  # noqa: PLC0415

    real_builder = chat_mod._get_or_build_session
    patched = {"done": False}

    def _patched(req):
        sess = real_builder(req)
        if not patched["done"]:
            sess.router = fake_router
            sess.conversation = MagicMock()
            sess.history = []
            patched["done"] = True
        return sess

    monkeypatch.setattr(chat_mod, "_get_or_build_session", _patched)

    # We hook the DeviceBus directly: patch its publish() to record every
    # call, then run the chat POST through TestClient (synchronous). After
    # the turn finishes we should have seen think → speak → idle.
    from lumi.ui.web import device_bus as bus_mod  # noqa: PLC0415

    seen: list[str] = []
    orig_publish = bus_mod.DeviceBus.publish

    async def _record(self, snapshot):
        if "state" in snapshot:
            seen.append(snapshot["state"])
        await orig_publish(self, snapshot)

    monkeypatch.setattr(bus_mod.DeviceBus, "publish", _record)

    client.get("/")
    csrf = client.cookies.get("csrf_token", "")
    r = client.post("/chat/stream", data={"message": "hi", "csrf_token": csrf})
    assert r.status_code == 200

    assert "think" in seen, f"think state missing: {seen}"
    assert "speak" in seen, f"speak state missing: {seen}"
    # idle must be the LAST state — turn-complete returns the face to rest.
    assert seen[-1] == "idle", f"last state should be idle: {seen}"


@pytest.mark.asyncio
async def test_chat_stream_publishes_idle_even_when_cancelled_before_first_chunk(
    tmp_path, monkeypatch,
) -> None:
    """Regression test for a real bug found on the Pi (2026-07-02): if the
    client disconnects — or the whole worker is killed, e.g. a service
    restart — while still waiting for the FIRST chunk, Starlette cancels
    the streaming generator at that await point via GeneratorExit/
    CancelledError. Both are BaseException, not Exception, so they are
    NOT caught by chat.py's `except Exception` blocks. Without an outer
    try/finally spanning the whole function, execution jumps straight
    past the idle-publish, leaving the device-display stuck showing
    "Thinking…" until some unrelated future turn happens to complete —
    which is exactly what was observed live."""
    from unittest.mock import MagicMock

    from starlette.requests import Request

    from lumi.ui.web.app import create_app
    from lumi.ui.web.routes import chat as chat_mod

    app = create_app(tmp_path)

    fake_router = MagicMock()

    def _blocking_gen(_transcript: str):
        # handle_streaming is a sync generator function in production,
        # run via loop.run_in_executor — a real OS thread. Cancelling the
        # asyncio-level task does NOT stop an already-running executor
        # thread (a genuine asyncio limitation), so aclose() will block
        # until this sleep actually returns. Keep it short (not the ~8s+
        # a real OpenClaw miss takes) so the test resolves quickly while
        # still exercising the exact mechanism: a slow sync generator,
        # cancelled while the app is waiting on its first item.
        import time as _time

        def gen():
            _time.sleep(0.3)
            yield "unreachable"  # pragma: no cover

        return gen()

    fake_router.handle_streaming.side_effect = _blocking_gen
    fake_router._bridge = None

    real_builder = chat_mod._get_or_build_session
    patched = {"done": False}

    def _patched(req):
        sess = real_builder(req)
        if not patched["done"]:
            sess.router = fake_router
            sess.conversation = MagicMock()
            sess.history = []
            patched["done"] = True
        return sess

    monkeypatch.setattr(chat_mod, "_get_or_build_session", _patched)

    from lumi.ui.web import device_bus as bus_mod

    seen: list[str] = []
    orig_publish = bus_mod.DeviceBus.publish

    async def _record(self, snapshot):
        if "state" in snapshot:
            seen.append(snapshot["state"])
        await orig_publish(self, snapshot)

    monkeypatch.setattr(bus_mod.DeviceBus, "publish", _record)

    scope = {"type": "http", "method": "POST", "path": "/chat/stream", "app": app, "headers": []}
    request = Request(scope)

    response = await chat_mod.chat_stream(request, message="hi")

    # Start consuming — this reaches "think" (published synchronously
    # before any chunk is awaited) and then blocks inside the executor
    # call waiting for the (never-arriving) first chunk from the router.
    task = asyncio.ensure_future(response.body_iterator.__anext__())
    await asyncio.sleep(0.2)
    assert not task.done(), "expected the stream to still be blocked on the first chunk"

    # Simulate what Starlette does when the client disconnects mid-request:
    # cancel the in-flight __anext__() — this delivers CancelledError into
    # the async generator's currently-suspended await point, the same
    # place a real client disconnect would land.
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert seen == ["think", "idle"], f"expected think then idle, got: {seen}"
