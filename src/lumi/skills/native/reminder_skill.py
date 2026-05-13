"""Native reminder skill — 'remind me to X in Y minutes'.

Reminders are in-memory only (lost on restart). Each fires via threading.Timer
and speaks aloud via TTS. Stored as a plain list so the user can ask 'what are
my reminders' too.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from time import time

from ...audio.tts import TTS
from ...log import get_logger
from ..base import NativeSkill, SkillResult

log = get_logger(__name__)

_SET = re.compile(
    r"remind(?:er)?\s+me\s+to\s+(.+?)\s+in\s+(\d+(?:\.\d+)?)\s*(hour|hr|minute|min|second|sec)s?",
    re.IGNORECASE,
)
_LIST = re.compile(r"\b(what(?:'s| are)(?: my)? reminders?|list reminders?)\b", re.IGNORECASE)
_CANCEL = re.compile(r"\b(cancel|clear|delete)\b.+\breminders?\b", re.IGNORECASE)

_MULTIPLIERS = {"hour": 3600, "hr": 3600, "minute": 60, "min": 60, "second": 1, "sec": 1}


@dataclass
class _Reminder:
    task: str
    fires_at: float
    timer: threading.Timer = field(repr=False)


class ReminderSkill(NativeSkill):
    def __init__(self, tts: TTS) -> None:
        self._tts = tts
        self._reminders: list[_Reminder] = []

    def matches(self, transcript: str) -> bool:
        return bool(
            _SET.search(transcript)
            or _LIST.search(transcript)
            or _CANCEL.search(transcript)
        )

    def execute(self, transcript: str) -> SkillResult:
        if _LIST.search(transcript):
            return self._list_reminders()
        if _CANCEL.search(transcript):
            return self._cancel_all()
        return self._set_reminder(transcript)

    def _set_reminder(self, transcript: str) -> SkillResult:
        m = _SET.search(transcript)
        if not m:
            return SkillResult(text="I didn't catch the task or time. Try: 'remind me to call John in 10 minutes'.")
        task = m.group(1).strip()
        amount = float(m.group(2))
        unit = m.group(3).lower()
        seconds = round(amount * _MULTIPLIERS[unit])
        fires_at = time() + seconds

        timer = threading.Timer(seconds, self._fire, args=[task])
        timer.daemon = True
        timer.start()
        self._reminders.append(_Reminder(task=task, fires_at=fires_at, timer=timer))

        unit_label = unit.replace("min", "minute").replace("hr", "hour").replace("sec", "second")
        if not unit_label.endswith("s") and amount != 1:
            unit_label += "s"
        log.info("reminder.set", task=task, seconds=seconds)
        return SkillResult(text=f"I'll remind you to {task} in {amount:.0f} {unit_label}.")

    def _fire(self, task: str) -> None:
        log.info("reminder.fired", task=task)
        self._reminders = [r for r in self._reminders if r.task != task]
        self._tts.speak(f"Reminder: {task}.")

    def _list_reminders(self) -> SkillResult:
        active = [r for r in self._reminders if r.timer.is_alive()]
        if not active:
            return SkillResult(text="You have no active reminders.")
        lines = [f"{r.task} (in {max(0, round(r.fires_at - time()))}s)" for r in active]
        return SkillResult(text="Your reminders: " + "; ".join(lines) + ".")

    def _cancel_all(self) -> SkillResult:
        for r in self._reminders:
            r.timer.cancel()
        count = len(self._reminders)
        self._reminders.clear()
        return SkillResult(text=f"Cancelled {count} reminder{'s' if count != 1 else ''}.")
