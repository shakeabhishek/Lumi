"""Notes skill — local quick-capture and recall.

Persists short notes as JSONL on disk so they survive restarts. Recall is a
simple case-insensitive substring scan, which is fast and predictable for
small note collections. Memory store handles richer semantic recall via
embeddings — this skill is for explicit "remember X" / "what did I note
about Y" intents.

Triggers:
  "remember that ..." / "make a note that ..."   → append note
  "note: ..."                                     → append note
  "what did I note about X" / "find notes ..."   → recall
  "show my notes" / "list notes"                  → all notes
  "clear all notes"                               → wipe
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from ...log import get_logger
from ..base import NativeSkill, SkillResult

log = get_logger(__name__)

_SAVE = re.compile(
    r"^(?:please\s+)?(?:remember|note|make a note|jot down|save)\b(?:\s+(?:that|this|the following))?[:,]?\s+(.+)",
    re.IGNORECASE,
)
_FIND = re.compile(
    r"\b(what did I note about|find (?:my )?notes (?:about|on|for)|search (?:my )?notes (?:for|about))\s+(.+)",
    re.IGNORECASE,
)
_LIST = re.compile(r"\b(show|list|read)(?:\s+(?:all|my))?\s+notes\b", re.IGNORECASE)
_CLEAR = re.compile(r"\b(clear|delete|wipe|forget)(?:\s+(?:all|my))?\s+notes\b", re.IGNORECASE)

_FILENAME = "notes.jsonl"
_MAX_LIST = 10


class NotesSkill(NativeSkill):
    def __init__(self, data_dir: Path) -> None:
        self._path = data_dir / _FILENAME

    # ── matching ────────────────────────────────────────────────────────────

    def matches(self, transcript: str) -> bool:
        return bool(
            _CLEAR.search(transcript)
            or _LIST.search(transcript)
            or _FIND.search(transcript)
            or _SAVE.search(transcript)
        )

    def execute(self, transcript: str) -> SkillResult:
        if _CLEAR.search(transcript):
            return self._clear()
        if _LIST.search(transcript):
            return self._list_all()
        m = _FIND.search(transcript)
        if m:
            return self._find(m.group(2).strip().rstrip("?.!"))
        m = _SAVE.search(transcript)
        if m:
            return self._save(m.group(1).strip().rstrip("?.!"))
        return SkillResult(text="I didn't catch the note.")

    # ── operations ──────────────────────────────────────────────────────────

    def _save(self, text: str) -> SkillResult:
        if not text:
            return SkillResult(text="What should I remember?")
        entry = {"ts": datetime.now(timezone.utc).isoformat(), "text": text}
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        log.info("notes.saved", chars=len(text))
        return SkillResult(text=f"Got it. I'll remember: {text}.")

    def _find(self, query: str) -> SkillResult:
        notes = self._load()
        if not notes:
            return SkillResult(text="No notes yet.")
        q = query.lower()
        hits = [n["text"] for n in notes if q in n["text"].lower()]
        if not hits:
            return SkillResult(text=f"No notes matching {query!r}.")
        if len(hits) == 1:
            return SkillResult(text=f"One note: {hits[0]}.")
        joined = "; ".join(hits[:3])
        return SkillResult(text=f"{len(hits)} matching notes: {joined}.")

    def _list_all(self) -> SkillResult:
        notes = self._load()
        if not notes:
            return SkillResult(text="No notes yet.")
        recent = [n["text"] for n in notes[-_MAX_LIST:]]
        return SkillResult(text=f"Your notes: {'; '.join(recent)}.")

    def _clear(self) -> SkillResult:
        count = len(self._load())
        if count == 0:
            return SkillResult(text="No notes to clear.")
        self._path.unlink(missing_ok=True)
        log.info("notes.cleared", count=count)
        return SkillResult(text=f"Cleared {count} note{'s' if count != 1 else ''}.")

    # ── persistence ─────────────────────────────────────────────────────────

    def _load(self) -> list[dict[str, str]]:
        if not self._path.exists():
            return []
        notes: list[dict[str, str]] = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                notes.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return notes
