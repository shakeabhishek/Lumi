"""Skill audit log — persists every skill invocation to a JSON lines file.

Format (one JSON object per line):
  {"ts": "2026-...", "source": "native|openclaw|llm", "skill": "timer", "input": "...", "result": "..."}

The Phase 3 web UI reads this file directly for the audit log viewer.
Stored at data_dir/audit_log.jsonl — append-only, human-readable.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from ..log import get_logger

log = get_logger(__name__)

Source = Literal["native", "tool", "openclaw", "llm"]
# "tool"     = bridge in ollama mode (local Python tool impls)
# "openclaw" = bridge in openclaw_cloud mode (real OpenClaw agent loop)


class AuditLog:
    def __init__(self, data_dir: Path) -> None:
        self._path = data_dir / "audit_log.jsonl"
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, source: Source, skill: str, input_text: str, result_text: str) -> None:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "source": source,
            "skill": skill,
            "input": input_text,
            "result": result_text,
        }
        try:
            with self._path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
            log.info("audit.logged", source=source, skill=skill)
        except OSError as exc:
            log.warning("audit.write_failed", error=str(exc))

    def get_recent(self, n: int = 20) -> list[dict]:
        """Return the n most recent entries, newest last.

        One corrupt JSON line (interrupted write, manual edit, fsck recovery)
        must not poison the entire viewer — we skip individual bad lines and
        return whatever we could parse. Read errors at the file level still
        return [].
        """
        if not self._path.exists():
            return []
        try:
            lines = self._path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            log.warning("audit.read_failed", error=str(exc))
            return []

        out: list[dict] = []
        skipped = 0
        for line in lines[-n * 2:]:        # over-read in case some are bad
            if not line.strip():
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                skipped += 1
                continue
        if skipped:
            log.warning("audit.skipped_corrupt_lines", n=skipped)
        return out[-n:]
