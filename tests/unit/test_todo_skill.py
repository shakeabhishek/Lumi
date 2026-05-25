"""Tests for TodoSkill — local task list with open/done state.

Coverage focus:
  * Triggers match the phrasings the README + skill docstring promise
  * Add/list/complete/remove/clear round-trip persists across instances
  * Completion vs removal vs already-done branches
  * Substring match biases toward the most recent matching open todo
  * Persistence file is rewritten atomically (no partial writes)
"""

from __future__ import annotations

import json
from pathlib import Path

from lumi.skills.native.todo_skill import TodoSkill


def _skill(tmp_path: Path) -> TodoSkill:
    return TodoSkill(data_dir=tmp_path)


# ── matching ───────────────────────────────────────────────────────────────


def test_matches_add_phrasings(tmp_path: Path) -> None:
    s = _skill(tmp_path)
    for phrase in [
        "add to my todo list: buy milk",
        "todo: review the PR",
        "I need to call mom",
        "I should book the dentist",
        "remind me to water the plants",
    ]:
        assert s.matches(phrase), phrase


def test_matches_list_phrasings(tmp_path: Path) -> None:
    s = _skill(tmp_path)
    for phrase in [
        "what's on my todo list",
        "show my todos",
        "list todos",
        "show me my todos",
    ]:
        assert s.matches(phrase), phrase


def test_matches_complete_phrasings(tmp_path: Path) -> None:
    s = _skill(tmp_path)
    # Need at least one todo so complete() doesn't bail with "no open todos".
    s.execute("todo: file the expense report")
    for phrase in [
        "mark the expense report as done",
        "complete the expense report",
        "finish the expense report",
        "I finished the expense report",
        "done with the expense report",
    ]:
        assert s.matches(phrase), phrase


def test_no_match_unrelated(tmp_path: Path) -> None:
    s = _skill(tmp_path)
    for phrase in [
        "what's the weather",
        "set a timer for 5 minutes",
        "switch to focus mode",
    ]:
        assert not s.matches(phrase), phrase


# ── add ────────────────────────────────────────────────────────────────────


def test_add_persists_and_lists(tmp_path: Path) -> None:
    s = _skill(tmp_path)
    s.execute("todo: buy milk")
    s.execute("I need to call mom")

    result = s.execute("show my todos")
    assert "buy milk" in result.text
    assert "call mom" in result.text


def test_add_survives_skill_restart(tmp_path: Path) -> None:
    """Persistence is the whole point — a fresh skill instance must
    see what an earlier instance saved."""
    _skill(tmp_path).execute("todo: ship lumi-os")

    fresh = _skill(tmp_path)
    result = fresh.execute("show my todos")
    assert "ship lumi-os" in result.text


def test_add_with_no_content_prompts_user(tmp_path: Path) -> None:
    s = _skill(tmp_path)
    result = s.execute("todo:")
    # Either rejects via "What's the todo?" or fails the match → "didn't catch"
    assert ("todo" in result.text.lower() or "didn't catch" in result.text)


# ── list ───────────────────────────────────────────────────────────────────


def test_list_when_empty(tmp_path: Path) -> None:
    s = _skill(tmp_path)
    result = s.execute("show my todos")
    assert "nothing" in result.text.lower() or "no todos" in result.text.lower()


def test_list_only_shows_open(tmp_path: Path) -> None:
    s = _skill(tmp_path)
    s.execute("todo: buy milk")
    s.execute("todo: file taxes")
    s.execute("mark buy milk as done")

    result = s.execute("show my todos")
    assert "file taxes" in result.text
    assert "buy milk" not in result.text


# ── complete ───────────────────────────────────────────────────────────────


def test_complete_marks_done(tmp_path: Path) -> None:
    s = _skill(tmp_path)
    s.execute("todo: water the plants")

    result = s.execute("mark water the plants as done")
    assert "done" in result.text.lower()

    # File now has done_at set.
    raw = (tmp_path / "todos.jsonl").read_text().strip()
    entry = json.loads(raw)
    assert entry["done_at"] is not None


def test_complete_when_no_match(tmp_path: Path) -> None:
    s = _skill(tmp_path)
    s.execute("todo: buy milk")

    result = s.execute("mark a thing that doesn't exist as done")
    assert "no open todo matching" in result.text.lower()


def test_complete_picks_most_recent_match(tmp_path: Path) -> None:
    """Substring matching should bias to the most recently added open
    todo — if you say 'finish the report' and you've added two
    'report' todos, the latest one wins."""
    s = _skill(tmp_path)
    s.execute("todo: write the Q1 report")
    s.execute("todo: write the Q2 report")

    # Substring match — "report" appears in both. Recency bias should
    # close the LATEST matching open todo (Q2).
    s.execute("finish report")
    result = s.execute("show my todos")
    assert "Q1" in result.text
    assert "Q2" not in result.text


def test_complete_already_done_is_idempotent(tmp_path: Path) -> None:
    s = _skill(tmp_path)
    s.execute("todo: buy milk")
    s.execute("mark buy milk as done")

    # Second attempt should not error; we tell the user it's already done.
    result = s.execute("mark buy milk as done")
    assert "no open todo matching" in result.text.lower() \
        or "already done" in result.text.lower()


# ── remove ─────────────────────────────────────────────────────────────────


def test_remove_deletes_from_list(tmp_path: Path) -> None:
    s = _skill(tmp_path)
    s.execute("todo: buy milk")
    s.execute("todo: file taxes")

    result = s.execute("remove buy milk from my todos")
    assert "removed" in result.text.lower()

    result = s.execute("show my todos")
    assert "buy milk" not in result.text
    assert "file taxes" in result.text


def test_remove_works_on_done_items_too(tmp_path: Path) -> None:
    """Once done, a todo is still in the JSONL until removed or cleared.
    `remove` should reach it; `complete` should not."""
    s = _skill(tmp_path)
    s.execute("todo: send invoice")
    s.execute("mark send invoice as done")

    result = s.execute("remove send invoice from my todos")
    assert "removed" in result.text.lower()


# ── clear ──────────────────────────────────────────────────────────────────


def test_clear_wipes_everything(tmp_path: Path) -> None:
    s = _skill(tmp_path)
    s.execute("todo: a")
    s.execute("todo: b")
    s.execute("todo: c")

    result = s.execute("clear all my todos")
    assert "cleared 3" in result.text.lower() or "cleared" in result.text.lower()

    result = s.execute("show my todos")
    assert "nothing" in result.text.lower() or "no todos" in result.text.lower()


def test_clear_when_empty_is_friendly(tmp_path: Path) -> None:
    s = _skill(tmp_path)
    result = s.execute("clear all my todos")
    assert "no todos" in result.text.lower()


# ── atomic rewrite ─────────────────────────────────────────────────────────


def test_save_all_does_not_leave_tmp_files(tmp_path: Path) -> None:
    """Atomic rewrite should clean up its tempfile on success — a
    leftover .tmp would clutter the data dir and (worse) be picked up
    by `_load()` if it parses as JSON."""
    s = _skill(tmp_path)
    s.execute("todo: a")
    s.execute("mark a as done")

    leftover_tmps = list(tmp_path.glob("todos.jsonl.*.tmp"))
    assert leftover_tmps == [], f"leftover tmpfiles: {leftover_tmps}"
