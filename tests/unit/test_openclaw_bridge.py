"""Tests for the Ollama-tool-calling OpenClawBridge."""

from __future__ import annotations

import json
from pathlib import Path
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


def test_send_unknown_tool_name_returns_none() -> None:
    """If the model invents a tool name not in our dispatch table, fall through to LLM."""
    first = _resp(200, {"message": {"tool_calls": [
        {"function": {"name": "made_up_tool", "arguments": {}}}
    ]}})
    with patch("httpx.post", return_value=first):
        assert OpenClawBridge(skills_dir=_fake_skills_dir()).send("anything") is None


# ── Catalog discovery from manifest dir ─────────────────────────────────────


def _fake_skills_dir(tmp_path=None) -> Path:
    """Build an in-memory OpenClaw skills dir with our 4 active skills."""
    import tempfile  # noqa: PLC0415
    base = Path(tempfile.mkdtemp(prefix="lumi_catalog_"))
    for name, desc in [
        ("weather", "Get current weather"),
        ("wikipedia_lookup", "Look up a topic on Wikipedia"),
        ("currency_exchange", "Convert between currencies"),
        ("news_headlines", "Top news headlines"),
    ]:
        d = base / name
        d.mkdir()
        (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {desc}\n---\n\nBody.")
    return base


def test_parse_frontmatter_basic() -> None:
    fm = obridge._parse_frontmatter("---\nname: weather\ndescription: X\n---\nBody")
    assert fm["name"] == "weather"
    assert fm["description"] == "X"


def test_parse_frontmatter_list_values() -> None:
    fm = obridge._parse_frontmatter(
        "---\nname: x\nrequiredEnv:\n  - FOO\n  - BAR\n---\n"
    )
    assert fm["name"] == "x"
    assert fm["requiredEnv"] == ["FOO", "BAR"]


def test_parse_frontmatter_no_frontmatter() -> None:
    assert obridge._parse_frontmatter("just a body, no fence") == {}


def test_discover_skills_reads_each_manifest() -> None:
    d = _fake_skills_dir()
    out = obridge.discover_skills(d)
    names = {n for n, _ in out}
    assert names == {"weather", "wikipedia_lookup", "currency_exchange", "news_headlines"}


def test_discover_skills_missing_dir_returns_empty() -> None:
    assert obridge.discover_skills(Path("/this/does/not/exist")) == []


def test_build_tools_only_includes_skills_with_impls() -> None:
    """An unknown manifest is logged 'v2-only' and excluded from tool defs."""
    d = _fake_skills_dir()
    # Add a manifest with no Python impl
    extra = d / "made_up"
    extra.mkdir()
    (extra / "SKILL.md").write_text("---\nname: made_up\ndescription: Z\n---")

    b = OpenClawBridge(skills_dir=d)
    loaded = set(b.loaded_tools())
    assert "get_weather" in loaded
    assert "made_up" not in loaded   # no impl → excluded


def test_bridge_with_empty_catalog_returns_none() -> None:
    """Empty manifest dir → send() short-circuits to None without calling Ollama."""
    import tempfile  # noqa: PLC0415
    d = Path(tempfile.mkdtemp(prefix="lumi_empty_"))
    # Patch httpx.post so we'd notice if it was called
    with patch("httpx.post", side_effect=AssertionError("should not be called")):
        assert OpenClawBridge(skills_dir=d).send("anything") is None
