from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ....skills.audit_log import AuditLog
from ..persistence import AVAILABLE_SKILLS, NATIVE_SKILLS, load_settings, save_settings

router = APIRouter()


_NATIVE_NAMES = {s["name"] for s in NATIVE_SKILLS}


def _toggle_button(skill_name: str, kind: str, enabled: bool) -> str:
    """HTMX partial returned by both the OpenClaw and native toggle
    routes. `kind` is the URL prefix segment — 'openclaw' or 'native'."""
    cls = "toggle on" if enabled else "toggle off"
    label = "On" if enabled else "Off"
    return (
        f'<button class="{cls}" '
        f'hx-post="/skills/{kind}/{skill_name}/toggle" '
        f'hx-target="this" hx-swap="outerHTML">{label}</button>'
    )


@router.get("/", response_class=HTMLResponse)
async def skills_index(request: Request) -> HTMLResponse:
    data_dir = request.app.state.data_dir
    settings = load_settings(data_dir)
    audit_log = AuditLog(data_dir)
    recent = audit_log.get_recent(n=20)
    # Decorate native list with on/off per current settings — opt-out,
    # so anything NOT in disabled_native_skills is considered on.
    disabled = set(settings.disabled_native_skills)
    natives = [
        {**s, "enabled": s["name"] not in disabled}
        for s in NATIVE_SKILLS
    ]
    return request.app.state.templates.TemplateResponse(
        request, "skills/index.html",
        {
            "settings": settings,
            "available_skills": AVAILABLE_SKILLS,
            "native_skills": natives,
            "recent": recent,
        },
    )


@router.post("/openclaw/{skill_name}/toggle", response_class=HTMLResponse)
async def toggle_openclaw_skill(request: Request, skill_name: str) -> HTMLResponse:
    """Toggle an OpenClaw plugin. Flips enabled_skills and invalidates
    the cached chat session so the bridge rebuilds with the new
    allow-list — without this the toggle was cosmetic."""
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
    # save_settings touches user_settings.json mtime which the chat
    # route uses to invalidate its cached session — see
    # routes/chat.py:_settings_mtime.
    return HTMLResponse(_toggle_button(skill_name, "openclaw", enabled))


@router.post("/native/{skill_name}/toggle", response_class=HTMLResponse)
async def toggle_native_skill(request: Request, skill_name: str) -> HTMLResponse:
    """Toggle a native skill via opt-out — defaulting to enabled.
    Stored as `disabled_native_skills` rather than a positive list
    so newly-added native skills are on by default for existing users."""
    if skill_name not in _NATIVE_NAMES:
        return HTMLResponse(status_code=404)
    data_dir = request.app.state.data_dir
    s = load_settings(data_dir)
    if skill_name in s.disabled_native_skills:
        s.disabled_native_skills.remove(skill_name)
        enabled = True
    else:
        s.disabled_native_skills.append(skill_name)
        enabled = False
    save_settings(data_dir, s)
    return HTMLResponse(_toggle_button(skill_name, "native", enabled))


# Backwards-compat: the previous /skills/{name}/toggle route assumed
# OpenClaw. Keep it pointing at the openclaw variant so any external
# scripts that were calling it continue to work. Internal callers (the
# template) now go through the new explicit /openclaw/ + /native/ paths.
@router.post("/{skill_name}/toggle", response_class=HTMLResponse, include_in_schema=False)
async def _legacy_toggle(request: Request, skill_name: str) -> HTMLResponse:
    return await toggle_openclaw_skill(request, skill_name)


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
