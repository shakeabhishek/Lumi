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


def _weather_payload(d: dict[str, Any]) -> dict[str, Any]:
    """Shape an OpenWeatherMap /weather response into Lumi's snapshot
    + add a `condition` enum (sunny / cloudy / rainy / snowy /
    clear-night) the React WidgetBar's WeatherSnapshot type expects."""
    owm_main = (d["weather"][0].get("main") or "").lower()
    owm_icon = d["weather"][0].get("icon", "") or ""
    is_night = owm_icon.endswith("n")
    if owm_main in {"rain", "drizzle", "thunderstorm"}:
        condition = "rainy"
    elif owm_main == "snow":
        condition = "snowy"
    elif owm_main == "clear":
        condition = "clear-night" if is_night else "sunny"
    else:
        condition = "cloudy"
    return {
        "location": d.get("name"),
        "temperature_c": d["main"]["temp"],
        "feels_like_c": d["main"]["feels_like"],
        "humidity_pct": d["main"]["humidity"],
        "conditions": d["weather"][0]["description"],
        "wind_mps": d["wind"]["speed"],
        "condition": condition,
    }


def fetch_weather(location: str) -> dict[str, Any] | None:
    """Best-effort snapshot for the device-display sampler. Returns None
    on ANY failure — the sampler keeps the last good reading rather
    than clobbering the UI with an error message. The LLM-facing skill
    `_weather()` below does its own request so it can produce precise
    'not found' / 'lookup failed' strings."""
    key = secrets.get_secret("openweathermap_api_key")
    if not key:
        return None
    try:
        r = httpx.get(
            "https://api.openweathermap.org/data/2.5/weather",
            params={"q": location, "appid": key, "units": "metric"},
            timeout=10.0,
        )
        if r.status_code != 200:
            return None
        return _weather_payload(r.json())
    except (httpx.HTTPError, KeyError, ValueError):
        return None


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
        snapshot = _weather_payload(r.json())
        return json.dumps({
            "location": snapshot["location"],
            "temperature_c": snapshot["temperature_c"],
            "feels_like_c": snapshot["feels_like_c"],
            "humidity_pct": snapshot["humidity_pct"],
            "conditions": snapshot["conditions"],
            "wind_mps": snapshot["wind_mps"],
        })
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


def _parse_agent_json(text: str) -> dict[str, Any] | None:
    """Extract the structured JSON result from `npx openclaw agent --json`.

    The agent CLI prints coloured log lines (with embedded JSON-shaped
    blobs in error messages) followed by the actual result object on its
    own line(s). We want the OUTERMOST balanced JSON object that
    contains a `payloads` field — naive find('{') / rfind('}') picks up
    inner braces from log noise; rfind walking outward picks up the
    innermost object first.

    Strategy: scan every line-starting `{` (positions preceded by `\\n`
    or beginning-of-string), try to balance forward, return the
    payloads-bearing result.
    """
    if not text:
        return None

    # Collect candidate start positions: each `{` at the start of a line.
    starts: list[int] = []
    if text.startswith("{"):
        starts.append(0)
    pos = 0
    while True:
        i = text.find("\n{", pos)
        if i < 0:
            break
        starts.append(i + 1)
        pos = i + 1

    # Prefer the latest (rightmost) candidate first — the agent prints
    # the result AFTER the log lines.
    for start in reversed(starts):
        end = _balanced_end(text, start)
        if end < 0:
            continue
        try:
            obj = json.loads(text[start:end])
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        # Strong signal that this is the result envelope (current or legacy
        # shape). If neither, keep looking — we may have parsed a stray
        # log line that happened to be valid JSON.
        if "payloads" in obj or "result" in obj or "meta" in obj:
            return obj

    return None


