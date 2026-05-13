from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ....skills.audit_log import AuditLog
from ..persistence import load_settings

router = APIRouter()


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
        {"settings": settings, "recent": recent},
    )
