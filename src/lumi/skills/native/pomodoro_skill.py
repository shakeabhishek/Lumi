"""Pomodoro timer — auto-cycling 25/5 work/break sessions.

Native, no network. One active session at a time. The session announces phase
transitions via TTS so the user can stay focused without watching a clock.

Triggers:
  "start pomodoro" / "begin a pomodoro"          → start a 25/5 cycle
  "start pomodoro for 50 minutes"                → custom work length
  "pause pomodoro" / "stop pomodoro"             → cancel current
  "pomodoro status" / "how much time"            → current phase + remaining
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from time import monotonic

from ...audio.tts import TTS
from ...log import get_logger
from ..base import NativeSkill, SkillResult

log = get_logger(__name__)

_START = re.compile(
    r"\b(start|begin)\b.*\bpomodoro(?:\s+for\s+(\d+)\s*(?:minute|min)s?)?",
    re.IGNORECASE,
)
_STOP = re.compile(r"\b(stop|cancel|end|pause)\b.*\bpomodoro\b", re.IGNORECASE)
_STATUS = re.compile(
    r"\bpomodoro\b.*\b(status|state|how (?:much|long))\b"
    r"|\b(how (?:much|long))\b.*\bpomodoro\b",
    re.IGNORECASE,
)

_DEFAULT_WORK_MIN = 25
_BREAK_MIN = 5


@dataclass
class _Session:
    phase: str           # "work" or "break"
    ends_at: float       # monotonic seconds
    work_len: int        # minutes
    timer: threading.Timer


class PomodoroSkill(NativeSkill):
    def __init__(self, tts: TTS) -> None:
        self._tts = tts
        self._session: _Session | None = None

    def matches(self, transcript: str) -> bool:
        return bool(
            _START.search(transcript)
            or _STOP.search(transcript)
            or _STATUS.search(transcript)
        )

    def execute(self, transcript: str) -> SkillResult:
        if _STOP.search(transcript):
            return self._cancel()
        if _STATUS.search(transcript):
            return self._status()
        m = _START.search(transcript)
        if m:
            mins = int(m.group(2)) if m.group(2) else _DEFAULT_WORK_MIN
            return self._start(mins)
        return SkillResult(text="I didn't catch that pomodoro command.")

    def _start(self, work_minutes: int) -> SkillResult:
        if self._session is not None:
            self._session.timer.cancel()
        seconds = work_minutes * 60
        self._schedule("work", seconds, work_minutes)
        log.info("pomodoro.start", minutes=work_minutes)
        return SkillResult(text=f"Pomodoro started. {work_minutes} minutes of focus.")

    def _schedule(self, phase: str, seconds: int, work_len: int) -> None:
        ends_at = monotonic() + seconds
        timer = threading.Timer(seconds, self._on_phase_end)
        timer.daemon = True
        timer.start()
        self._session = _Session(phase=phase, ends_at=ends_at, work_len=work_len, timer=timer)

    def _on_phase_end(self) -> None:
        if self._session is None:
            return
        s = self._session
        if s.phase == "work":
            self._tts.speak("Time for a break. Five minutes.")
            log.info("pomodoro.work_done")
            self._schedule("break", _BREAK_MIN * 60, s.work_len)
        else:
            self._tts.speak(f"Break over. {s.work_len} more minutes when you're ready.")
            log.info("pomodoro.break_done")
            self._session = None

    def _cancel(self) -> SkillResult:
        if self._session is None:
            return SkillResult(text="No pomodoro running.")
        self._session.timer.cancel()
        self._session = None
        log.info("pomodoro.cancelled")
        return SkillResult(text="Pomodoro cancelled.")

    def _status(self) -> SkillResult:
        if self._session is None:
            return SkillResult(text="No pomodoro running.")
        remaining = max(0, round(self._session.ends_at - monotonic()))
        m, s = divmod(remaining, 60)
        return SkillResult(
            text=f"On {self._session.phase} — {m} minute{'s' if m != 1 else ''} {s} seconds left."
        )
