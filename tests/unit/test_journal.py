"""Tests for JournalGenerator — caching, generation, edge cases."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from lumi.llm.ollama_backend import MockLLMBackend
from lumi.runtime.journal import JournalGenerator
from lumi.skills.audit_log import AuditLog


def _seed_audit(data_dir: Path, day: date, n: int = 3) -> None:
    """Write `n` audit entries with timestamps on the given day."""
    log = AuditLog(data_dir)
    iso_day = day.isoformat()
    for i in range(n):
        # Use the AuditLog.log to keep format consistent, then rewrite ts.
        log.log("native", "timer", f"start timer {i}", f"ok {i}")
    # Rewrite all timestamps to fall on `day`
    path = data_dir / "audit_log.jsonl"
    lines = path.read_text().splitlines()
    rewritten = []
    for i, raw in enumerate(lines):
        entry = json.loads(raw)
        entry["ts"] = f"{iso_day}T09:{i:02d}:00+00:00"
        rewritten.append(json.dumps(entry))
    path.write_text("\n".join(rewritten) + "\n")


def test_generates_summary_for_day_with_turns(tmp_path: Path) -> None:
    _seed_audit(tmp_path, date(2026, 5, 14), n=3)
    llm = MockLLMBackend(response="- you worked on X\n- you set 3 timers\n- it was a focused day")
    j = JournalGenerator(tmp_path, llm, AuditLog(tmp_path))

    entry = j.get_or_generate(date(2026, 5, 14))
    assert entry["date"] == "2026-05-14"
    assert entry["n_turns"] == 3
    assert "you worked on X" in entry["summary"]


def test_returns_cached_entry_without_regen(tmp_path: Path) -> None:
    _seed_audit(tmp_path, date(2026, 5, 14))
    llm = MockLLMBackend(response="first generation")
    j = JournalGenerator(tmp_path, llm, AuditLog(tmp_path))
    first = j.get_or_generate(date(2026, 5, 14))

    # Swap the LLM to one that would produce different output; cache should win.
    j._llm = MockLLMBackend(response="second generation — should NOT appear")
    second = j.get_or_generate(date(2026, 5, 14))
    assert first == second
    assert "first generation" in second["summary"]


def test_empty_day_short_circuits(tmp_path: Path) -> None:
    # No audit log at all.
    llm = MockLLMBackend(response="should not be called")
    j = JournalGenerator(tmp_path, llm, AuditLog(tmp_path))
    entry = j.get_or_generate(date(2026, 5, 14))
    assert entry["n_turns"] == 0
    assert "no conversations" in entry["summary"].lower()
    # Mock LLM should not have received messages for an empty day.
    assert llm.received_messages == []


def test_all_entries_sorted_newest_first(tmp_path: Path) -> None:
    _seed_audit(tmp_path, date(2026, 5, 12), n=1)
    j = JournalGenerator(tmp_path, MockLLMBackend(response="m"), AuditLog(tmp_path))
    j.get_or_generate(date(2026, 5, 12))
    j.get_or_generate(date(2026, 5, 13))
    j.get_or_generate(date(2026, 5, 14))
    entries = j.all_entries()
    dates = [e["date"] for e in entries]
    assert dates == ["2026-05-14", "2026-05-13", "2026-05-12"]


def test_llm_failure_records_fallback(tmp_path: Path) -> None:
    _seed_audit(tmp_path, date(2026, 5, 14))

    class _ExplodingLLM:
        @property
        def model(self) -> str: return "boom"
        def chat(self, _msgs):
            raise RuntimeError("llm down")

    j = JournalGenerator(tmp_path, _ExplodingLLM(), AuditLog(tmp_path))
    entry = j.get_or_generate(date(2026, 5, 14))
    assert "unavailable" in entry["summary"].lower()


def test_only_includes_target_day(tmp_path: Path) -> None:
    """Turns from other days should not bleed into a day's summary."""
    # Seed entries on May 12 and May 14
    _seed_audit(tmp_path, date(2026, 5, 12), n=2)
    # AuditLog appends, so seed a second day by manually appending.
    log = AuditLog(tmp_path)
    log.log("native", "timer", "later day", "ok")
    # Rewrite that last line's ts to May 14.
    path = tmp_path / "audit_log.jsonl"
    lines = path.read_text().splitlines()
    last = json.loads(lines[-1])
    last["ts"] = "2026-05-14T10:00:00+00:00"
    lines[-1] = json.dumps(last)
    path.write_text("\n".join(lines) + "\n")

    captured: list[str] = []

    class _CapturingLLM:
        @property
        def model(self) -> str: return "cap"
        def chat(self, msgs):
            captured.append(msgs[-1]["content"])
            yield "summary"

    j = JournalGenerator(tmp_path, _CapturingLLM(), AuditLog(tmp_path))
    j.get_or_generate(date(2026, 5, 12))
    # Prompt for May 12 should reference seeded "start timer" turns,
    # not the later-day turn.
    assert "later day" not in captured[0]
    assert "start timer" in captured[0]
