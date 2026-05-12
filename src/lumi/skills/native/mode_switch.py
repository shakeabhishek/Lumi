"""Native mode-switch skill — changes the conversation mode immediately."""

from __future__ import annotations

import re

from ...config import Mode
from ...log import get_logger
from ...runtime.conversation import ConversationManager
from ..base import NativeSkill, SkillResult

log = get_logger(__name__)

_MODE_NAMES: dict[str, Mode] = {
    "general": Mode.GENERAL,
    "code": Mode.CODE,
    "focus": Mode.FOCUS,
    "dictation": Mode.DICTATION,
}

_PATTERN = re.compile(
    r"\b(?:switch(?:\s+to)?|enter|go\s+to|use|enable)\s+("
    + "|".join(_MODE_NAMES)
    + r")\s*(?:mode)?\b",
    re.IGNORECASE,
)


class ModeSwitchSkill(NativeSkill):
    def __init__(self, conversation: ConversationManager) -> None:
        self._conversation = conversation

    def matches(self, transcript: str) -> bool:
        return bool(_PATTERN.search(transcript))

    def execute(self, transcript: str) -> SkillResult:
        match = _PATTERN.search(transcript)
        if not match:
            return SkillResult(text="Which mode would you like? General, code, focus, or dictation.")

        mode_name = match.group(1).lower()
        mode = _MODE_NAMES[mode_name]
        self._conversation.set_mode(mode)
        log.info("mode_switch.activated", mode=mode.value)
        return SkillResult(text=f"Switched to {mode_name} mode.")
