"""Tests for TimerSkill — matching and duration parsing."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from lumi.skills.native.timer import TimerSkill, _humanize, _parse_seconds


class TestDurationParsing:
    def test_minutes(self) -> None:
        assert _parse_seconds("set a timer for 5 minutes") == 300

    def test_seconds(self) -> None:
        assert _parse_seconds("remind me in 30 seconds") == 30

    def test_hours(self) -> None:
        assert _parse_seconds("countdown 1 hour") == 3600

    def test_abbreviations(self) -> None:
        assert _parse_seconds("2 min") == 120
        assert _parse_seconds("45 sec") == 45
        assert _parse_seconds("2 hr") == 7200

    def test_no_duration_returns_none(self) -> None:
        assert _parse_seconds("set a timer") is None
        assert _parse_seconds("what time is it") is None

    def test_plural_handled(self) -> None:
        assert _parse_seconds("3 minutes") == 180
        assert _parse_seconds("10 seconds") == 10


class TestHumanize:
    def test_exact_hours(self) -> None:
        assert _humanize(3600) == "1 hour"
        assert _humanize(7200) == "2 hours"

    def test_exact_minutes(self) -> None:
        assert _humanize(60) == "1 minute"
        assert _humanize(300) == "5 minutes"

    def test_seconds(self) -> None:
        assert _humanize(1) == "1 second"
        assert _humanize(45) == "45 seconds"

    def test_mixed_shows_seconds(self) -> None:
        assert _humanize(90) == "90 seconds"


class TestTimerSkillMatching:
    def setup_method(self) -> None:
        self.skill = TimerSkill(tts=MagicMock())

    def test_matches_timer_keyword(self) -> None:
        assert self.skill.matches("set a timer for 5 minutes")
        assert self.skill.matches("Timer for 10 minutes please")

    def test_matches_remind_me(self) -> None:
        assert self.skill.matches("remind me in 30 seconds")
        assert self.skill.matches("Remind me in 2 minutes")

    def test_matches_countdown(self) -> None:
        assert self.skill.matches("countdown 1 hour")

    def test_does_not_match_time_question(self) -> None:
        assert not self.skill.matches("what time is it?")
        assert not self.skill.matches("how long does it take to boil water?")
        assert not self.skill.matches("tell me a joke")


class TestTimerSkillExecute:
    def setup_method(self) -> None:
        self.tts = MagicMock()
        self.skill = TimerSkill(tts=self.tts)

    def test_returns_confirmation(self) -> None:
        result = self.skill.execute("set a timer for 5 minutes")
        assert result.handled is True
        assert "5 minutes" in result.text.lower() or "timer" in result.text.lower()

    def test_asks_for_duration_when_unparseable(self) -> None:
        result = self.skill.execute("set a timer")
        assert result.handled is True
        assert "?" in result.text
