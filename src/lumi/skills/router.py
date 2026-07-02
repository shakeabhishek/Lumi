"""Skill router — dispatches utterances to the right handler.

Priority order:
  1. Native skills (keyword match, fast, local)
  2. OpenClaw bridge (networked skills — weather, Wikipedia, etc.)
  3. Direct LLM via ConversationManager (general conversation fallback)

Every dispatch is recorded in AuditLog when one is provided.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

from ..audio.tts import TTS
from ..llm.routed_backend import _EXPLICIT_CLOUD_PREFIX
from ..log import get_logger
from ..runtime.conversation import ConversationManager
from .audit_log import AuditLog
from .base import NativeSkill
from .native.clipboard_skill import ClipboardSkill
from .native.mode_switch import ModeSwitchSkill
from .native.notes_skill import NotesSkill
from .native.pomodoro_skill import PomodoroSkill
from .native.reminder_skill import ReminderSkill
from .native.system_stats_skill import SystemStatsSkill
from .native.timer import TimerSkill
from .native.todo_skill import TodoSkill
from .native.volume_skill import VolumeSkill
from .openclaw_bridge import OpenClawBridge

log = get_logger(__name__)

# Heuristic gate on whether to even TRY the OpenClaw bridge (step 2 below).
# Verified 2026-07-02: in "openclaw_cloud" runtime_mode, trying the bridge
# means shelling out to the `openclaw agent` CLI, which costs several real
# seconds even on a miss (its own --timeout flag isn't honored — see
# runtime/session.py). Trying it unconditionally for every message,
# including plain conversation, made ordinary chat feel broken. This
# approximates "does the message plausibly need one of the enabled
# OpenClaw skills" — keep it in sync with the enabled_skills set
# (weather, timer, unit_converter, wikipedia_lookup, file_search) rather
# than trying to be exhaustive; a false negative here just means an
# unusual phrasing falls through to the direct LLM instead of a skill,
# not a hard failure. wikipedia_lookup deliberately requires "wikipedia"/
# "look up" as an anchor, not bare "who is"/"what is" — those are answered
# directly and correctly by the LLM without needing the skill (see
# CLAUDE.md's wikipedia_lookup decision-log entry).
_LIKELY_SKILL_TRIGGERS = re.compile(
    r"\b("
    r"weather|forecast|temperature|raining|snowing|humid|degrees\s+(?:out|outside)|"
    r"timer|countdown|alarm|"
    r"convert|conversion|kilomet|\bmiles?\b|kilogram|pounds?|celsius|fahrenheit|"
    r"liters?|gallons?|centimet|\binch(?:es)?\b|\bfeet\b|\bmeters?\b|ounces?|grams?|"
    r"wikipedia|look\s+up|"
    r"find\s+(?:a\s+|the\s+)?file|search\s+(?:for\s+)?(?:a\s+|the\s+)?file|sandbox\s+director"
    r")\b",
    re.IGNORECASE,
)


def _worth_trying_openclaw(transcript: str) -> bool:
    """False for plain conversation and explicit cloud: escalation — both
    skip straight to the direct LLM instead of paying the bridge's latency
    for a call that's virtually certain to miss."""
    if _EXPLICIT_CLOUD_PREFIX.match(transcript):
        return False
    return bool(_LIKELY_SKILL_TRIGGERS.search(transcript))


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
        data_dir: Path | None = None,
        pseudonymizer: object | None = None,    # runtime.privacy.Pseudonymizer
        disabled_native_skills: list[str] | None = None,
    ) -> None:
        # Build the full native skill list first, then filter by the
        # user's deny-list. Done in this order (rather than skipping at
        # construction time) so disabling a skill that has expensive
        # construction — none today, but defence in depth — still does
        # the work to fail fast if anything in the constructor breaks.
        all_native: list[NativeSkill] = [
            ReminderSkill(tts=tts),   # before TimerSkill — more specific "remind me to X" pattern
            PomodoroSkill(tts=tts),   # before TimerSkill — "pomodoro" anchors avoid generic timer match
            TimerSkill(tts=tts),
            ModeSwitchSkill(conversation=conversation),
            VolumeSkill(),
            SystemStatsSkill(),
            ClipboardSkill(enabled=clipboard_enabled),
        ]
        if data_dir is not None:
            # TodoSkill before NotesSkill — both match "remember X" / "I
            # need to X" phrasings; todos are mutable tasks while notes
            # are immutable observations. Putting todos first lets
            # "I need to call mom" become a todo rather than a note,
            # which is the more useful default.
            all_native.append(TodoSkill(data_dir=data_dir))
            all_native.append(NotesSkill(data_dir=data_dir))
        disabled = set(disabled_native_skills or [])
        self._native: list[NativeSkill] = [
            s for s in all_native if _skill_name(s) not in disabled
        ]
        self._bridge = bridge
        self._conversation = conversation
        self._audit = audit_log
        # If a pseudonymizer is supplied (cloud mode), audit log entries
        # store the MASKED transcript so even our on-disk logs don't keep
        # raw PII. In pure-local V1 hybrid (no pseudonymizer), audit log
        # keeps raw transcripts — they never leave the device anyway.
        self._pseudo = pseudonymizer

    def _audit_text(self, text: str) -> str:
        if self._pseudo is None or not text:
            return text
        try:
            return self._pseudo.mask(text)  # type: ignore[attr-defined]
        except Exception:
            return text

    def handle(self, transcript: str) -> str:
        # 1. Native skills
        for skill in self._native:
            if skill.matches(transcript):
                result = skill.execute(transcript)
                if result.handled:
                    name = _skill_name(skill)
                    log.info("router.native", skill=name)
                    if self._audit:
                        self._audit.log("native", name, self._audit_text(transcript), self._audit_text(result.text))
                    return result.text

        # 2. OpenClaw
        # In "ollama" mode this is a cheap direct HTTP call to the already-
        # running local Ollama server — always worth trying. In
        # "openclaw_cloud" mode it's a slow CLI subprocess (see
        # _worth_trying_openclaw's docstring) — gate it so plain
        # conversation doesn't pay that tax on every single turn.
        if self._bridge is not None and (
            self._bridge.runtime_mode != "openclaw_cloud" or _worth_trying_openclaw(transcript)
        ):
            response = self._bridge.send(transcript)
            if response:
                log.info("router.openclaw")
                if self._audit:
                    src = "openclaw" if self._bridge.runtime_mode == "openclaw_cloud" else "tool"
                    self._audit.log(src, src, self._audit_text(transcript), self._audit_text(response))
                return response
            log.info("router.openclaw_miss")

        # 3. Direct LLM
        log.info("router.llm")
        reply = self._conversation.chat(transcript)
        if self._audit:
            self._audit.log("llm", "llm", self._audit_text(transcript), self._audit_text(reply))
        return reply

    def handle_streaming(self, transcript: str) -> Iterator[str]:
        """Like handle() but streams the LLM response token-by-token on the LLM path."""
        # 1. Native skills — return full text as a single chunk
        for skill in self._native:
            if skill.matches(transcript):
                result = skill.execute(transcript)
                if result.handled:
                    name = _skill_name(skill)
                    log.info("router.native", skill=name)
                    if self._audit:
                        self._audit.log("native", name, self._audit_text(transcript), self._audit_text(result.text))
                    yield result.text
                    return

        # 2. OpenClaw — synchronous, yield whole response. See handle()'s
        # comment: only gated in "openclaw_cloud" mode, where the bridge
        # is a slow CLI subprocess rather than a cheap direct HTTP call.
        if self._bridge is not None and (
            self._bridge.runtime_mode != "openclaw_cloud" or _worth_trying_openclaw(transcript)
        ):
            response = self._bridge.send(transcript)
            if response:
                log.info("router.openclaw")
                if self._audit:
                    src = "openclaw" if self._bridge.runtime_mode == "openclaw_cloud" else "tool"
                    self._audit.log(src, src, self._audit_text(transcript), self._audit_text(response))
                yield response
                return
            log.info("router.openclaw_miss")

        # 3. Streaming LLM
        log.info("router.llm_stream")
        parts: list[str] = []
        for chunk in self._conversation.stream_chat(transcript):
            parts.append(chunk)
            yield chunk
        if self._audit:
            # If a RoutedBackend served this turn it exposes `.last_route`
            # so the audit log can tell local-vs-cloud:provider apart at
            # a glance. Otherwise default to plain "llm".
            backend = getattr(self._conversation, "_backend", None)
            route = getattr(backend, "last_route", "")
            src = f"cloud:{route.split(':', 1)[1]}" if route.startswith("cloud:") else "llm"
            skill = "llm"
            self._audit.log(src, skill, self._audit_text(transcript), self._audit_text("".join(parts)))
