"""Tool-calling bridge — Ollama with skill tool definitions.

We previously proxied through OpenClaw's `/v1/chat/completions` gateway,
but the gateway does NOT forward skill manifests as OpenAI tool definitions
to the underlying model — so qwen2.5:1.5b just hallucinated answers without
ever calling a skill. The Phase 1 viability test used the direct Ollama
`/api/chat` path with tool definitions and passed at 94%. This bridge does
that, in Python, for the Lumi runtime.

For each call:
  1. POST to /api/chat with our tool definitions and the user's transcript.
  2. If the model emits a tool_call, execute the corresponding skill function.
  3. POST back the tool result so the model can compose a natural reply.
  4. Return that reply. If the model never called a tool, return None so
     the skill router falls through to its plain-LLM path with full history.

API keys live in the OS keychain via lumi.runtime.secrets, never on disk
in plaintext.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from ..log import get_logger
from ..runtime import secrets

log = get_logger(__name__)


def _tool(name: str, description: str, properties: dict[str, dict], required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


_TOOLS: list[dict] = [
    _tool(
        "get_weather",
        "Get current weather conditions for a city or location",
        {
            "location": {
                "type": "string",
                "description": "City name, optionally with country, e.g. 'London' or 'Tokyo, JP'",
            }
        },
        ["location"],
    ),
    _tool(
        "lookup_wikipedia",
        "Look up a topic on Wikipedia and return a one-paragraph summary",
        {"topic": {"type": "string", "description": "Topic to search for"}},
        ["topic"],
    ),
    _tool(
        "get_exchange_rate",
        "Convert an amount from one currency to another using live exchange rates",
        {
            "amount": {"type": "number", "description": "Amount to convert"},
            "from_currency": {"type": "string", "description": "ISO 4217 source code, e.g. 'USD'"},
            "to_currency": {"type": "string", "description": "ISO 4217 target code, e.g. 'EUR'"},
        },
        ["amount", "from_currency", "to_currency"],
    ),
    _tool(
        "get_news_headlines",
        "Get the top 3-5 news headlines from a public RSS source",
        {
            "source": {
                "type": "string",
                "description": "One of: bbc, npr, hn, reuters. Default 'bbc'.",
            }
        },
        [],
    ),
]


# ── Tool implementations ────────────────────────────────────────────────────


def _weather(location: str) -> str:
    key = secrets.get_secret("openweathermap_api_key")
    if not key:
        return "OpenWeatherMap API key is not configured. Run `lumi keys set openweathermap` to store one."
    try:
        r = httpx.get(
            "https://api.openweathermap.org/data/2.5/weather",
            params={"q": location, "appid": key, "units": "metric"},
            timeout=10.0,
        )
        if r.status_code == 404:
            return f"Couldn't find a location called {location!r}."
        r.raise_for_status()
        d = r.json()
        return json.dumps(
            {
                "location": d.get("name"),
                "temperature_c": d["main"]["temp"],
                "feels_like_c": d["main"]["feels_like"],
                "humidity_pct": d["main"]["humidity"],
                "conditions": d["weather"][0]["description"],
                "wind_mps": d["wind"]["speed"],
            }
        )
    except httpx.HTTPError as exc:
        return f"Weather lookup failed: {exc}"


def _wikipedia(topic: str) -> str:
    try:
        slug = topic.strip().replace(" ", "_")
        r = httpx.get(
            f"https://en.wikipedia.org/api/rest_v1/page/summary/{slug}",
            headers={"User-Agent": "Lumi/1.0 (https://github.com/lumi)"},
            timeout=10.0,
            follow_redirects=True,
        )
        if r.status_code == 404:
            return f"No Wikipedia article found for {topic!r}."
        r.raise_for_status()
        d = r.json()
        return json.dumps({"title": d.get("title"), "extract": d.get("extract", "")[:600]})
    except httpx.HTTPError as exc:
        return f"Wikipedia lookup failed: {exc}"


def _exchange_rate(amount: float, from_code: str, to_code: str) -> str:
    try:
        r = httpx.get(
            "https://api.exchangerate.host/convert",
            params={"from": from_code.upper(), "to": to_code.upper(), "amount": amount},
            timeout=10.0,
        )
        r.raise_for_status()
        d = r.json()
        if not d.get("success", True) or d.get("result") is None:
            return f"Couldn't convert {from_code} to {to_code}."
        return json.dumps(
            {
                "amount": amount,
                "from": from_code.upper(),
                "to": to_code.upper(),
                "result": round(float(d["result"]), 4),
                "rate": d.get("info", {}).get("rate"),
            }
        )
    except httpx.HTTPError as exc:
        return f"Exchange rate lookup failed: {exc}"


_NEWS_FEEDS = {
    "bbc": "https://feeds.bbci.co.uk/news/world/rss.xml",
    "npr": "https://feeds.npr.org/1001/rss.xml",
    "hn": "https://news.ycombinator.com/rss",
    "reuters": "https://feeds.reuters.com/Reuters/worldNews",
}


def _news_headlines(source: str = "bbc") -> str:
    import re  # noqa: PLC0415

    url = _NEWS_FEEDS.get(source.lower(), _NEWS_FEEDS["bbc"])
    try:
        r = httpx.get(
            url, timeout=10.0, follow_redirects=True,
            headers={"User-Agent": "Lumi/1.0"},
        )
        r.raise_for_status()
        # Tiny RSS title extractor — avoids pulling in feedparser.
        titles = re.findall(r"<title>(.*?)</title>", r.text, flags=re.IGNORECASE | re.DOTALL)
        # First title is usually the feed name; skip it.
        items = [t.strip() for t in titles[1:6] if t.strip()]
        return json.dumps({"source": source.lower(), "headlines": items})
    except httpx.HTTPError as exc:
        return f"News fetch failed: {exc}"


def _dispatch(name: str, args: dict[str, Any]) -> str:
    if name == "get_weather":
        return _weather(str(args.get("location", "")))
    if name == "lookup_wikipedia":
        return _wikipedia(str(args.get("topic", "")))
    if name == "get_exchange_rate":
        return _exchange_rate(
            float(args.get("amount", 1)),
            str(args.get("from_currency", "")),
            str(args.get("to_currency", "")),
        )
    if name == "get_news_headlines":
        return _news_headlines(str(args.get("source", "bbc")))
    return f"Unknown tool: {name}"


# ── Bridge ──────────────────────────────────────────────────────────────────


class OpenClawBridge:
    """Single-turn tool-calling client backed by Ollama.

    Kept the class name for backwards compat with the skill router and config;
    the underlying transport is now Ollama, not the OpenClaw gateway.
    """

    def __init__(
        self,
        url: str = "http://127.0.0.1:11434",
        token: str = "",                # noqa: ARG002  unused; kept for router signature compat
        model: str = "qwen2.5:1.5b",
        timeout: float = 30.0,
    ) -> None:
        # `url` historically pointed at the OpenClaw gateway. If the caller
        # passes an openclaw URL (port 18789), silently swap it for Ollama's.
        if "18789" in url or "openclaw" in url:
            url = "http://127.0.0.1:11434"
        self._url = url.rstrip("/")
        self._model = model
        self._timeout = timeout

    def send(self, text: str) -> str | None:
        """Return the model's reply, or None to defer to the router's LLM path.

        Returns None when:
          - the model didn't call any tool AND produced no useful text
          - any HTTP or parse error occurs
        """
        try:
            first = httpx.post(
                f"{self._url}/api/chat",
                json={
                    "model": self._model,
                    "messages": [{"role": "user", "content": text}],
                    "tools": _TOOLS,
                    "stream": False,
                },
                timeout=self._timeout,
            )
            first.raise_for_status()
            msg = first.json().get("message", {})
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("bridge.first_call_failed", error=str(exc))
            return None

        tool_calls = msg.get("tool_calls") or []
        if not tool_calls:
            log.info("bridge.no_tool_call")
            return None

        call = tool_calls[0]
        name = call.get("function", {}).get("name", "")
        args = call.get("function", {}).get("arguments") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {}

        log.info("bridge.tool_call", tool=name, args=args)
        tool_result = _dispatch(name, args)

        try:
            second = httpx.post(
                f"{self._url}/api/chat",
                json={
                    "model": self._model,
                    "messages": [
                        {"role": "user", "content": text},
                        msg,
                        {"role": "tool", "content": tool_result},
                    ],
                    "stream": False,
                },
                timeout=self._timeout,
            )
            second.raise_for_status()
            reply = second.json().get("message", {}).get("content", "").strip()
            log.info("bridge.ok", tool=name, chars=len(reply))
            return reply or None
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("bridge.followup_failed", error=str(exc), tool=name)
            return None
