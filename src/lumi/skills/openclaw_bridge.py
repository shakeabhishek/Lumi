"""Tool-calling bridge — OpenClaw manifests as catalog, Ollama as runtime.

V1 hybrid design (honest about what each piece does):

  * **OpenClaw is the catalog.** Skill manifests live in
    `~/.openclaw/workspace/skills/<name>/SKILL.md`. The frontmatter (name,
    description, required env vars) is the single source of truth for
    *what skills exist*. Drop a new manifest into that directory and Lumi
    sees it on next start.

  * **Ollama is the runtime.** V1's qwen2.5:1.5b doesn't reliably follow
    OpenClaw's text-based orchestration format (designed for Claude/GPT),
    but it does score 94% on OpenAI-style tool calling. So we convert each
    manifest into a function tool definition and let Ollama drive the
    model with our tool defs.

  * **Lumi provides the implementation.** Each manifest in the catalog
    needs a matching Python implementation in this file's `_SKILL_IMPLS`
    registry. Manifests without an impl are listed in `lumi skills` but
    log a "V2-only" warning and aren't exposed to the model.

When V2's cloud LLM lands, we'll route through OpenClaw's gateway with a
model strong enough to drive its orchestration — and the same manifests
work without changes.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from ..log import get_logger
from ..runtime import secrets

log = get_logger(__name__)

OPENCLAW_SKILLS_DIR = Path.home() / ".openclaw" / "workspace" / "skills"


# ── Tool implementations ────────────────────────────────────────────────────


def _weather(location: str) -> str:
    key = secrets.get_secret("openweathermap_api_key")
    if not key:
        return "OpenWeatherMap API key is not configured. Run `lumi keys set openweathermap_api_key`."
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
    url = _NEWS_FEEDS.get(source.lower(), _NEWS_FEEDS["bbc"])
    try:
        r = httpx.get(
            url, timeout=10.0, follow_redirects=True,
            headers={"User-Agent": "Lumi/1.0"},
        )
        r.raise_for_status()
        titles = re.findall(r"<title>(.*?)</title>", r.text, flags=re.IGNORECASE | re.DOTALL)
        # First title is usually the feed name; skip it.
        items = [t.strip() for t in titles[1:6] if t.strip()]
        return json.dumps({"source": source.lower(), "headlines": items})
    except httpx.HTTPError as exc:
        return f"News fetch failed: {exc}"


# ── Skill registry: maps OpenClaw skill name → tool schema + python impl ───
#
# Adding a new skill requires:
#   1. A SKILL.md in ~/.openclaw/workspace/skills/<name>/  (catalog entry)
#   2. An entry in this dict (runtime impl)
# The OpenClaw catalog drives discovery. This registry drives execution.

_SKILL_IMPLS: dict[str, dict[str, Any]] = {
    "weather": {
        "tool_name": "get_weather",
        "parameters": {
            "location": {
                "type": "string",
                "description": "City name, optionally with country, e.g. 'London' or 'Tokyo, JP'",
            }
        },
        "required": ["location"],
        "callable": lambda args: _weather(str(args.get("location", ""))),
    },
    "wikipedia_lookup": {
        "tool_name": "lookup_wikipedia",
        "parameters": {
            "topic": {"type": "string", "description": "Topic to search for on Wikipedia"},
        },
        "required": ["topic"],
        "callable": lambda args: _wikipedia(str(args.get("topic", ""))),
    },
    "currency_exchange": {
        "tool_name": "get_exchange_rate",
        "parameters": {
            "amount": {"type": "number", "description": "Amount to convert"},
            "from_currency": {"type": "string", "description": "ISO 4217 source code, e.g. 'USD'"},
            "to_currency": {"type": "string", "description": "ISO 4217 target code, e.g. 'EUR'"},
        },
        "required": ["amount", "from_currency", "to_currency"],
        "callable": lambda args: _exchange_rate(
            float(args.get("amount", 1)),
            str(args.get("from_currency", "")),
            str(args.get("to_currency", "")),
        ),
    },
    "news_headlines": {
        "tool_name": "get_news_headlines",
        "parameters": {
            "source": {
                "type": "string",
                "description": "One of: bbc, npr, hn, reuters. Default 'bbc'.",
            }
        },
        "required": [],
        "callable": lambda args: _news_headlines(str(args.get("source", "bbc"))),
    },
}


# ── Catalog discovery: read SKILL.md manifests from the OpenClaw workspace ─


def _parse_frontmatter(text: str) -> dict[str, Any]:
    """Tiny YAML-ish parser for SKILL.md frontmatter. Handles `key: value`
    and simple list values. Returns {} if no frontmatter."""
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    block = text[3:end].strip()
    out: dict[str, Any] = {}
    current_key: str | None = None
    for raw in block.splitlines():
        line = raw.rstrip()
        if not line:
            continue
        if line.startswith("  - ") and current_key:
            out.setdefault(current_key, [])
            if isinstance(out[current_key], list):
                out[current_key].append(line[4:].strip())
            continue
        if ":" in line:
            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip()
            current_key = key
            if val:
                out[key] = val
    return out


def discover_skills(
    skills_dir: Path = OPENCLAW_SKILLS_DIR,
) -> list[tuple[str, dict[str, Any]]]:
    """Read every SKILL.md frontmatter in `skills_dir`. Returns (name, manifest)."""
    if not skills_dir.exists():
        return []
    out: list[tuple[str, dict[str, Any]]] = []
    for sub in sorted(skills_dir.iterdir()):
        if not sub.is_dir():
            continue
        md = sub / "SKILL.md"
        if not md.exists():
            continue
        try:
            fm = _parse_frontmatter(md.read_text(encoding="utf-8"))
        except OSError:
            continue
        name = fm.get("name") or sub.name
        out.append((name, fm))
    return out


def _build_tools(catalog: list[tuple[str, dict[str, Any]]]) -> tuple[list[dict], dict[str, Callable]]:
    """Build OpenAI-style tool defs + dispatch table for skills we have impls for."""
    tools: list[dict] = []
    dispatch: dict[str, Callable] = {}
    for name, manifest in catalog:
        impl = _SKILL_IMPLS.get(name)
        if impl is None:
            log.info("bridge.skill_v2_only", name=name, description=manifest.get("description", ""))
            continue
        tools.append({
            "type": "function",
            "function": {
                "name": impl["tool_name"],
                "description": manifest.get("description", impl["tool_name"]),
                "parameters": {
                    "type": "object",
                    "properties": impl["parameters"],
                    "required": impl["required"],
                },
            },
        })
        dispatch[impl["tool_name"]] = impl["callable"]
    return tools, dispatch


# ── Bridge ──────────────────────────────────────────────────────────────────


class OpenClawBridge:
    """Tool-calling client. Catalog from OpenClaw manifests, runtime via Ollama."""

    def __init__(
        self,
        url: str = "http://127.0.0.1:11434",
        token: str = "",                # noqa: ARG002  unused; kept for router signature compat
        model: str = "qwen2.5:1.5b",
        timeout: float = 30.0,
        skills_dir: Path | None = None,
    ) -> None:
        # `url` historically pointed at the OpenClaw gateway. If the caller
        # passes the old openclaw URL (port 18789), silently swap for Ollama.
        if "18789" in url or "openclaw" in url:
            url = "http://127.0.0.1:11434"
        self._url = url.rstrip("/")
        self._model = model
        self._timeout = timeout
        catalog = discover_skills(skills_dir or OPENCLAW_SKILLS_DIR)
        self._tools, self._dispatch = _build_tools(catalog)
        log.info(
            "bridge.ready",
            catalog_total=len(catalog),
            tools_loaded=len(self._tools),
            v2_only=[n for n, _ in catalog if n not in _SKILL_IMPLS],
        )

    # public surface

    def loaded_tools(self) -> list[str]:
        return [t["function"]["name"] for t in self._tools]

    def send(self, text: str) -> str | None:
        """Return the model's reply, or None to defer to the router's LLM path."""
        if not self._tools:
            log.info("bridge.no_tools")
            return None
        try:
            first = httpx.post(
                f"{self._url}/api/chat",
                json={
                    "model": self._model,
                    "messages": [{"role": "user", "content": text}],
                    "tools": self._tools,
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

        handler = self._dispatch.get(name)
        if handler is None:
            log.warning("bridge.unknown_tool", name=name)
            return None

        log.info("bridge.tool_call", tool=name, args=args)
        tool_result = handler(args)

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
