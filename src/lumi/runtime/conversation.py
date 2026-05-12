"""Conversation state — message history + LLM dispatch.

`ConversationManager` is the single point of contact between the runtime
and the LLM. It owns the history, injects the system prompt, and enforces
the sliding-window context limit. ChromaDB-backed memory retrieval plugs in
here in Week 2 (inject relevant past context into the system prompt string).
"""

from __future__ import annotations

from collections.abc import Iterator

from ..config import Mode
from ..llm.ollama_backend import LLMBackend, Message
from ..llm.prompts import get_system_prompt
from ..log import get_logger

log = get_logger(__name__)


class ConversationManager:
    def __init__(
        self,
        backend: LLMBackend,
        mode: Mode = Mode.GENERAL,
        max_turns: int = 20,
    ) -> None:
        self._backend = backend
        self._mode = mode
        self._max_turns = max_turns
        self._history: list[Message] = []

    @property
    def mode(self) -> Mode:
        return self._mode

    def set_mode(self, mode: Mode) -> None:
        log.info("conversation.mode_change", old=self._mode.value, new=mode.value)
        self._mode = mode

    def clear(self) -> None:
        self._history.clear()
        log.info("conversation.cleared")

    def _build_messages(self) -> list[Message]:
        system: Message = {"role": "system", "content": get_system_prompt(self._mode)}
        tail = self._history[-(self._max_turns * 2):]
        return [system, *tail]

    def chat(self, user_text: str) -> str:
        """Add user turn, stream LLM reply, return the full reply string."""
        self._history.append({"role": "user", "content": user_text})
        log.info("conversation.user", text=user_text)

        reply = "".join(self._backend.chat(self._build_messages())).strip()

        self._history.append({"role": "assistant", "content": reply})
        log.info("conversation.assistant", text=reply)
        return reply

    def stream_chat(self, user_text: str) -> Iterator[str]:
        """Streaming variant — yields text chunks as they arrive.

        Appends the full assembled reply to history once the stream is exhausted.
        Use this when the caller wants to pipe chunks to TTS without waiting for
        the full response (streaming TTS, Week 2).
        """
        self._history.append({"role": "user", "content": user_text})
        log.info("conversation.user", text=user_text)

        buffer: list[str] = []
        for chunk in self._backend.chat(self._build_messages()):
            buffer.append(chunk)
            yield chunk

        reply = "".join(buffer).strip()
        self._history.append({"role": "assistant", "content": reply})
        log.info("conversation.assistant", text=reply)
