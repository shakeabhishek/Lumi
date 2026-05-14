"""Daily journal — read past summaries, generate today's on demand."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from ....config import get_settings
from ....llm import make_llm_backend
from ....runtime.journal import JournalGenerator
from ....skills.audit_log import AuditLog
from ..persistence import load_settings

router = APIRouter()


def _journal(data_dir) -> JournalGenerator:
    cfg = get_settings()
    return JournalGenerator(
        data_dir=data_dir,
        llm=make_llm_backend(cfg),
        audit_log=AuditLog(data_dir),
    )


@router.get("/", response_class=HTMLResponse)
async def journal_index(request: Request) -> HTMLResponse:
    """List all cached daily journal entries, newest first."""
    data_dir = request.app.state.data_dir
    entries = _journal(data_dir).all_entries()
    return request.app.state.templates.TemplateResponse(
        request, "journal.html",
        {"settings": load_settings(data_dir), "entries": entries},
    )


@router.post("/today", response_class=HTMLResponse)
async def journal_today(request: Request) -> HTMLResponse:
    """Generate (or fetch cached) today's summary and return the rendered card."""
    data_dir = request.app.state.data_dir
    entry = _journal(data_dir).get_or_generate(date.today())
    return request.app.state.templates.TemplateResponse(
        request, "journal_entry.html",
        {"entry": entry},
    )
