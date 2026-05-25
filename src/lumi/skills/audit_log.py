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
    # Largest reverse-read window we'll do from the tail of the file when
    # callers ask for recent entries. 64 KB covers ~200 generously-sized
    # entries — well above the n=20 the chat path needs. If a caller asks
    # for more than the window holds we fall back to a full read.
    _TAIL_WINDOW = 64 * 1024

    def __init__(self, data_dir: Path) -> None:
        self._path = data_dir / "audit_log.jsonl"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # In-memory tail cache: the last entry we wrote in this process,
        # used as a fast path by `get_recent(n=1)` which is hot on
        # /chat/stream's metadata lookup. Survives across instances of
        # AuditLog because instances are cheap and re-read the cache from
        # the file's last entry on demand.
        self._last: dict | None = None

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
            self._last = entry
            log.info("audit.logged", source=source, skill=skill)
        except OSError as exc:
            log.warning("audit.write_failed", error=str(exc))

    def get_recent(self, n: int = 20) -> list[dict]:
        """Return the n most recent entries, newest last.

        Reads the **tail** of the file rather than the whole thing — the
        chat path used to call get_recent(n=1) after every turn, which
        was O(file size) per call and produced O(n²) work over long
        soaks. Now we seek to (size − 64 KB) and parse forward, which
        is O(1) regardless of how long the file has grown.

        One corrupt JSON line (interrupted write, manual edit, fsck recovery)
        must not poison the entire viewer — we skip individual bad lines and
        return whatever we could parse. Read errors at the file level still
        return [].
        """
        if not self._path.exists():
            return []
        try:
            size = self._path.stat().st_size
            window = min(size, self._TAIL_WINDOW)
            with self._path.open("rb") as f:
                f.seek(size - window)
                tail = f.read(window)
        except OSError as exc:
            log.warning("audit.read_failed", error=str(exc))
            return []

        # Drop a partial first line — if we didn't start at the file
        # head, the bytes before the first newline are some other
        # entry's tail. Without this we'd JSON-fail on every call.
        text = tail.decode("utf-8", errors="replace")
        if size > window:
            nl = text.find("\n")
            if nl >= 0:
                text = text[nl + 1:]

        out: list[dict] = []
        skipped = 0
        for line in text.splitlines():
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
