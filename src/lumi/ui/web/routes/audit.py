"""Audit log standalone viewer.

Split out from /skills (which is now just the skill-management surface).
Filterable by source family (native / openclaw / cloud / llm / tool /
all) so the user can find a specific path's history without
scrolling past unrelated entries. Pagination via `n` query param;
default 50 entries — enough to be useful, small enough to load
fast even on a 256 GB SD card.
"""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ....skills.audit_log import AuditLog

router = APIRouter()


# Family → predicate. The audit log source field is a free string so
# cloud:gemini / cloud:anthropic both collapse into the "cloud" family.
_FAMILIES: dict[str, str] = {
    "all":       "Everything",
    "native":    "Native skills",
    "openclaw":  "OpenClaw cloud agent",
    "tool":      "OpenClaw local (V1 hybrid)",
    "llm":       "Direct LLM",
    "cloud":     "Cloud routing (RoutedBackend)",
}


def _match_family(entry_source: str, family: str) -> bool:
    if family == "all":
        return True
    if family == "cloud":
        # RoutedBackend writes "cloud:gemini" / "cloud:anthropic" etc.
        return entry_source.startswith("cloud:")
    return entry_source == family


@router.get("/", response_class=HTMLResponse)
async def audit_index(
    request: Request,
    family: str = Query("all"),
    n: int = Query(50, ge=1, le=500),
) -> HTMLResponse:
    if family not in _FAMILIES:
        family = "all"
    data_dir = request.app.state.data_dir
    al = AuditLog(data_dir)
    # Over-read by 4x — the family filter drops a chunk, and we'd
    # rather show the user the requested N (or close to it) than
    # show an honest 50 entries that turn into 6 after filtering.
    raw = al.get_recent(n=n * 4)
    entries = [e for e in raw if _match_family(e.get("source", ""), family)]
    entries = entries[-n:]

    # Per-family counts for the filter buttons — gives the user a sense
    # of how active each path has been. Read from the same `raw` slice
    # so the numbers correspond to "what's in the recent window."
    counts = {
        f: sum(1 for e in raw if _match_family(e.get("source", ""), f))
        for f in _FAMILIES
    }
    return request.app.state.templates.TemplateResponse(
        request, "audit/index.html",
        {
            "entries": entries,
            "families": _FAMILIES,
            "active_family": family,
            "counts": counts,
            "n": n,
        },
    )


@router.post("/clear", response_class=RedirectResponse, status_code=303)
async def clear(request: Request) -> str:
    p = request.app.state.data_dir / "audit_log.jsonl"
    if p.exists():
        p.unlink()
    return "/audit-log/"
