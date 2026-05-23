"""Cookie-based CSRF protection for the Lumi dashboard.

V1 runs on localhost on a laptop — CSRF is low-risk there. On the Pi
once `lumi.local` is reachable on the LAN (or worse, the LAN sometimes
crosses NATs to a phone), an attacker page can `fetch('http://lumi.local/...')`
from a browser tab and trip every POST endpoint we expose: factory
reset, set cloud key, toggle skills, etc. So we add CSRF before
hardware ships, not after.

Design:
  * First GET that returns HTML sets a `csrf_token` cookie (SameSite=Strict,
    HttpOnly is NOT set because the form needs to read it via the template).
  * Every mutating method (POST/PUT/PATCH/DELETE) must present the same
    token in EITHER a `csrf_token` form field OR an `X-CSRF-Token`
    header. Mismatch → 403.
  * Bypass list for non-browser callers that we explicitly trust:
    /api/context (the hotkey daemon POSTs there from the same machine),
    and OPTIONS preflight if anything ever needs it.

Tokens are 32 hex chars from secrets.token_hex. One token per browser
session; we don't rotate per request — the goal is defence against
cross-origin abuse, not perfect forward secrecy.

ASGI middleware (not BaseHTTPMiddleware): Starlette's BaseHTTPMiddleware
buffers the entire response body before passing it on, which breaks
StreamingResponse (Server-Sent Events for /chat/stream). Implementing
as a pure ASGI app lets responses flow through chunk-by-chunk.
"""

from __future__ import annotations

import secrets as _secrets
from typing import Iterable
from urllib.parse import parse_qs

from fastapi import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# Routes we explicitly do NOT enforce CSRF on. Each is either a same-machine
# trusted caller (hotkey daemon) or a same-origin static asset.
_BYPASS_PREFIXES: tuple[str, ...] = (
    "/api/context",      # send-to-Lumi daemon — runs locally with no browser
    "/static/",          # static assets, no state
)

_COOKIE_NAME = "csrf_token"
_FORM_FIELD = "csrf_token"
_HEADER_NAME = b"x-csrf-token"
_MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# 403 body for invalid/missing tokens.
_FORBIDDEN_BODY = (
    '{"error":"csrf_token mismatch — refresh the page and try again"}'
).encode("utf-8")


def _new_token() -> str:
    return _secrets.token_hex(16)


def _bypass(path: str) -> bool:
    return any(path.startswith(p) for p in _BYPASS_PREFIXES)


def _cookies_from_scope(scope: Scope) -> dict[str, str]:
    """Parse the Cookie header out of the raw ASGI scope."""
    out: dict[str, str] = {}
    for name, value in scope.get("headers", []):
        if name == b"cookie":
            for piece in value.decode("latin-1").split(";"):
                if "=" in piece:
                    k, _, v = piece.strip().partition("=")
                    out[k] = v
    return out


def _header_value(scope: Scope, name: bytes) -> str:
    name = name.lower()
    for k, v in scope.get("headers", []):
        if k.lower() == name:
            return v.decode("latin-1")
    return ""


async def _read_body(receive: Receive) -> bytes:
    """Drain the request body off the ASGI receive channel."""
    chunks: list[bytes] = []
    while True:
        message = await receive()
        if message["type"] == "http.request":
            body = message.get("body", b"") or b""
            if body:
                chunks.append(body)
            if not message.get("more_body", False):
                break
        elif message["type"] == "http.disconnect":
            break
    return b"".join(chunks)


def _form_token(body: bytes, content_type: str) -> str:
    if "form-urlencoded" not in content_type:
        return ""
    try:
        parsed = parse_qs(body.decode("utf-8", errors="replace"), keep_blank_values=True)
    except Exception:
        return ""
    vals = parsed.get(_FORM_FIELD)
    return vals[0] if vals else ""


class CSRFMiddleware:
    """Pure ASGI middleware. Compatible with StreamingResponse."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "GET").upper()
        path = scope.get("path", "")
        cookies = _cookies_from_scope(scope)
        existing = cookies.get(_COOKIE_NAME, "")
        token = existing or _new_token()

        # Make the resolved token available to handlers (templates pull it
        # via csrf_token_for(request) which reads request.state.csrf_token).
        scope.setdefault("state", {})
        # FastAPI uses scope["state"] as the backing dict for request.state.
        scope["state"]["csrf_token"] = token

        # Validate on mutating methods, unless explicitly bypassed.
        if method in _MUTATING_METHODS and not _bypass(path):
            header_token = _header_value(scope, _HEADER_NAME)
            submitted = header_token

            # The header-only path covers HTMX/JS callers. For classic form
            # POSTs we have to drain the body to find the token, then
            # replay the body so the downstream route still sees it.
            if not submitted:
                ctype = _header_value(scope, b"content-type")
                if "form-urlencoded" in ctype:
                    body = await _read_body(receive)
                    submitted = _form_token(body, ctype)
                    receive = _wrap_body_receive(body, original_receive=receive)
                # other content types: only the header path is supported

            if (
                not existing
                or not submitted
                or not _secrets.compare_digest(existing, submitted)
            ):
                await _send_forbidden(send)
                return

        # Wrap `send` so we can inject the Set-Cookie on the response start
        # message — works equally well for plain responses and streams.
        async def send_with_cookie(message: Message) -> None:
            if message["type"] == "http.response.start" and not existing:
                headers = list(message.get("headers", []))
                secure = scope.get("scheme") == "https"
                cookie_value = (
                    f"{_COOKIE_NAME}={token}; Path=/; SameSite=Strict"
                    + ("; Secure" if secure else "")
                )
                headers.append((b"set-cookie", cookie_value.encode("latin-1")))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_cookie)


def _wrap_body_receive(body: bytes, *, original_receive: Receive) -> Receive:
    """Return a receive callable that yields `body` once (so the route can
    re-read it), then defers to the original receive for any subsequent
    polls. StreamingResponse calls receive() while streaming to detect
    client disconnects — if we returned http.disconnect ourselves, the
    response truncates immediately and no body bytes reach the client."""
    sent = {"served": False}

    async def receive() -> Message:
        if not sent["served"]:
            sent["served"] = True
            return {"type": "http.request", "body": body, "more_body": False}
        return await original_receive()

    return receive


async def _send_forbidden(send: Send) -> None:
    await send({
        "type": "http.response.start",
        "status": 403,
        "headers": [(b"content-type", b"application/json")],
    })
    await send({
        "type": "http.response.body",
        "body": _FORBIDDEN_BODY,
        "more_body": False,
    })


# ── Template helper ────────────────────────────────────────────────────────


def csrf_token_for(request: Request) -> str:
    """Return the CSRF token for this request — the middleware sets it on
    request.state for every request, so templates render the same value
    that the response's Set-Cookie carries (avoids the first-visit
    chicken-and-egg)."""
    state = getattr(request, "state", None)
    if state is not None:
        token = getattr(state, "csrf_token", "")
        if token:
            return token
    return request.cookies.get(_COOKIE_NAME, "")


# Mutable bypass list (rarely-used escape hatch for tests / advanced wiring).
def add_bypass(prefix: str) -> None:
    global _BYPASS_PREFIXES
    _BYPASS_PREFIXES = (*_BYPASS_PREFIXES, prefix)


def bypass_list() -> Iterable[str]:
    return _BYPASS_PREFIXES
