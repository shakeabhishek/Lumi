"""FastAPI application factory for the Lumi web dashboard.

Usage (dev):
    uv run lumi web

The app serves at http://localhost:8080. On a real Pi it would be
reachable at http://lumi.local via mDNS (Phase 5).
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

_HERE = Path(__file__).parent
TEMPLATES_DIR = _HERE / "templates"
STATIC_DIR = _HERE / "static"


def create_app(data_dir: Path) -> FastAPI:
    from .routes.dashboard import router as dashboard_router
    from .routes.dev import router as dev_router
    from .routes.onboarding import router as onboarding_router
    from .routes.settings import router as settings_router
    from .routes.skills import router as skills_router

    app = FastAPI(title="Lumi", docs_url=None, redoc_url=None)

    app.state.data_dir = data_dir
    app.state.templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    app.include_router(dashboard_router)
    app.include_router(onboarding_router, prefix="/onboarding")
    app.include_router(settings_router, prefix="/settings")
    app.include_router(skills_router, prefix="/skills")
    app.include_router(dev_router, prefix="/dev")

    return app
