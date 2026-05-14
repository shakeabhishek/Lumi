"""Tests for PomodoroSkill, NotesSkill, and the HailoBackend stub."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from lumi.llm.hailo_backend import HailoBackend
from lumi.skills.native.notes_skill import NotesSkill
from lumi.skills.native.pomodoro_skill import PomodoroSkill


# ───────────────────────────────────────────────────────────────────────────
# PomodoroSkill
# ───────────────────────────────────────────────────────────────────────────


def _pomodoro() -> PomodoroSkill:
    return PomodoroSkill(tts=MagicMock())


def test_pomodoro_matches_triggers() -> None:
    s = _pomodoro()
    assert s.matches("start a pomodoro")
    assert s.matches("begin a pomodoro for 50 minutes")
    assert s.matches("stop pomodoro")
    assert s.matches("cancel pomodoro")
    assert s.matches("pomodoro status")
    assert s.matches("how much time is left on the pomodoro")


def test_pomodoro_no_match_unrelated() -> None:
    s = _pomodoro()
    assert not s.matches("set a timer for 5 minutes")
    assert not s.matches("what time is it")


def test_pomodoro_start_default() -> None:
    s = _pomodoro()
    result = s.execute("start a pomodoro")
    assert result.handled
    assert "25" in result.text
    assert s._session is not None
    assert s._session.phase == "work"
    s._session.timer.cancel()


def test_pomodoro_start_custom_length() -> None:
    s = _pomodoro()
    result = s.execute("start a pomodoro for 50 minutes")
    assert "50" in result.text
    assert s._session.work_len == 50
    s._session.timer.cancel()


def test_pomodoro_status_when_running() -> None:
    s = _pomodoro()
    s.execute("start a pomodoro")
    result = s.execute("pomodoro status")
    assert "work" in result.text.lower()
    assert "minute" in result.text.lower()
    s._session.timer.cancel()


def test_pomodoro_status_when_idle() -> None:
    s = _pomodoro()
    result = s.execute("pomodoro status")
    assert "no pomodoro" in result.text.lower()


def test_pomodoro_cancel() -> None:
    s = _pomodoro()
    s.execute("start a pomodoro")
    result = s.execute("cancel pomodoro")
    assert s._session is None
    assert "cancelled" in result.text.lower()


def test_pomodoro_starting_new_cancels_old() -> None:
    s = _pomodoro()
    s.execute("start a pomodoro for 30 minutes")
    first_timer = s._session.timer
    s.execute("start a pomodoro for 15 minutes")
    assert not first_timer.is_alive() or first_timer.finished.is_set()
    assert s._session.work_len == 15
    s._session.timer.cancel()


# ───────────────────────────────────────────────────────────────────────────
# NotesSkill
# ───────────────────────────────────────────────────────────────────────────


def test_notes_matches_triggers(tmp_path: Path) -> None:
    s = NotesSkill(data_dir=tmp_path)
    assert s.matches("remember that I left my keys on the table")
    assert s.matches("make a note that the wifi password is hunter2")
    assert s.matches("note: pick up milk")
    assert s.matches("what did I note about milk")
    assert s.matches("find notes about keys")
    assert s.matches("show my notes")
    assert s.matches("clear all notes")


def test_notes_no_match_unrelated(tmp_path: Path) -> None:
    s = NotesSkill(data_dir=tmp_path)
    assert not s.matches("set a timer for 5 minutes")
    assert not s.matches("what time is it")


def test_notes_save_and_find(tmp_path: Path) -> None:
    s = NotesSkill(data_dir=tmp_path)
    r = s.execute("remember that the wifi password is hunter2")
    assert "wifi password is hunter2" in r.text

    r = s.execute("what did I note about wifi")
    assert "hunter2" in r.text


def test_notes_persist_across_instances(tmp_path: Path) -> None:
    s1 = NotesSkill(data_dir=tmp_path)
    s1.execute("remember that my flight is at 7am")

    s2 = NotesSkill(data_dir=tmp_path)
    r = s2.execute("what did I note about flight")
    assert "7am" in r.text


def test_notes_list_when_empty(tmp_path: Path) -> None:
    s = NotesSkill(data_dir=tmp_path)
    r = s.execute("show my notes")
    assert "no notes" in r.text.lower()


def test_notes_list_multiple(tmp_path: Path) -> None:
    s = NotesSkill(data_dir=tmp_path)
    s.execute("remember that I like oat milk")
    s.execute("remember that I am vegetarian")
    r = s.execute("show my notes")
    assert "oat milk" in r.text
    assert "vegetarian" in r.text


def test_notes_find_no_match(tmp_path: Path) -> None:
    s = NotesSkill(data_dir=tmp_path)
    s.execute("remember that I like oat milk")
    r = s.execute("what did I note about quantum physics")
    assert "no notes" in r.text.lower() or "matching" in r.text.lower()


def test_notes_clear_removes_file(tmp_path: Path) -> None:
    s = NotesSkill(data_dir=tmp_path)
    s.execute("remember thing one")
    s.execute("remember thing two")
    r = s.execute("clear all notes")
    assert "2" in r.text
    r = s.execute("show my notes")
    assert "no notes" in r.text.lower()


def test_notes_handles_corrupt_line(tmp_path: Path) -> None:
    (tmp_path / "notes.jsonl").write_text('{"ts":"x","text":"good"}\nnot json\n')
    s = NotesSkill(data_dir=tmp_path)
    r = s.execute("show my notes")
    assert "good" in r.text


# ───────────────────────────────────────────────────────────────────────────
# HailoBackend stub
# ───────────────────────────────────────────────────────────────────────────


def test_hailo_model_property(tmp_path: Path) -> None:
    b = HailoBackend(model_path=tmp_path / "fake.hef", model_name="qwen2.5-1.5b")
    assert b.model == "hailo:qwen2.5-1.5b"


def test_hailo_chat_raises_not_implemented_on_laptop(tmp_path: Path) -> None:
    b = HailoBackend(model_path=tmp_path / "fake.hef")
    with pytest.raises((NotImplementedError, RuntimeError)):
        # _get_runtime fails first (no hailo_platform on laptop), so RuntimeError;
        # if someone mocks past that, the stub raises NotImplementedError.
        next(iter(b.chat([{"role": "user", "content": "hi"}])))
