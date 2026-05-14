"""Twemoji asset loader for the vector face.

Downloads the four state emojis from jsDelivr's Twemoji CDN on first use and
caches them under `models/twemoji/`. Network is only touched once per
codepoint; subsequent renders read from disk.

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

# Twemoji only publishes 72×72 PNGs. To get higher resolution we ask the
# wsrv.nl image-resize proxy to rasterize the official Twemoji SVG at a
# requested pixel size — the result is a crisp PNG of any size we want.
# Cached locally after first fetch, so the proxy is only hit once per emoji.
_CDN_URL = (
    "https://wsrv.nl/?"
    "url=https://cdn.jsdelivr.net/gh/jdecked/twemoji@latest/assets/svg/{cp}.svg"
    "&w={size}&h={size}&output=png"
)
_DEFAULT_PNG_SIZE = 320


def cache_dir(models_dir: Path) -> Path:
    return models_dir / "twemoji"


def codepoint_for(state: LumiState) -> str:
    return _STATE_TO_CODEPOINT.get(state, _STATE_TO_CODEPOINT[LumiState.IDLE])


def ensure_cached(
    models_dir: Path,
    timeout_s: float = 10.0,
    size: int = _DEFAULT_PNG_SIZE,
) -> dict[LumiState, Path]:
    """Download any missing emoji PNGs. Returns {state: cached_path}.

    `size` is the requested rasterization in pixels (square). Each codepoint's
    cache file name includes the size so different requested sizes co-exist.
    A state is omitted if its fetch failed AND no prior cache exists.
    """
    import httpx  # noqa: PLC0415

    out: dict[LumiState, Path] = {}
    cdir = cache_dir(models_dir)
    cdir.mkdir(parents=True, exist_ok=True)
    for state, cp in _STATE_TO_CODEPOINT.items():
        path = cdir / f"{cp}_{size}.png"
        if not path.exists():
            url = _CDN_URL.format(cp=cp, size=size)
            try:
                resp = httpx.get(url, timeout=timeout_s, follow_redirects=True)
                resp.raise_for_status()
                # Basic sanity: PNG magic 0x89 'P' 'N' 'G'
                if not resp.content.startswith(b"\x89PNG"):
                    raise ValueError(f"response is not a PNG: {resp.content[:8]!r}")
                path.write_bytes(resp.content)
                log.info("twemoji.fetched", codepoint=cp, size=size, bytes=len(resp.content))
            except Exception as exc:
                log.warning("twemoji.fetch_failed", codepoint=cp, error=str(exc))
        if path.exists():
            out[state] = path
    return out
