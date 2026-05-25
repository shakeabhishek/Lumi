from __future__ import annotations

import json

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ....skills.audit_log import AuditLog
from ..persistence import load_settings

router = APIRouter()


def _summarize_todos(data_dir) -> dict[str, int]:
    """Open + done counts from todos.jsonl. Returns zeros if the file
    doesn't exist or is unreadable — never raises into the dashboard."""
    p = data_dir / "todos.jsonl"
    if not p.exists():
        return {"open": 0, "done": 0}
    open_n = done_n = 0
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                t = json.loads(line)
            except json.JSONDecodeError:
                continue
            if t.get("done_at"):
                done_n += 1
            else:
                open_n += 1
    except OSError:
        pass
    return {"open": open_n, "done": done_n}


def _memory_count(data_dir, memory_enabled: bool) -> int | None:
    """Total memories stored. None means "memory feature is off / deps
    missing" — the tile shows "—" rather than 0 in that case, so the
    user can tell apart "no memories yet" (0) from "memory not active"."""
    if not memory_enabled:
        return None
    try:
        from ....runtime.memory import MemoryStore  # noqa: PLC0415

        if not MemoryStore.is_available():
            return None
        store = MemoryStore(data_dir)
        col = store._collection                   # noqa: SLF001
        return col.count() if col is not None else None
    except Exception:
        return None


def _last_cloud_route(recent: list[dict]) -> str | None:
    """Find the most recent cloud:* audit entry — surfaces "Lumi has
    been using your cloud quota" without needing to click into the
    audit log. None if no cloud route in the recent window."""
    for entry in reversed(recent):
        src = entry.get("source", "")
        if src.startswith("cloud:"):
            return src
    return None


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    data_dir = request.app.state.data_dir
    settings = load_settings(data_dir)

    if not settings.onboarding_complete:
        return RedirectResponse(url=f"/onboarding/{settings.onboarding_step}")  # type: ignore[return-value]

    audit_log = AuditLog(data_dir)
    recent = audit_log.get_recent(n=10)

    return request.app.state.templates.TemplateResponse(
        request, "dashboard.html",
        {
            "settings": settings,
            "recent": recent,
            "todos": _summarize_todos(data_dir),
            "memory_count": _memory_count(data_dir, settings.memory_enabled),
            "last_cloud_route": _last_cloud_route(recent),
        },
    )
