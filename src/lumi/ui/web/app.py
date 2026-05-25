"""FastAPI application factory for the Lumi web dashboard.

Usage (dev):
    uv run lumi web

The app serves at http://localhost:8080. On a real Pi it would be
reachable at http://lumi.local via mDNS (Phase 5).
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ...runtime.storage import secure_data_dir
from .csrf import CSRFMiddleware, csrf_token_for
from .device_samplers import start_samplers

_HERE = Path(__file__).parent
TEMPLATES_DIR = _HERE / "templates"
STATIC_DIR = _HERE / "static"


def create_app(data_dir: Path) -> FastAPI:
    from .routes.audit import router as audit_router
    from .routes.chat import router as chat_router
    from .routes.context_api import router as context_router
    from .routes.dashboard import router as dashboard_router
    from .routes.dev import router as dev_router
    from .routes.device_display import router as device_display_router
    from .routes.journal import router as journal_router
    from .routes.onboarding import router as onboarding_router
    from .routes.settings import router as settings_router
    from .routes.skills import router as skills_router

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        # Start background samplers that feed the device display via the
        # DeviceBus. Cancel them on shutdown so uvicorn can exit cleanly.
        sampler_tasks = start_samplers(_app)
        try:
            yield
        finally:
            for task in sampler_tasks:
                task.cancel()
            for task in sampler_tasks:
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task

    app = FastAPI(title="Lumi", docs_url=None, redoc_url=None, lifespan=lifespan)

    import sys  # noqa: PLC0415

    app.add_middleware(CSRFMiddleware)

    # At-rest hardening: ensure the data dir + its sensitive files are 0700/0600.
    secure_data_dir(data_dir)
    app.state.data_dir = data_dir
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    # Expose csrf_token() to every template so forms/HTMX calls can include
    # the token without each route having to thread it manually.
    templates.env.globals["csrf_token"] = csrf_token_for
    app.state.templates = templates
    app.state.platform = sys.platform

    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    app.include_router(dashboard_router)
    app.include_router(chat_router, prefix="/chat")
    app.include_router(onboarding_router, prefix="/onboarding")
    app.include_router(settings_router, prefix="/settings")
    app.include_router(skills_router, prefix="/skills")
    app.include_router(audit_router, prefix="/audit-log")
    app.include_router(journal_router, prefix="/journal")
    app.include_router(dev_router, prefix="/dev")
    app.include_router(context_router, prefix="/api")
    app.include_router(device_display_router, prefix="/device-display")

    return app
