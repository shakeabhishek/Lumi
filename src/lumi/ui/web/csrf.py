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
"""

from __future__ import annotations

import secrets as _secrets
from typing import Iterable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

# Routes we explicitly do NOT enforce CSRF on. Each is either a same-machine
# trusted caller (hotkey daemon) or an HTMX partial that comes from the
# already-CSRF-protected dashboard but is fetched without the form helper.
_BYPASS_PREFIXES: tuple[str, ...] = (
    "/api/context",      # send-to-Lumi daemon — runs locally with no browser
    "/static/",          # static assets, no state
)

_COOKIE_NAME = "csrf_token"
_FORM_FIELD = "csrf_token"
_HEADER_NAME = "x-csrf-token"
_MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def _new_token() -> str:
    return _secrets.token_hex(16)


def _bypass(path: str) -> bool:
    return any(path.startswith(p) for p in _BYPASS_PREFIXES)


class CSRFMiddleware(BaseHTTPMiddleware):
    """Issues + validates a per-browser-session CSRF token."""

    async def dispatch(self, request: Request, call_next):
        method = request.method.upper()
        path = request.url.path

        # Resolve the token for this request:
        #   - If the browser already sent the cookie, use that.
        #   - Otherwise mint a new one NOW and stash it on request.state
        #     so the template that's about to render can include the SAME
        #     token in forms. We'll persist it as a cookie on the response.
        existing = request.cookies.get(_COOKIE_NAME, "")
        token = existing or _new_token()
        request.state.csrf_token = token

        # Enforce on mutating methods, unless explicitly bypassed.
        if method in _MUTATING_METHODS and not _bypass(path):
            cookie_token = existing
            submitted = await self._submitted_token(request)
            if not cookie_token or not submitted or not _secrets.compare_digest(cookie_token, submitted):
                return JSONResponse(
                    {"error": "csrf_token mismatch — refresh the page and try again"},
                    status_code=403,
                )

        response: Response = await call_next(request)

        # Set the cookie on first response so the next request validates.
        if not existing:
            response.set_cookie(
                _COOKIE_NAME,
                token,
                samesite="strict",
                # Not HttpOnly — Jinja templates render it via the
                # csrf_token() global. Setting HttpOnly would defeat that.
                httponly=False,
                # Only mark secure when actually over HTTPS — V1 traffic is
                # HTTP localhost and a secure cookie would never be sent.
                secure=request.url.scheme == "https",
            )
        return response

    @staticmethod
    async def _submitted_token(request: Request) -> str:
        """Pull the token from header or form. For form bodies we read the
        raw body and parse it ourselves, then splice it back onto the
        request's receive callable so the downstream route handler can
        still read request.form() / request.body() exactly once."""
        # Header path — JS / HTMX callers.
        header = request.headers.get(_HEADER_NAME, "")
        if header:
            return header
        ctype = request.headers.get("content-type", "")
        if "form-urlencoded" not in ctype:
            # We don't try to handle multipart here — token must come via
            # the X-CSRF-Token header for multipart submissions (none of
            # our routes use multipart today). Same for application/json.
            return ""
        try:
            body = await request.body()
        except Exception:
            return ""

        # Re-arm the receive channel so the route handler can also read
        # the body via request.form() / request.body(). Starlette caches
        # request._body internally; we set it AND patch receive() to
        # return the same body once more for safety.
        async def _replay():
            return {"type": "http.request", "body": body, "more_body": False}
        request._receive = _replay        # type: ignore[attr-defined]
        request._body = body              # type: ignore[attr-defined]

        # Parse with urllib so we don't consume Starlette's form() machinery.
        from urllib.parse import parse_qs  # noqa: PLC0415
        try:
            parsed = parse_qs(body.decode("utf-8", errors="replace"), keep_blank_values=True)
        except Exception:
            return ""
        vals = parsed.get(_FORM_FIELD)
        return vals[0] if vals else ""


# ── Template helper ────────────────────────────────────────────────────────


def csrf_token_for(request: Request) -> str:
    """Return the CSRF token for this request.

    The middleware always sets `request.state.csrf_token` — either to the
    existing cookie value or to a freshly-minted token that will be set
    on the response. Templates rendering during the response see the
    correct value either way (first GET or subsequent), so forms always
    submit a token that matches the cookie the browser is about to receive.
    """
    return getattr(request.state, "csrf_token", "") or request.cookies.get(_COOKIE_NAME, "")


# Routes routers can append to to opt out of CSRF for additional paths.
# Add cautiously — every entry here is a potential CSRF target.
def add_bypass(prefix: str) -> None:
    global _BYPASS_PREFIXES
    _BYPASS_PREFIXES = (*_BYPASS_PREFIXES, prefix)


def bypass_list() -> Iterable[str]:
    return _BYPASS_PREFIXES
