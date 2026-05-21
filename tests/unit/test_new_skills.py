"""Tests for VolumeSkill, ReminderSkill, and SystemStatsSkill."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


from lumi.skills.native.reminder_skill import ReminderSkill
from lumi.skills.native.system_stats_skill import SystemStatsSkill
from lumi.skills.native.volume_skill import VolumeSkill


# ---------------------------------------------------------------------------
# VolumeSkill
# ---------------------------------------------------------------------------


def test_volume_matches_triggers() -> None:
    s = VolumeSkill()
    assert s.matches("volume up")
    assert s.matches("make it louder")
    assert s.matches("quieter please")
    assert s.matches("mute")
    assert s.matches("set volume to 50")


def test_volume_no_match_unrelated() -> None:
    s = VolumeSkill()
    assert not s.matches("what time is it")
    assert not s.matches("set a timer for 5 minutes")


def test_volume_up_macos(monkeypatch) -> None:
    monkeypatch.setattr("sys.platform", "darwin")
    with (
        patch("lumi.skills.native.volume_skill._get_volume_macos", return_value=40),
        patch("lumi.skills.native.volume_skill._set_volume_macos", return_value=True) as mock_set,
    ):
        result = VolumeSkill().execute("volume up")
    mock_set.assert_called_once_with(60)
    assert "60" in result.text


def test_volume_down_macos(monkeypatch) -> None:
    monkeypatch.setattr("sys.platform", "darwin")
    with (
        patch("lumi.skills.native.volume_skill._get_volume_macos", return_value=60),
        patch("lumi.skills.native.volume_skill._set_volume_macos", return_value=True),
    ):
        result = VolumeSkill().execute("quieter")
    assert "40" in result.text


def test_volume_set_explicit(monkeypatch) -> None:
    monkeypatch.setattr("sys.platform", "darwin")
    with patch("lumi.skills.native.volume_skill._set_volume_macos", return_value=True):
        result = VolumeSkill().execute("set volume to 75")
    assert "75" in result.text


def test_volume_mute_macos(monkeypatch) -> None:
    monkeypatch.setattr("sys.platform", "darwin")
    with patch("lumi.skills.native.volume_skill._set_mute_macos", return_value=True):
        result = VolumeSkill().execute("mute")
    assert "muted" in result.text.lower()


def test_volume_clamps_to_100(monkeypatch) -> None:
    monkeypatch.setattr("sys.platform", "darwin")
    with (
        patch("lumi.skills.native.volume_skill._get_volume_macos", return_value=95),
        patch("lumi.skills.native.volume_skill._set_volume_macos", return_value=True) as mock_set,
    ):
        VolumeSkill().execute("louder")
    mock_set.assert_called_once_with(100)


# ---------------------------------------------------------------------------
# ReminderSkill
# ---------------------------------------------------------------------------


def test_reminder_matches_set_pattern() -> None:
    tts = MagicMock()
    s = ReminderSkill(tts)
    assert s.matches("remind me to call John in 10 minutes")
    assert s.matches("remind me to take medication in 2 hours")
    assert s.matches("reminder me to stretch in 30 seconds")


def test_reminder_matches_list() -> None:
    tts = MagicMock()
    s = ReminderSkill(tts)
    assert s.matches("what are my reminders")
    assert s.matches("list reminders")


def test_reminder_matches_cancel() -> None:
    tts = MagicMock()
    s = ReminderSkill(tts)
    assert s.matches("cancel all reminders")
    assert s.matches("clear reminders")


def test_reminder_no_match_unrelated() -> None:
    tts = MagicMock()
    s = ReminderSkill(tts)
    assert not s.matches("set a timer for 5 minutes")  # timer skill handles this
    assert not s.matches("what time is it")


def test_reminder_set_creates_timer() -> None:
    tts = MagicMock()
    s = ReminderSkill(tts)
    result = s.execute("remind me to call John in 1 hour")
    assert result.handled
    assert "John" in result.text
    assert len(s._reminders) == 1
    s._reminders[0].timer.cancel()


def test_reminder_fires_tts(monkeypatch) -> None:
    tts = MagicMock()
    s = ReminderSkill(tts)
    s._fire("test task")
    tts.speak.assert_called_once()
    assert "test task" in tts.speak.call_args[0][0]


def test_reminder_list_empty() -> None:
    tts = MagicMock()
    s = ReminderSkill(tts)
    result = s.execute("what are my reminders")
    assert "no active" in result.text.lower()


def test_reminder_cancel_clears_all() -> None:
    tts = MagicMock()
    s = ReminderSkill(tts)
    s.execute("remind me to stretch in 100 minutes")
    s.execute("remind me to drink water in 200 minutes")
    result = s.execute("cancel all reminders")
    assert len(s._reminders) == 0
    assert "2" in result.text


def test_reminder_invalid_missing_task() -> None:
    tts = MagicMock()
    s = ReminderSkill(tts)
    result = s.execute("remind me in 5 minutes")  # no "to X" component
    assert "didn't catch" in result.text.lower() or result.handled


# ---------------------------------------------------------------------------
# SystemStatsSkill
# ---------------------------------------------------------------------------


def test_system_stats_matches_triggers() -> None:
    s = SystemStatsSkill()
    assert s.matches("system stats")
    assert s.matches("how's my machine")
    assert s.matches("cpu usage")
    assert s.matches("memory usage")
    assert s.matches("disk space")


def test_system_stats_no_match_unrelated() -> None:
    s = SystemStatsSkill()
    assert not s.matches("set a timer")
    assert not s.matches("volume up")


def test_system_stats_with_psutil() -> None:
    mock_psutil = MagicMock()
    mock_psutil.cpu_percent.return_value = 42.5
    mock_psutil.virtual_memory.return_value = MagicMock(
        percent=65.0, used=4 * 1024**3, total=8 * 1024**3
    )
    mock_psutil.disk_usage.return_value = MagicMock(
        percent=55.0, used=100 * 1024**3, total=250 * 1024**3
    )
    with patch.dict("sys.modules", {"psutil": mock_psutil}):
        result = SystemStatsSkill().execute("system stats")
    assert "42" in result.text
    assert result.handled


def test_system_stats_psutil_missing_graceful() -> None:
    with patch.dict("sys.modules", {"psutil": None}):  # type: ignore[dict-item]
        # Should not raise — falls back to subprocess or returns a message
        result = SystemStatsSkill().execute("system stats")
    assert result.handled
