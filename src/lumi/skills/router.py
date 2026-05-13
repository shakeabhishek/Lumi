"""Skill router — dispatches utterances to the right handler.

Priority order:
  1. Native skills (keyword match, fast, local)
  2. OpenClaw bridge (networked skills — weather, Wikipedia, etc.)
  3. Direct LLM via ConversationManager (general conversation fallback)

Every dispatch is recorded in AuditLog when one is provided.
"""

from __future__ import annotations

from ..audio.tts import TTS
from ..log import get_logger
from ..runtime.conversation import ConversationManager
from .audit_log import AuditLog
from .base import NativeSkill
from .native.clipboard_skill import ClipboardSkill
from .native.mode_switch import ModeSwitchSkill
from .native.timer import TimerSkill
from .openclaw_bridge import OpenClawBridge

log = get_logger(__name__)


def _skill_name(skill: NativeSkill) -> str:
    return type(skill).__name__.removesuffix("Skill").lower().replace("switch", "_switch")


class SkillRouter:
    def __init__(
        self,
        conversation: ConversationManager,
        tts: TTS,
        bridge: OpenClawBridge | None = None,
        audit_log: AuditLog | None = None,
        clipboard_enabled: bool = False,
    ) -> None:
        self._native: list[NativeSkill] = [
            TimerSkill(tts=tts),
            ModeSwitchSkill(conversation=conversation),
            ClipboardSkill(enabled=clipboard_enabled),
        ]
        self._bridge = bridge
        self._conversation = conversation
        self._audit = audit_log

    def handle(self, transcript: str) -> str:
        # 1. Native skills
        for skill in self._native:
            if skill.matches(transcript):
                result = skill.execute(transcript)
                if result.handled:
                    name = _skill_name(skill)
                    log.info("router.native", skill=name)
                    if self._audit:
                        self._audit.log("native", name, transcript, result.text)
                    return result.text

        # 2. OpenClaw
        if self._bridge is not None:
            response = self._bridge.send(transcript)
            if response:
                log.info("router.openclaw")
                if self._audit:
                    self._audit.log("openclaw", "openclaw", transcript, response)
                return response
            log.info("router.openclaw_miss")

        # 3. Direct LLM
        log.info("router.llm")
        reply = self._conversation.chat(transcript)
        if self._audit:
            self._audit.log("llm", "llm", transcript, reply)
        return reply
