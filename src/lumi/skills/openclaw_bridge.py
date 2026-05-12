"""HTTP client to the OpenClaw gateway.

Sends the user's transcript to OpenClaw and returns the plain-text response.
Returns None on any failure so the skill router can fall through to the LLM.
"""

from __future__ import annotations

import httpx

from ..log import get_logger

log = get_logger(__name__)


class OpenClawBridge:
    def __init__(self, url: str, token: str, timeout: float = 30.0) -> None:
        self._url = url.rstrip("/")
        self._token = token
        self._timeout = timeout

    def send(self, text: str) -> str | None:
        """Send transcript to OpenClaw; return response text or None on failure."""
        try:
            response = httpx.post(
                f"{self._url}/v1/chat/completions",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self._token}",
                },
                json={
                    "model": "openclaw",
                    "messages": [{"role": "user", "content": text}],
                },
                timeout=self._timeout,
            )
            response.raise_for_status()
            data: dict = response.json()
            content: str = data["choices"][0]["message"]["content"]
            log.info("openclaw_bridge.ok", chars=len(content))
            return content
        except httpx.TimeoutException:
            log.warning("openclaw_bridge.timeout", url=self._url)
            return None
        except httpx.HTTPStatusError as exc:
            log.warning("openclaw_bridge.http_error", status=exc.response.status_code)
            return None
        except Exception as exc:
            log.warning("openclaw_bridge.error", error=str(exc))
            return None
