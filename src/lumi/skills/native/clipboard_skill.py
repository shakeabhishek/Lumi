"""Native clipboard skill — reads the host clipboard on request."""

from __future__ import annotations

from ..base import NativeSkill, SkillResult

_TRIGGERS = (
    "clipboard", "what did i copy", "what's copied", "what i copied",
    "read my clipboard", "show my clipboard",
)


class ClipboardSkill(NativeSkill):
    def __init__(self, enabled: bool = False) -> None:
        self._enabled = enabled

    def matches(self, transcript: str) -> bool:
        t = transcript.lower()
        return any(phrase in t for phrase in _TRIGGERS)

    def execute(self, transcript: str) -> SkillResult:
        if not self._enabled:
            return SkillResult(
                text="Clipboard access is disabled. Enable it in Settings → Data permissions."
            )
        from ...host_helper import clipboard  # noqa: PLC0415

        content = clipboard.read()
        if content is None:
            return SkillResult(text="I couldn't read the clipboard right now.")
        stripped = content.strip()
        if not stripped:
            return SkillResult(text="Your clipboard is empty.")
        preview = stripped[:400]
        suffix = "…" if len(stripped) > 400 else ""
        return SkillResult(text=f"Your clipboard contains: {preview}{suffix}")
