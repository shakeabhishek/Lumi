"""Tests for AuditLog — write, read, and failure handling."""

from __future__ import annotations

import json
from pathlib import Path


from lumi.skills.audit_log import AuditLog


class TestLog:
    def test_creates_file_on_first_write(self, tmp_path: Path) -> None:
        al = AuditLog(tmp_path)
        al.log("native", "timer", "set a timer for 5 minutes", "Timer set for 5 minutes.")
        assert (tmp_path / "audit_log.jsonl").exists()

    def test_entry_has_required_fields(self, tmp_path: Path) -> None:
        al = AuditLog(tmp_path)
        al.log("openclaw", "weather", "what's the weather", "It's sunny.")
        line = (tmp_path / "audit_log.jsonl").read_text().strip()
        entry = json.loads(line)
        assert entry["source"] == "openclaw"
        assert entry["skill"] == "weather"
        assert entry["input"] == "what's the weather"
        assert entry["result"] == "It's sunny."
        assert "ts" in entry

    def test_multiple_entries_appended(self, tmp_path: Path) -> None:
        al = AuditLog(tmp_path)
        al.log("native", "timer", "5 min timer", "Timer set.")
        al.log("llm", "llm", "tell me a joke", "Why did the chicken...")
        lines = (tmp_path / "audit_log.jsonl").read_text().splitlines()
        assert len(lines) == 2

    def test_creates_data_dir_if_missing(self, tmp_path: Path) -> None:
        nested = tmp_path / "deep" / "nested"
        al = AuditLog(nested)
        al.log("native", "timer", "input", "result")
        assert (nested / "audit_log.jsonl").exists()


class TestGetRecent:
    def test_returns_empty_when_no_file(self, tmp_path: Path) -> None:
        al = AuditLog(tmp_path)
        assert al.get_recent() == []

    def test_returns_all_entries_when_fewer_than_n(self, tmp_path: Path) -> None:
        al = AuditLog(tmp_path)
        al.log("native", "timer", "input 1", "result 1")
        al.log("openclaw", "weather", "input 2", "result 2")
        entries = al.get_recent(n=10)
        assert len(entries) == 2

    def test_caps_at_n_most_recent(self, tmp_path: Path) -> None:
        al = AuditLog(tmp_path)
        for i in range(10):
            al.log("llm", "llm", f"input {i}", f"result {i}")
        entries = al.get_recent(n=3)
        assert len(entries) == 3
        assert entries[-1]["input"] == "input 9"

    def test_entries_have_correct_structure(self, tmp_path: Path) -> None:
        al = AuditLog(tmp_path)
        al.log("native", "mode_switch", "switch to code mode", "Switched to code mode.")
        entry = al.get_recent()[0]
        assert entry["source"] == "native"
        assert entry["skill"] == "mode_switch"
        assert entry["input"] == "switch to code mode"
        assert entry["result"] == "Switched to code mode."

    def test_one_corrupt_line_does_not_poison_the_whole_read(self, tmp_path: Path) -> None:
        """A truncated write or manually-edited line must not blank the viewer.
        Skip the bad line, return the rest."""
        al = AuditLog(tmp_path)
        al.log("native", "timer", "input 1", "result 1")
        al.log("native", "timer", "input 2", "result 2")
        # Wedge a corrupt line into the middle.
        path = tmp_path / "audit_log.jsonl"
        existing = path.read_text().splitlines()
        path.write_text(existing[0] + "\n{not valid json\n" + existing[1] + "\n")

        entries = al.get_recent()
        assert len(entries) == 2
        assert entries[0]["input"] == "input 1"
        assert entries[1]["input"] == "input 2"

    def test_trailing_corrupt_line_alone_still_yields_prior_entries(
        self, tmp_path: Path,
    ) -> None:
        """A crash mid-append leaves a partial last line. Old behaviour blanked
        the viewer; new behaviour returns the entries that committed cleanly."""
        al = AuditLog(tmp_path)
        for i in range(5):
            al.log("native", "timer", f"in {i}", f"out {i}")
        path = tmp_path / "audit_log.jsonl"
        # Append a truncated JSON object (simulating crash mid-write)
        with path.open("a") as f:
            f.write('{"ts":"2026-05-21T...","sourc')

        entries = al.get_recent()
        assert len(entries) == 5
        assert entries[-1]["input"] == "in 4"

    def test_n_cap_still_applies_when_skipping_corrupt_lines(self, tmp_path: Path) -> None:
        """The over-read shouldn't let a get_recent(n=3) return 5."""
        al = AuditLog(tmp_path)
        for i in range(10):
            al.log("native", "timer", f"in {i}", f"out {i}")
        # Sprinkle some bad lines in.
        path = tmp_path / "audit_log.jsonl"
        lines = path.read_text().splitlines()
        lines.insert(2, "{garbage")
        lines.insert(7, "also garbage")
        path.write_text("\n".join(lines) + "\n")

        entries = al.get_recent(n=3)
        assert len(entries) == 3


class TestRouterIntegration:
    """Verify the router logs invocations via the audit log."""

    def test_native_skill_logged(self, tmp_path: Path) -> None:
        from unittest.mock import MagicMock

        from lumi.skills.audit_log import AuditLog
        from lumi.skills.router import SkillRouter

        al = AuditLog(tmp_path)
        tts = MagicMock()
        conversation = MagicMock()
        router = SkillRouter(conversation=conversation, tts=tts, audit_log=al)

        router.handle("set a timer for 5 minutes")

        entries = al.get_recent()
        assert len(entries) == 1
        assert entries[0]["source"] == "native"
        assert entries[0]["skill"] == "timer"

    def test_llm_fallback_logged(self, tmp_path: Path) -> None:
        from unittest.mock import MagicMock

        from lumi.skills.audit_log import AuditLog
        from lumi.skills.router import SkillRouter

        al = AuditLog(tmp_path)
        tts = MagicMock()
        conversation = MagicMock()
        conversation.chat.return_value = "Here is a joke."
        router = SkillRouter(conversation=conversation, tts=tts, bridge=None, audit_log=al)

        router.handle("tell me a joke")

        entries = al.get_recent()
        assert len(entries) == 1
        assert entries[0]["source"] == "llm"
        assert entries[0]["result"] == "Here is a joke."

    def test_no_audit_log_is_fine(self) -> None:
        from unittest.mock import MagicMock

        from lumi.skills.router import SkillRouter

        tts = MagicMock()
        conversation = MagicMock()
        conversation.chat.return_value = "ok"
        router = SkillRouter(conversation=conversation, tts=tts)
        router.handle("anything")  # should not raise
