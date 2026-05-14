"""Daily journal — Lumi summarizes each day's conversations into 3 bullets.

Reads the audit log + recent memory and feeds them through the local LLM with
a focused summarization prompt. Caches results to `data_dir/journal.jsonl`
keyed by date so we don't re-summarize completed days.

Generation is on-demand (when the user opens /journal or runs `lumi journal`),
keeping the runtime simple on a laptop — no background scheduler needed.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

from ..llm.ollama_backend import LLMBackend, Message
from ..log import get_logger
from ..skills.audit_log import AuditLog

log = get_logger(__name__)

_FILENAME = "journal.jsonl"

_PROMPT = (
    "You are summarizing the user's day with Lumi. Below are the conversations "
    "they had today, listed oldest first. Write a warm, calm 3-bullet summary "
    "that captures: (1) what the user worked on or thought about, (2) anything "
    "they asked Lumi to remember or set up, (3) a gentle note about how the "
    "day felt — only if there's signal for it.\n\n"
    "Constraints: 3 bullets. Each one short. No headings, no preamble. Refer to "
    "the user in second person (\"you\"). Skip filler interactions like timers "
    "and volume changes.\n\n"
    "Conversations:\n{transcript}"
)


class JournalGenerator:
    """On-demand daily summarization. Cached to JSONL by ISO date."""

    def __init__(self, data_dir: Path, llm: LLMBackend, audit_log: AuditLog) -> None:
        self._path = data_dir / _FILENAME
        self._llm = llm
        self._audit = audit_log

    # ── public ──────────────────────────────────────────────────────────────

    def get_or_generate(self, day: date | None = None) -> dict[str, str]:
        """Return cached summary for `day` (default today). Generates if missing.

        Empty-conversation days return {"date": ..., "summary": "(no conversations)"}.
        """
        day = day or date.today()
        cached = self._lookup(day)
        if cached is not None:
            return cached

        turns = self._turns_for(day)
        if not turns:
            entry = {"date": day.isoformat(), "summary": "(no conversations)", "n_turns": 0}
            self._append(entry)
            return entry

        transcript = "\n".join(
            f"You: {t['input']}\nLumi: {t['result']}" for t in turns
        )
        prompt = _PROMPT.format(transcript=transcript)
        messages: list[Message] = [
            {"role": "system", "content": "You are Lumi, summarizing the day for the user."},
            {"role": "user", "content": prompt},
        ]
        try:
            summary = "".join(self._llm.chat(messages)).strip()
        except Exception as exc:
            log.warning("journal.llm_failed", error=str(exc))
            summary = "(summary unavailable — LLM error)"

        entry = {
            "date": day.isoformat(),
            "summary": summary,
            "n_turns": len(turns),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        self._append(entry)
        log.info("journal.generated", date=day.isoformat(), turns=len(turns))
        return entry

    def all_entries(self) -> list[dict[str, str]]:
        """Return all cached journal entries, newest day first."""
        if not self._path.exists():
            return []
        entries: list[dict[str, str]] = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        # newest first
        return sorted(entries, key=lambda e: e.get("date", ""), reverse=True)

    # ── internals ───────────────────────────────────────────────────────────

    def _turns_for(self, day: date) -> list[dict[str, str]]:
        """All audit-log entries from the given day."""
        target = day.isoformat()
        recent = self._audit.get_recent(n=500)
        return [e for e in recent if e.get("ts", "").startswith(target)]

    def _lookup(self, day: date) -> dict[str, str] | None:
        for entry in self.all_entries():
            if entry.get("date") == day.isoformat():
                return entry
        return None

    def _append(self, entry: dict[str, str]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
