"""Thin cloud-LLM adapters used by RoutedBackend.

V1.5 ships Gemini (gemini-2.5-flash) only because that's what the
dashboard already collects keys for and what we verified end-to-end
on 2026-05-23. Anthropic + OpenAI are TODO — same shape, different
HTTP body. Each adapter implements the CloudLLMClient duck-typed
interface in routed_backend.py:

  complete(messages)           -> str            # full reply, non-streaming
  complete_streaming(messages) -> Iterator[str]   # reply chunks, as they arrive
  label                        -> str             # short id for audit logging

`complete_streaming` was added 2026-07-05 when RoutedBackend flipped
from local-first-with-cloud-escalation to cloud-first-with-local-
fallback: cloud is now the common path for every turn, not an
occasional short fallback, so non-streaming replies would mean a
multi-second silent wait before anything appears — the opposite of
the responsiveness the flip was for.

Adapters use httpx directly rather than the official provider SDKs
because (a) we only need one endpoint per provider and (b) we don't
want to drag three big SDK trees into the wheel.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from typing import Any

import httpx

from ..log import get_logger
from .ollama_backend import Message

log = get_logger(__name__)


class _NoKeyError(RuntimeError):
    """Raised when build_cloud_client is called but the keychain has
    no entry for the configured provider. Caught by callers and
    treated as 'cloud routing unavailable for this turn'."""


# ── Gemini ──────────────────────────────────────────────────────────────────


class GeminiClient:
    """Google Generative Language API — `gemini-2.5-flash` by default.
    Uses the v1beta REST endpoint (stable as of 2026-05). Synchronous
    single-shot completion; matches the CloudLLMClient protocol."""

    label = "gemini"

    def __init__(
        self, api_key: str, model: str = "gemini-2.5-flash",
        timeout: float = 30.0,
    ) -> None:
        self._key = api_key
        self._model = model
        self._timeout = timeout

    def _build_body(self, messages: list[Message]) -> dict[str, Any]:
        # Gemini's content shape: an array of {role, parts: [{text}]}.
        # Roles are "user" / "model"; "system" gets folded into a
        # `systemInstruction` field at the top level.
        system_parts: list[str] = []
        contents: list[dict[str, Any]] = []
        for m in messages:
            role = m.get("role")
            content = m.get("content", "")
            if not content:
                continue
            if role == "system":
                system_parts.append(content)
            elif role == "assistant":
                contents.append({"role": "model", "parts": [{"text": content}]})
            else:
                contents.append({"role": "user", "parts": [{"text": content}]})

        body: dict[str, Any] = {"contents": contents}
        if system_parts:
            body["systemInstruction"] = {"parts": [{"text": "\n\n".join(system_parts)}]}
        return body

    @staticmethod
    def _extract_text(candidates: list[dict[str, Any]]) -> str:
        if not candidates:
            return ""
        parts = candidates[0].get("content", {}).get("parts", [])
        return "".join(p.get("text", "") for p in parts)

    def complete(self, messages: list[Message]) -> str:
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self._model}:generateContent"
        )
        r = httpx.post(
            url,
            params={"key": self._key},
            json=self._build_body(messages),
            timeout=self._timeout,
        )
        r.raise_for_status()
        data = r.json()
        return self._extract_text(data.get("candidates", []))

    def complete_streaming(self, messages: list[Message]) -> Iterator[str]:
        """Yield reply text chunks as Gemini generates them, via the
        SSE-formatted streamGenerateContent endpoint. Each SSE event is
        a JSON object with the same candidates[0].content.parts shape
        as the non-streaming response, but partial."""
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self._model}:streamGenerateContent"
        )
        with httpx.stream(
            "POST",
            url,
            params={"key": self._key, "alt": "sse"},
            json=self._build_body(messages),
            timeout=self._timeout,
        ) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if not line.startswith("data: "):
                    continue
                payload = line[len("data: "):].strip()
                if not payload or payload == "[DONE]":
                    continue
                try:
                    data = json.loads(payload)
                except json.JSONDecodeError:
                    log.warning("gemini.stream_parse_error", line=payload[:200])
                    continue
                text = self._extract_text(data.get("candidates", []))
                if text:
                    yield text


# ── Factory ─────────────────────────────────────────────────────────────────


def build_cloud_client(provider: str, model: str, api_key: str | None):
    """Return a CloudLLMClient for the named provider, or None if the
    key isn't present. Callers should treat None as 'cloud routing
    not available for this turn' — log it and stay local rather than
    raising.
    """
    if not api_key:
        return None
    p = provider.lower().strip()
    if p == "gemini":
        return GeminiClient(api_key=api_key, model=model or "gemini-2.5-flash")
    # Other providers: stub for now. Plumb in when we extend coverage.
    log.warning("cloud_clients.unsupported_provider", provider=provider)
    return None


def get_cloud_api_key(provider: str) -> str | None:
    """Pull the cloud LLM API key from the OS keychain — canonical
    storage per CLAUDE.md privacy section. The dashboard /settings/cloud
    page stores under (service="lumi", key="cloud_llm_api_key"); we
    just read that. `provider` is accepted but not used for keying
    today because the dashboard is single-provider — kept in the
    signature so we can extend to per-provider keys without rippling
    callers later.

    Falls back to LUMI_CLOUD_{PROVIDER}_API_KEY env var if the
    keychain has nothing — useful for headless CI / tests.
    """
    p = provider.lower().strip()
    if not p:
        return None

    try:
        from ..runtime.secrets import get_secret  # noqa: PLC0415

        key = get_secret("cloud_llm_api_key")
        if key:
            return key
    except Exception as exc:
        log.warning("cloud_clients.keychain_unavailable", error=str(exc))

    env_name = f"LUMI_CLOUD_{p.upper()}_API_KEY"
    return os.environ.get(env_name)
