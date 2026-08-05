"""Config for the vision worker — argparse + env fallback.

Deliberately no pydantic-settings/typer: this venv is already heavy with
mediapipe + opencv, and one CLI entrypoint doesn't need a config
framework. Mirrors the root project's LUMI_* env var naming convention
without importing anything from it.
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    data_dir: Path
    web_base_url: str
    settings_poll_s: float = 2.0  # how often to re-check camera_enabled when off
    presence_heartbeat_s: float = 5.0  # POST /api/presence at least this often, even unchanged


def load_config() -> Config:
    parser = argparse.ArgumentParser(prog="lumi-vision-worker")
    parser.add_argument(
        "--data-dir",
        default=os.environ.get("LUMI_DATA_DIR", ""),
        help="Lumi's data directory (for user_settings.json and .wake_trigger.json). "
        "Falls back to LUMI_DATA_DIR env var.",
    )
    parser.add_argument(
        "--web-base-url",
        default=os.environ.get("LUMI_WEB_BASE_URL", "http://127.0.0.1:8080"),
        help="Base URL of the main Lumi web app, for pushing gesture/presence events. "
        "Falls back to LUMI_WEB_BASE_URL env var.",
    )
    args = parser.parse_args()

    if not args.data_dir:
        raise SystemExit(
            "lumi-vision-worker: --data-dir is required (or set LUMI_DATA_DIR)"
        )

    return Config(data_dir=Path(args.data_dir), web_base_url=args.web_base_url)
