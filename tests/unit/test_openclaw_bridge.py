"""Tests for the Ollama-tool-calling OpenClawBridge."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

from lumi.skills import openclaw_bridge as obridge
from lumi.skills.openclaw_bridge import OpenClawBridge


# ── helpers ─────────────────────────────────────────────────────────────────


def _resp(status: int, payload: dict | str) -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.raise_for_status.return_value = None
    if isinstance(payload, str):
        r.text = payload
        r.json.side_effect = ValueError("not json")
    else:
        r.json.return_value = payload
    return r


def _tool_call(name: str, args: dict) -> dict:
    return {"function": {"name": name, "arguments": args}}


# ── bridge.send: tool-calling flow ─────────────────────────────────────────


def test_send_executes_tool_then_returns_followup_reply() -> None:
    """Tool flow: model calls a tool, we run it, model composes final reply."""
    first = _resp(200, {"message": {"tool_calls": [_tool_call("lookup_wikipedia", {"topic": "Turing"})]}})
    second = _resp(200, {"message": {"content": "Turing was an English mathematician..."}})
    wiki = _resp(200, {"title": "Alan Turing", "extract": "English mathematician."})

    with patch("httpx.post", side_effect=[first, second]), \
         patch("httpx.get", return_value=wiki):
        reply = OpenClawBridge().send("Look up Alan Turing")

    assert reply is not None
    assert "Turing" in reply


def test_send_returns_none_when_model_didnt_call_tool() -> None:
    """No tool_calls in the response → return None so router falls through to LLM."""
    first = _resp(200, {"message": {"content": "Sure, what do you want?", "tool_calls": []}})
    with patch("httpx.post", return_value=first):
        assert OpenClawBridge().send("Tell me a joke") is None


def test_send_returns_none_on_first_http_error() -> None:
    with patch("httpx.post", side_effect=httpx.ConnectError("ollama down")):
        assert OpenClawBridge().send("anything") is None


def test_send_handles_arguments_as_json_string() -> None:
    """Some Ollama versions return tool args as a JSON string rather than a dict."""
    first = _resp(200, {"message": {"tool_calls": [
        {"function": {"name": "lookup_wikipedia", "arguments": json.dumps({"topic": "Python"})}}
    ]}})
    second = _resp(200, {"message": {"content": "Python is a language."}})
    wiki = _resp(200, {"title": "Python", "extract": "A language."})

    with patch("httpx.post", side_effect=[first, second]), \
         patch("httpx.get", return_value=wiki):
        reply = OpenClawBridge().send("Look up Python")

    assert reply == "Python is a language."


def test_url_swap_from_old_openclaw_gateway_url() -> None:
    """Existing config pointed at the openclaw gateway port (18789); the new
    bridge must transparently switch to Ollama's port (11434)."""
    b = OpenClawBridge(url="http://127.0.0.1:18789", token="lumi-dev-token")
    assert "11434" in b._url and "18789" not in b._url


# ── tool implementations ───────────────────────────────────────────────────


def test_weather_no_key_returns_clear_message() -> None:
    with patch.object(obridge.secrets, "get_secret", return_value=""):
        out = obridge._weather("London")
    assert "key" in out.lower()


def test_weather_404_returns_friendly_message() -> None:
    with patch.object(obridge.secrets, "get_secret", return_value="fakekey"), \
         patch("httpx.get", return_value=_resp(404, {})):
        out = obridge._weather("Nowhereville")
    assert "couldn't find" in out.lower()


def test_weather_success_returns_compact_json() -> None:
    payload = {
        "name": "London",
        "main": {"temp": 12.5, "feels_like": 11.0, "humidity": 78},
        "weather": [{"description": "light rain"}],
        "wind": {"speed": 4.2},
    }
    with patch.object(obridge.secrets, "get_secret", return_value="fakekey"), \
         patch("httpx.get", return_value=_resp(200, payload)):
        out = obridge._weather("London")
    parsed = json.loads(out)
    assert parsed["location"] == "London"
    assert parsed["temperature_c"] == 12.5
    assert parsed["conditions"] == "light rain"


def test_wikipedia_success() -> None:
    payload = {"title": "Alan Turing", "extract": "English mathematician and computer scientist."}
    with patch("httpx.get", return_value=_resp(200, payload)):
        out = obridge._wikipedia("Alan Turing")
    parsed = json.loads(out)
    assert parsed["title"] == "Alan Turing"
    assert "mathematician" in parsed["extract"]


def test_wikipedia_404_returns_friendly_message() -> None:
    with patch("httpx.get", return_value=_resp(404, {})):
        out = obridge._wikipedia("Nonexistent Person")
    assert "no wikipedia article" in out.lower()


def test_exchange_rate_success() -> None:
    payload = {"success": True, "result": 92.41, "info": {"rate": 0.9241}}
    with patch("httpx.get", return_value=_resp(200, payload)):
        out = obridge._exchange_rate(100, "USD", "EUR")
    parsed = json.loads(out)
    assert parsed["result"] == 92.41
    assert parsed["from"] == "USD"
    assert parsed["to"] == "EUR"


def test_news_extracts_titles_from_rss() -> None:
    rss = """<?xml version="1.0"?>
    <rss><channel>
      <title>BBC News</title>
      <item><title>EU climate deal</title></item>
      <item><title>Pacific summit closes</title></item>
      <item><title>Mars mission delayed</title></item>
    </channel></rss>"""
    with patch("httpx.get", return_value=_resp(200, rss)):
        out = obridge._news_headlines("bbc")
    parsed = json.loads(out)
    assert parsed["source"] == "bbc"
    assert "EU climate deal" in parsed["headlines"]
    assert "BBC News" not in parsed["headlines"]   # feed title skipped


def test_dispatch_unknown_tool() -> None:
    assert "unknown tool" in obridge._dispatch("not-a-real-tool", {}).lower()


# ── tools schema sanity ────────────────────────────────────────────────────


def test_tools_schema_has_four_functions() -> None:
    names = {t["function"]["name"] for t in obridge._TOOLS}
    assert names == {"get_weather", "lookup_wikipedia", "get_exchange_rate", "get_news_headlines"}


def test_tools_schema_required_fields_present() -> None:
    for t in obridge._TOOLS:
        fn = t["function"]
        assert fn["name"]
        assert fn["description"]
        assert "parameters" in fn
        assert fn["parameters"]["type"] == "object"
