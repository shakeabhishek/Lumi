"""Developer dashboard — hardware status, pipeline latency, live config, skill test panel."""

from __future__ import annotations

import shutil
import sys
import time
from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from ....runtime.perf import PerfLog
from ..persistence import load_settings

router = APIRouter()


def _check(module: str) -> bool:
    try:
        __import__(module)
        return True
    except ImportError:
        return False


def _hw_status() -> dict[str, bool | str]:
    return {
        "whisper": _check("faster_whisper"),
        "piper": bool(shutil.which("piper")),
        "ollama": bool(shutil.which("ollama")),
        "pygame": _check("pygame"),
        "pynput": _check("pynput"),
        "chromadb": _check("chromadb"),
        "resemblyzer": _check("resemblyzer"),
        "psutil": _check("psutil"),
        "platform": sys.platform,
        "python": sys.version.split()[0],
    }


@router.get("/", response_class=HTMLResponse)
async def dev_index(request: Request) -> HTMLResponse:
    data_dir = request.app.state.data_dir
    settings = load_settings(data_dir)
    perf_log = PerfLog(data_dir)
    recent_perf = perf_log.get_recent(n=25)
    hw = _hw_status()
    return request.app.state.templates.TemplateResponse(
        request, "dev.html",
        {"settings": settings, "hw": hw, "recent_perf": recent_perf},
    )


@router.get("/perf/rows", response_class=HTMLResponse)
async def perf_rows(request: Request) -> HTMLResponse:
    """HTMX partial — refreshes just the latency table rows."""
    data_dir = request.app.state.data_dir
    recent_perf = PerfLog(data_dir).get_recent(n=25)
    return request.app.state.templates.TemplateResponse(
        request, "dev_perf_rows.html",
        {"recent_perf": recent_perf},
    )


# ───────────────────────────────────────────────────────────────────────────
# Skill test panel — POST a transcript, see which handler fires + latency
# ───────────────────────────────────────────────────────────────────────────


@router.post("/test", response_class=HTMLResponse)
async def test_transcript(
    request: Request,
    transcript: Annotated[str, Form()],
) -> HTMLResponse:
    """Drive the live SkillRouter as if the user had said `transcript` aloud.

    Returns an HTMX partial showing: which handler fired (native skill name,
    openclaw, or llm), the response text, and end-to-end latency.
    """
    from ....audio.tts import _PrintTTS  # noqa: PLC0415
    from ....config import get_settings  # noqa: PLC0415
    from ....llm.ollama_backend import MockLLMBackend  # noqa: PLC0415
    from ....runtime.conversation import ConversationManager  # noqa: PLC0415
    from ....skills.audit_log import AuditLog  # noqa: PLC0415
    from ....skills.router import SkillRouter  # noqa: PLC0415

    data_dir = request.app.state.data_dir
    cfg = get_settings()
    settings = load_settings(data_dir)

    # Build an ephemeral router. Use MockLLMBackend so the panel doesn't depend
    # on ollama being up; native + openclaw paths exercise the real handlers.
    tts = _PrintTTS()
    llm = MockLLMBackend(response="(mock LLM reply — start ollama for real responses)")
    conv = ConversationManager(llm, mode=cfg.mode)
    audit = AuditLog(data_dir)
    router_ = SkillRouter(
        conversation=conv, tts=tts,
        bridge=None,                # skip openclaw bridge from the panel
        audit_log=audit,
        clipboard_enabled=settings.clipboard_enabled,
        data_dir=data_dir,
    )

    t0 = time.perf_counter()
    reply = router_.handle(transcript.strip())
    elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)

    # Pull the last audit entry to learn which handler fired.
    last = audit.get_recent(n=1)
    handler = last[0]["source"] if last else "unknown"
    skill = last[0]["skill"] if last else "?"

    return request.app.state.templates.TemplateResponse(
        request, "dev_test_result.html",
        {
            "transcript": transcript,
            "reply": reply,
            "handler": handler,
            "skill": skill,
            "elapsed_ms": elapsed_ms,
        },
    )
