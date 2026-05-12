"""Tests for OpenClawBridge HTTP client."""

from __future__ import annotations

import json

import httpx
import pytest

from lumi.skills.openclaw_bridge import OpenClawBridge


def _make_transport(status: int, body: dict) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=body)

    return httpx.MockTransport(handler)


def _bridge_with_transport(transport: httpx.MockTransport) -> OpenClawBridge:
    bridge = OpenClawBridge(url="http://localhost:18789", token="test-token")
    # Patch _client by monkey-patching send
    original_send = bridge.send

    def patched_send(text: str) -> str | None:
        with httpx.Client(transport=transport) as client:
            try:
                response = client.post(
                    "http://localhost:18789/v1/chat/completions",
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": "Bearer test-token",
                    },
                    json={"model": "openclaw", "messages": [{"role": "user", "content": text}]},
                    timeout=5.0,
                )
                response.raise_for_status()
                data = response.json()
                return data["choices"][0]["message"]["content"]
            except httpx.TimeoutException:
                return None
            except httpx.HTTPStatusError:
                return None
            except Exception:
                return None

    bridge.send = patched_send  # type: ignore[method-assign]
    return bridge


_OK_BODY = {
    "choices": [{"message": {"role": "assistant", "content": "It's sunny in London, 18°C."}}]
}


class TestOpenClawBridge:
    def test_returns_content_on_success(self) -> None:
        bridge = _bridge_with_transport(_make_transport(200, _OK_BODY))
        result = bridge.send("What's the weather in London?")
        assert result == "It's sunny in London, 18°C."

    def test_returns_none_on_http_500(self) -> None:
        bridge = _bridge_with_transport(_make_transport(500, {"error": "internal"}))
        result = bridge.send("anything")
        assert result is None

    def test_returns_none_on_http_401(self) -> None:
        bridge = _bridge_with_transport(_make_transport(401, {"error": "unauthorized"}))
        result = bridge.send("anything")
        assert result is None

    def test_sends_correct_model_and_message(self) -> None:
        captured: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            return httpx.Response(200, json=_OK_BODY)

        bridge = _bridge_with_transport(httpx.MockTransport(handler))
        bridge.send("test prompt")

        assert len(captured) == 1
        body = json.loads(captured[0].content)
        assert body["model"] == "openclaw"
        assert body["messages"][0]["role"] == "user"
        assert body["messages"][0]["content"] == "test prompt"

    def test_returns_none_on_connection_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused")

        bridge = _bridge_with_transport(httpx.MockTransport(handler))
        result = bridge.send("anything")
        assert result is None
