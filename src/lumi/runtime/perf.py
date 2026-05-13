"""Pipeline performance timing — measures per-stage latency and persists to disk."""

from __future__ import annotations

import json
import time
from pathlib import Path


class PipelineTimer:
    """Records elapsed time at named checkpoints within a single voice turn."""

    def __init__(self) -> None:
        self._t0 = time.perf_counter()
        self._marks: dict[str, float] = {}

    def mark(self, stage: str) -> None:
        """Record elapsed ms since timer creation for this stage."""
        self._marks[stage] = round((time.perf_counter() - self._t0) * 1000, 1)

    def total_ms(self) -> float:
        return max(self._marks.values(), default=0.0)

    def summary(self) -> dict[str, float]:
        return dict(self._marks)

    def log_line(self) -> str:
        parts = "  ".join(f"{k}={v:.0f}ms" for k, v in self._marks.items())
        return f"[perf] total={self.total_ms():.0f}ms  {parts}"


class PerfLog:
    """Append-only JSONL file that stores recent pipeline timing entries."""

    MAX_LINES = 200

    def __init__(self, data_dir: Path) -> None:
        self._path = data_dir / "perf.jsonl"

    def record(self, timer: PipelineTimer) -> None:
        entry = {"ts": round(time.time(), 3), "total_ms": timer.total_ms(), **timer.summary()}
        try:
            with self._path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
            self._trim()
        except OSError:
            pass

    def get_recent(self, n: int = 20) -> list[dict]:
        if not self._path.exists():
            return []
        try:
            lines = [l for l in self._path.read_text(encoding="utf-8").splitlines() if l.strip()]
            entries = []
            for line in lines:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
            return list(reversed(entries[-n:]))
        except OSError:
            return []

    def _trim(self) -> None:
        try:
            lines = self._path.read_text(encoding="utf-8").splitlines()
            if len(lines) > self.MAX_LINES:
                self._path.write_text("\n".join(lines[-self.MAX_LINES:]) + "\n", encoding="utf-8")
        except OSError:
            pass
