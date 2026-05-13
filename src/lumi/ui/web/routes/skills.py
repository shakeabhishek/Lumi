from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ....skills.audit_log import AuditLog
from ..persistence import AVAILABLE_SKILLS, load_settings, save_settings

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def skills_index(request: Request) -> HTMLResponse:
    data_dir = request.app.state.data_dir
    settings = load_settings(data_dir)
    audit_log = AuditLog(data_dir)
    recent = audit_log.get_recent(n=20)
    return request.app.state.templates.TemplateResponse(
        request, "skills/index.html",
        {
            "settings": settings,
            "available_skills": AVAILABLE_SKILLS,
            "recent": recent,
        },
    )


@router.post("/{skill_name}/toggle", response_class=HTMLResponse)
async def toggle_skill(request: Request, skill_name: str) -> HTMLResponse:
    if skill_name not in AVAILABLE_SKILLS:
        return HTMLResponse(status_code=404)
    data_dir = request.app.state.data_dir
    s = load_settings(data_dir)
    if skill_name in s.enabled_skills:
        s.enabled_skills.remove(skill_name)
        enabled = False
    else:
        s.enabled_skills.append(skill_name)
        enabled = True
    save_settings(data_dir, s)
    # Return just the updated toggle button (HTMX swaps this in-place)
    state_class = "toggle on" if enabled else "toggle off"
    state_label = "On" if enabled else "Off"
    return HTMLResponse(
        f'<button class="{state_class}" '
        f'hx-post="/skills/{skill_name}/toggle" '
        f'hx-target="this" hx-swap="outerHTML">'
        f"{state_label}</button>"
    )


@router.get("/audit-log/rows", response_class=HTMLResponse)
async def audit_log_rows(request: Request) -> HTMLResponse:
    """HTMX partial — refreshes just the log rows."""
    data_dir = request.app.state.data_dir
    recent = AuditLog(data_dir).get_recent(n=30)
    return request.app.state.templates.TemplateResponse(
        request, "skills/audit_log_rows.html",
        {"recent": recent},
    )


@router.post("/audit-log/clear", response_class=RedirectResponse, status_code=303)
async def clear_audit_log(request: Request) -> str:
    data_dir = request.app.state.data_dir
    log_path = data_dir / "audit_log.jsonl"
    if log_path.exists():
        log_path.unlink()
    return "/skills"
