"""Developer dashboard — hardware status, pipeline latency, live config."""

from __future__ import annotations

import shutil
import sys

from fastapi import APIRouter, Request
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
