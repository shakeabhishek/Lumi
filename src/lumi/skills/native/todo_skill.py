"""Todo skill — local task list with open/done state.

Sibling to NotesSkill: notes are immutable observations ("I take oat
milk"), todos are pending tasks that move from open → done over time.
Persisted as JSONL so the list survives restarts; small enough to
rewrite on completion / deletion without a database.

Triggers:
  "add to my todo list: ..." / "todo: ..." / "I need to ..."  → add
  "what's on my todo list" / "show my todos" / "list todos"   → list open
  "mark X as done" / "complete X" / "I finished X"            → complete
  "remove X from todos" / "delete X from todos"               → remove
  "clear (all) todos" / "wipe my todos"                       → wipe
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ...log import get_logger
from ..base import NativeSkill, SkillResult

log = get_logger(__name__)

# Order matters in execute(): more-specific patterns first so "complete
# the X todo" doesn't accidentally match the add path.
_CLEAR = re.compile(
    r"\b(clear|wipe|delete|forget)(?:\s+(?:all\s+my|all|my))?\s+todos?\b",
    re.IGNORECASE,
)
_LIST = re.compile(
    r"\b(?:what(?:'s| is) on (?:my )?todo|"
    r"show (?:me )?(?:my )?todos?|"
    r"list (?:my )?todos?|"
    r"read (?:me )?(?:my )?todos?)\b",
    re.IGNORECASE,
)
_COMPLETE = re.compile(
    r"^(?:please\s+)?(?:mark|complete|finish|check off|i (?:just )?finished|i'?ve finished|done with)\s+(.+?)(?:\s+(?:as|is)\s+done)?[?.!]?$",
    re.IGNORECASE,
)
_REMOVE = re.compile(
    r"^(?:please\s+)?(?:remove|drop|cancel|delete)\s+(.+?)\s+from\s+(?:my\s+)?todos?[?.!]?$",
    re.IGNORECASE,
)
_ADD = re.compile(
    r"^(?:please\s+)?(?:add (?:to (?:my )?todo(?: list)?[:,]?\s+)?|"
    r"todo[:,]?\s+|"
    r"i need to\s+|"
    r"i have to\s+|"
    r"i should\s+|"
    r"remind me to\s+)(.+)",
    re.IGNORECASE,
)

_FILENAME = "todos.jsonl"
_MAX_LIST = 10


class TodoSkill(NativeSkill):
    def __init__(self, data_dir: Path) -> None:
        self._path = data_dir / _FILENAME

    # ── matching ────────────────────────────────────────────────────────────

    def matches(self, transcript: str) -> bool:
        # "I need to call mom" matches _ADD even without "todo" in it — the
        # phrasing IS the intent. Order matches execute().
        return bool(
            _CLEAR.search(transcript)
            or _LIST.search(transcript)
            or _COMPLETE.match(transcript)
            or _REMOVE.match(transcript)
            or _ADD.match(transcript)
        )

    def execute(self, transcript: str) -> SkillResult:
        if _CLEAR.search(transcript):
            return self._clear()
        if _LIST.search(transcript):
            return self._list_open()
        m = _REMOVE.match(transcript)
        if m:
            return self._remove(m.group(1).strip().rstrip("?.!"))
        m = _COMPLETE.match(transcript)
        if m:
            return self._complete(m.group(1).strip().rstrip("?.!"))
        m = _ADD.match(transcript)
        if m:
            return self._add(m.group(1).strip().rstrip("?.!"))
        return SkillResult(text="I didn't catch the todo.")

    # ── operations ──────────────────────────────────────────────────────────

    def _add(self, text: str) -> SkillResult:
        if not text:
            return SkillResult(text="What's the todo?")
        entry = {
            "id": uuid.uuid4().hex[:8],
            "ts": datetime.now(timezone.utc).isoformat(),
            "text": text,
            "done_at": None,
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        log.info("todo.added", chars=len(text))
        return SkillResult(text=f"Added to your list: {text}.")

    def _list_open(self) -> SkillResult:
        todos = self._load()
        open_todos = [t["text"] for t in todos if not t.get("done_at")]
        if not open_todos:
            return SkillResult(text="Nothing on your todo list.")
        recent = open_todos[-_MAX_LIST:]
        if len(open_todos) == 1:
            return SkillResult(text=f"One todo: {recent[0]}.")
        joined = "; ".join(recent)
        suffix = f" ({len(open_todos)} open)" if len(open_todos) > _MAX_LIST else ""
        return SkillResult(text=f"Your todos{suffix}: {joined}.")

    def _complete(self, query: str) -> SkillResult:
        return self._mutate_match(
            query,
            on_match=lambda t: {**t, "done_at": datetime.now(timezone.utc).isoformat()},
            on_success=lambda matched: f"Marked done: {matched}.",
            already_msg=lambda matched: f"Already done: {matched}.",
            skip_filter=lambda t: bool(t.get("done_at")),
            empty_msg="No open todos.",
            no_match_msg=lambda q: f"No open todo matching {q!r}.",
        )

    def _remove(self, query: str) -> SkillResult:
        return self._mutate_match(
            query,
            on_match=None,                              # signals deletion
            on_success=lambda matched: f"Removed: {matched}.",
            already_msg=None,
            skip_filter=lambda t: False,                # any todo, done or not
            empty_msg="No todos to remove.",
            no_match_msg=lambda q: f"No todo matching {q!r}.",
        )

    def _clear(self) -> SkillResult:
        count = len(self._load())
        if count == 0:
            return SkillResult(text="No todos to clear.")
        self._path.unlink(missing_ok=True)
        log.info("todo.cleared", count=count)
        return SkillResult(text=f"Cleared {count} todo{'s' if count != 1 else ''}.")

    # ── shared mutation helper ──────────────────────────────────────────────
    #
    # Complete and remove share a substring-match-then-rewrite pattern;
    # keeping it factored out avoids two near-identical _save_all() copies
    # drifting apart.

    def _mutate_match(
        self, query: str, *,
        on_match,                  # callable(todo)->updated_todo OR None (delete)
        on_success,                # callable(matched_text)->reply string
        already_msg,               # callable(matched_text)->reply OR None
        skip_filter,               # callable(todo)->bool (skip if True)
        empty_msg: str,
        no_match_msg,              # callable(query)->reply string
    ) -> SkillResult:
        todos = self._load()
        if not todos:
            return SkillResult(text=empty_msg)
        q = query.lower()

        # Find the most recent open match — recency biases towards what
        # the user was just talking about.
        match_idx = None
        for i in range(len(todos) - 1, -1, -1):
            t = todos[i]
            if q not in t["text"].lower():
                continue
            if skip_filter(t):
                if already_msg:
                    return SkillResult(text=already_msg(t["text"]))
                # fall through — remove takes precedence over "already done"
            match_idx = i
            break

        if match_idx is None:
            return SkillResult(text=no_match_msg(query))

        matched = todos[match_idx]
        if on_match is None:
            del todos[match_idx]
        else:
            todos[match_idx] = on_match(matched)
        self._save_all(todos)
        return SkillResult(text=on_success(matched["text"]))

    # ── persistence ─────────────────────────────────────────────────────────

    def _load(self) -> list[dict]:
        if not self._path.exists():
            return []
        out: list[dict] = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out

    def _save_all(self, todos: list[dict]) -> None:
        # Atomic rewrite — protects against partial truncation on crash.
        # See runtime/storage.py for the canonical pattern; using a
        # simpler inline tempfile here since the data isn't sensitive
        # (no chmod 0600 needed) but the atomicity matters.
        import os
        import tempfile

        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(
            prefix=self._path.name + ".", suffix=".tmp",
            dir=str(self._path.parent),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                for t in todos:
                    f.write(json.dumps(t) + "\n")
            os.replace(tmp, self._path)
        except Exception:
            Path(tmp).unlink(missing_ok=True)
            raise
