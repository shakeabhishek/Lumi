"""Native timer skill — local, no network required."""

from __future__ import annotations

import re
import threading

from ...audio.tts import TTS
from ...log import get_logger
from ..base import NativeSkill, SkillResult

log = get_logger(__name__)

_TRIGGER = re.compile(r"\b(timer|remind me|countdown)\b", re.IGNORECASE)
_DURATION = re.compile(
    r"(\d+(?:\.\d+)?)\s*(hour|hr|minute|min|second|sec)s?",
    re.IGNORECASE,
)
_MULTIPLIERS = {
    "hour": 3600, "hr": 3600,
    "minute": 60, "min": 60,
    "second": 1, "sec": 1,
}


def _parse_seconds(text: str) -> int | None:
    match = _DURATION.search(text)
    if not match:
        return None
    value = float(match.group(1))
    unit = match.group(2).lower()
    return round(value * _MULTIPLIERS[unit])


def _humanize(seconds: int) -> str:
    if seconds >= 3600 and seconds % 3600 == 0:
        n = seconds // 3600
        return f"{n} hour{'s' if n > 1 else ''}"
    if seconds >= 60 and seconds % 60 == 0:
        n = seconds // 60
        return f"{n} minute{'s' if n > 1 else ''}"
    return f"{seconds} second{'s' if seconds != 1 else ''}"


class TimerSkill(NativeSkill):
    def __init__(self, tts: TTS) -> None:
        self._tts = tts

    def matches(self, transcript: str) -> bool:
        return bool(_TRIGGER.search(transcript))

    def execute(self, transcript: str) -> SkillResult:
        seconds = _parse_seconds(transcript)
        if seconds is None or seconds <= 0:
            return SkillResult(text="How long should the timer be?")

        label = _humanize(seconds)
        # daemon=True so a 5-minute reminder doesn't block Python
        # interpreter shutdown — particularly important under pytest,
        # where a `set a timer for 5 minutes` test fixture would
        # otherwise stall the entire suite for the timer's duration
        # waiting on the join.
        t = threading.Timer(seconds, self._alert, args=[label])
        t.daemon = True
        t.start()
        log.info("timer.set", seconds=seconds, label=label)
        return SkillResult(text=f"Timer set for {label}.")

    def _alert(self, label: str) -> None:
        log.info("timer.fired", label=label)
        self._tts.speak(f"{label} timer done!")
