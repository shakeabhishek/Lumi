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

_CDN_URL = "https://cdn.jsdelivr.net/gh/jdecked/twemoji@latest/assets/72x72/{cp}.png"


def cache_dir(models_dir: Path) -> Path:
    return models_dir / "twemoji"


def codepoint_for(state: LumiState) -> str:
    return _STATE_TO_CODEPOINT.get(state, _STATE_TO_CODEPOINT[LumiState.IDLE])


def ensure_cached(models_dir: Path, timeout_s: float = 10.0) -> dict[LumiState, Path]:
    """Download any missing emoji PNGs. Returns {state: cached_path}.

    A state is omitted from the result if its fetch failed AND no prior cache
    exists — callers fall back to a drawn face for those states.
    """
    import httpx  # noqa: PLC0415

    out: dict[LumiState, Path] = {}
    cdir = cache_dir(models_dir)
    cdir.mkdir(parents=True, exist_ok=True)
    for state, cp in _STATE_TO_CODEPOINT.items():
        path = cdir / f"{cp}.png"
        if not path.exists():
            try:
                resp = httpx.get(_CDN_URL.format(cp=cp), timeout=timeout_s)
                resp.raise_for_status()
                path.write_bytes(resp.content)
                log.info("twemoji.fetched", codepoint=cp, bytes=len(resp.content))
            except Exception as exc:
                log.warning("twemoji.fetch_failed", codepoint=cp, error=str(exc))
        if path.exists():
            out[state] = path
    return out