def _balanced_end(text: str, start: int) -> int:
    """Return the index AFTER the `}` that closes the object opened at
    `text[start]`, respecting string escapes so embedded `}` inside
    string values don't confuse the counter. -1 if unbalanced."""
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i + 1
    return -1


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
    """Tool-calling client. Two runtime modes:

    - "ollama" (default): direct Ollama tool_calls with our Python tool impls.
      Reliable on small local models (94% in viability test). What V1 ships.
    - "openclaw_cloud": shell out to `npx openclaw agent` so OpenClaw's full
      agent loop drives a cloud LLM (Claude/GPT/Gemini) over the SAME plugin
      catalog. Unlocks community skills once a cloud key is configured in
      /settings/cloud (which also writes the provider into OpenClaw's config
      via skills.openclaw_operator.sync_to_openclaw).
    """

    def __init__(
        self,
        url: str = "http://127.0.0.1:11434",
        token: str = "",                # noqa: ARG002  unused; kept for router signature compat
        model: str = "qwen2.5:7b",
        timeout: float = 15.0,
        skills_dir: Path | None = None,
        runtime_mode: str = "ollama",
        pseudonymizer: object | None = None,   # runtime.privacy.Pseudonymizer
        enabled_skills: list[str] | None = None,
    ) -> None:
        # `url` historically pointed at the OpenClaw gateway. If the caller
        # passes the old openclaw URL (port 18789), silently swap for Ollama.
        if "18789" in url or "openclaw" in url:
            url = "http://127.0.0.1:11434"
        self._url = url.rstrip("/")
        self._model = model
        self._timeout = timeout
        self._mode = runtime_mode if runtime_mode in {"ollama", "openclaw_cloud"} else "ollama"
        # Cloud mode REQUIRES a pseudonymizer so we don't leak PII to the
        # provider. Caller is responsible for passing one (the chat route
        # constructs one from settings + the owner's name).
        self._pseudo = pseudonymizer
        # First-failure state for cloud subprocess so we can surface ONE
        # user-visible warning rather than silently falling through to the
        # local LLM forever. See cloud_failure_notice().
        self._cloud_failure: str | None = None
        self._cloud_failure_seen = False
        # Ollama health: once we observe a connection refused / timeout
        # on the chat endpoint, disable the bridge for the rest of this
        # process so we don't burn another self._timeout seconds per turn.
        # A subsequent fresh process or a successful /api/tags ping
        # re-enables it. Audit #20.
        self._ollama_disabled = False
        catalog = discover_skills(skills_dir or OPENCLAW_SKILLS_DIR)
        # User-toggleable allow-list. `None` (the default) means "everything
        # in the catalog is on" — preserves the prior behaviour for callers
        # that don't pass enabled_skills. An empty list explicitly disables
        # every skill (rare but valid: pure-LLM mode).
        if enabled_skills is not None:
            catalog = [(name, meta) for (name, meta) in catalog if name in enabled_skills]
        self._tools, self._dispatch = _build_tools(catalog)
        log.info(
            "bridge.ready",
            mode=self._mode,
            catalog_total=len(catalog),
            tools_loaded=len(self._tools),
            v2_only=[n for n, _ in catalog if n not in _SKILL_IMPLS],
            pseudonymizer=type(pseudonymizer).__name__ if pseudonymizer else None,
            enabled_filter=enabled_skills,
        )

    # public surface

    def loaded_tools(self) -> list[str]:
        return [t["function"]["name"] for t in self._tools]

    @property
    def runtime_mode(self) -> str:
        """'ollama' (local Python tool execution) or 'openclaw_cloud' (real OpenClaw agent loop)."""
        return self._mode

    def health_check(self, timeout: float = 2.0) -> bool:
        """Ping /api/tags to verify Ollama is reachable. If a previous turn
        sticky-disabled the bridge and Ollama is back, this re-enables it.
        Returns True iff reachable. Cloud mode short-circuits to True
        because the bridge doesn't talk to Ollama at all there."""
        if self._mode != "ollama":
            return True
        try:
            r = httpx.get(f"{self._url}/api/tags", timeout=timeout)
            r.raise_for_status()
            if self._ollama_disabled:
                log.info("bridge.ollama_recovered")
            self._ollama_disabled = False
            return True
        except (httpx.HTTPError, ValueError):
            self._ollama_disabled = True
            return False

    def cloud_failure_notice(self) -> str | None:
        """Return a one-shot user-facing notice if the cloud subprocess
        has failed since the last check, then mark it as seen so the
        same notice isn't repeated turn after turn. Returns None when
        nothing's wrong, or when the user has already been told."""
        if not self._cloud_failure or self._cloud_failure_seen:
            return None
        self._cloud_failure_seen = True
        return self._cloud_failure

    def _record_cloud_failure(self, kind: str, exc: object) -> None:
        """Stash a short, user-safe failure reason. New failures override
        older ones (most recent wins) but the seen flag resets so the
        user sees the latest reason once."""
        kind_to_msg = {
            "no_npx": (
                "Cloud mode is configured but `npx` (Node.js) wasn't found. "
                "Falling back to local. Install Node.js 20+ to enable cloud LLM."
            ),
            "timeout": (
                "Cloud LLM didn't respond in time — falling back to local for this turn."
            ),
            "bad_output": (
                "Cloud subprocess returned unparseable output — falling back to local."
            ),
            "nonzero": (
                "Cloud subprocess exited with an error — falling back to local. "
                "Try `lumi cloud-test` from a terminal to see details."
            ),
        }
        self._cloud_failure = kind_to_msg.get(kind, f"Cloud LLM unavailable: {exc!s:.120}")
        self._cloud_failure_seen = False
        log.warning("bridge.cloud_user_notice", kind=kind, error=str(exc)[:200])

    def send(self, text: str) -> str | None:
        """Return the model's reply, or None to defer to the router's LLM path."""
        if self._mode == "openclaw_cloud":
            return self._send_via_openclaw(text)
        if not self._tools:
            log.info("bridge.no_tools")
            return None
        if self._ollama_disabled:
            # Sticky failure: don't burn another timeout cycle. The router
            # falls through to the LLM path (which has its own backend).
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
        except httpx.ConnectError as exc:
            log.warning("bridge.ollama_unreachable", error=str(exc))
            self._ollama_disabled = True
            return None
        except httpx.TimeoutException as exc:
            log.warning("bridge.ollama_timeout", error=str(exc))
            self._ollama_disabled = True
            return None
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

    def _send_via_openclaw(self, text: str) -> str | None:
        """Cloud mode: drive OpenClaw's full agent loop via its session CLI.

        Pseudonymizes the transcript before sending if a Pseudonymizer was
        supplied (it should always be — privacy is non-negotiable in cloud
        mode). Unmasks the reply before returning so the user sees real
        names/emails/etc.
        """
        import subprocess  # noqa: PLC0415

        # PII masking: replace names, emails, phones, cards, etc. with
        # stable pseudonyms before anything leaves the device.
        if self._pseudo is not None:
            masked_text = self._pseudo.mask(text)  # type: ignore[attr-defined]
            if masked_text != text:
                log.info(
                    "bridge.pseudonymized",
                    raw_chars=len(text),
                    masked_chars=len(masked_text),
                    replacements=len(self._pseudo.mapping),  # type: ignore[attr-defined]
                )
        else:
            log.warning("bridge.cloud_send_without_pseudonymizer")  # should never happen
            masked_text = text

        try:
            proc = subprocess.run(
                ["npx", "openclaw", "agent",
                 "--agent", "main",
                 "--local",                # embedded run; reads provider key from openclaw.json
                 "--message", masked_text,
                 "--json",
                 "--timeout", str(int(self._timeout))],
                # +3, not the wider buffer this used to carry: verified against
                # the real OpenClaw 2026.04.20 CLI (2026-07-02) that its own
                # `--timeout` flag above is NOT honored — the process runs
                # until *this* subprocess timeout hard-kills it, regardless of
                # what we pass. A big grace buffer here used to just add dead
                # seconds to every miss; +3 is only slack for the process to
                # flush output and exit after being killed.
                capture_output=True, text=True, timeout=self._timeout + 3,
            )
            if proc.returncode != 0:
                self._record_cloud_failure("nonzero", proc.stderr[:200] or proc.stdout[:200])
                return None
            # The agent CLI's `--json` mode in OpenClaw 2026.04 emits the
            # result envelope on STDERR (alongside coloured log lines),
            # not stdout — stdout often comes back empty. Parse both
            # streams together so we don't care which one the CLI picks.
            combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
            data = _parse_agent_json(combined)
            if data is None:
                self._record_cloud_failure("bad_output", "no JSON object in subprocess output")
                return None
            # The result envelope can be either `{"payloads": [...], "meta": {...}}`
            # (openclaw 2026.04+) or wrapped in `{"result": {...}}` (older).
            envelope = data.get("result", data)
            payloads = envelope.get("payloads", []) or []
            reply = "\n\n".join(p.get("text", "") for p in payloads if p.get("text")).strip()
            tool_summary = envelope.get("meta", {}).get("agentMeta", {}).get("toolSummary") or {}
            log.info(
                "bridge.openclaw_ok",
                chars=len(reply),
                tool_calls=tool_summary.get("calls"),
                tools=tool_summary.get("tools"),
            )
            # Clear any previous failure notice — we just got a real reply.
            self._cloud_failure = None
            # Unmask before handing back to the user.
            if self._pseudo is not None and reply:
                reply = self._pseudo.unmask(reply)  # type: ignore[attr-defined]
            return reply or None
        except FileNotFoundError as exc:
            self._record_cloud_failure("no_npx", exc)
            return None
        except subprocess.TimeoutExpired as exc:
            self._record_cloud_failure("timeout", exc)
            return None
        except (json.JSONDecodeError, OSError) as exc:
            self._record_cloud_failure("bad_output", exc)
            return None
