"""Twemoji asset loader for the vector face.

Lookup order:
  1. Bundled assets in src/lumi/ui/face/assets/twemoji/ (ships with Lumi
     so first-boot never blocks on the network).
  2. User cache dir at models/twemoji/ — populated on demand for sizes
     we didn't pre-rasterize, or to swap in a custom asset.

The bundled set covers the four states at 320px. Other sizes are still
backed by the CDN, but the bundle gives us a guaranteed offline floor:
no jsDelivr, no wsrv.nl, no problem.

The vector face uses these four:
  IDLE   → 1f60d  😍 smiling with heart-eyes
  LISTEN → 1f917  🤗 hugging face
  THINK  → 1f914  🤔 thinking face
  SPEAK  → 1f604  😄 grinning with smiling eyes
"""

from __future__ import annotations

from pathlib import Path

from ...log import get_logger
from ...runtime.state_machine import LumiState

log = get_logger(__name__)

_STATE_TO_CODEPOINT: dict[LumiState, str] = {
    LumiState.IDLE: "1f60d",
    LumiState.LISTEN: "1f917",
    LumiState.THINK: "1f914",
    LumiState.SPEAK: "1f604",
}

# Twemoji upstream pin. Avoid `@latest` — the CDN URL is part of our
# offline-fallback contract and we want predictable behaviour.
_TWEMOJI_VERSION = "15.1.0"

_CDN_URL = (
    "https://wsrv.nl/?"
    "url=https://cdn.jsdelivr.net/gh/jdecked/twemoji@" + _TWEMOJI_VERSION +
    "/assets/svg/{cp}.svg"
    "&w={size}&h={size}&output=png"
)
_DEFAULT_PNG_SIZE = 320

# Bundled assets directory — relative to THIS file, not the user's models dir.
# Always present; ships with the wheel.
_BUNDLED_DIR = Path(__file__).parent / "assets" / "twemoji"


def cache_dir(models_dir: Path) -> Path:
    return models_dir / "twemoji"


def codepoint_for(state: LumiState) -> str:
    return _STATE_TO_CODEPOINT.get(state, _STATE_TO_CODEPOINT[LumiState.IDLE])


def _bundled_path(codepoint: str, size: int) -> Path | None:
    """Return the bundled PNG path if we shipped one at this size, else None."""
    p = _BUNDLED_DIR / f"{codepoint}_{size}.png"
    return p if p.exists() else None


def ensure_cached(
    models_dir: Path,
    timeout_s: float = 10.0,
    size: int = _DEFAULT_PNG_SIZE,
) -> dict[LumiState, Path]:
    """Return {state: png_path} for every state we can serve.

    Lookup order per state:
      1. Bundled file at the requested size — return immediately, no I/O.
      2. User cache file — return if present.
      3. Network fetch into user cache — best-effort, never raises.

    A state is omitted from the result only if all three fail. Boot never
    blocks on the network as long as the bundled assets exist at this size.
    """
    out: dict[LumiState, Path] = {}
    cdir = cache_dir(models_dir)

    for state, cp in _STATE_TO_CODEPOINT.items():
        # 1. Bundled
        bundled = _bundled_path(cp, size)
        if bundled is not None:
            out[state] = bundled
            continue

        # 2. User cache
        cached = cdir / f"{cp}_{size}.png"
        if cached.exists():
            out[state] = cached
            continue

        # 3. CDN fetch (only if we don't have it locally)
        fetched = _fetch_into_cache(cp, size, cdir, timeout_s)
        if fetched is not None:
            out[state] = fetched

    return out


def _fetch_into_cache(
    codepoint: str, size: int, cdir: Path, timeout_s: float
) -> Path | None:
    """Best-effort fetch from the CDN. Returns the cache path on success,
    None on any failure. Never raises. Validates PNG magic before saving."""
    import httpx  # noqa: PLC0415

    cdir.mkdir(parents=True, exist_ok=True)
    url = _CDN_URL.format(cp=codepoint, size=size)
    try:
        resp = httpx.get(url, timeout=timeout_s, follow_redirects=True)
        resp.raise_for_status()
        if not resp.content.startswith(b"\x89PNG"):
            raise ValueError(f"response is not a PNG: {resp.content[:8]!r}")
        path = cdir / f"{codepoint}_{size}.png"
        path.write_bytes(resp.content)
        log.info("twemoji.fetched", codepoint=codepoint, size=size, bytes=len(resp.content))
        return path
    except Exception as exc:
        log.warning("twemoji.fetch_failed", codepoint=codepoint, error=str(exc))
        return None
