"""Conversation state — message history + LLM dispatch.

`ConversationManager` is the single point of contact between the runtime
and the LLM. It owns the history, injects the system prompt, and enforces
the sliding-window context limit. An optional MemoryStore injects relevant
past context into the system prompt when available.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING

from ..config import Mode
from ..llm.ollama_backend import LLMBackend, Message
from ..llm.prompts import get_system_prompt
from ..log import get_logger

if TYPE_CHECKING:
    from .memory import MemoryStore

log = get_logger(__name__)


class ConversationManager:
    def __init__(
        self,
        backend: LLMBackend,
        mode: Mode = Mode.GENERAL,
        max_turns: int = 20,
        memory: MemoryStore | None = None,
    ) -> None:
        self._backend = backend
        self._mode = mode
        self._max_turns = max_turns
        self._memory = memory
        self._history: list[Message] = []
        self._context_hint: str = ""  # injected for one turn (e.g. active window)

    @property
    def mode(self) -> Mode:
        return self._mode

    def set_mode(self, mode: Mode) -> None:
        log.info("conversation.mode_change", old=self._mode.value, new=mode.value)
        self._mode = mode

    def set_context_hint(self, hint: str) -> None:
        """Set a one-turn context string (e.g. active window title) to inject into the system prompt."""
        self._context_hint = hint

    def clear(self) -> None:
        self._history.clear()
        log.info("conversation.cleared")

    def _build_messages(self) -> list[Message]:
        system_content = get_system_prompt(self._mode)
        if self._memory and self._history:
            ctx = self._memory.get_relevant_context(self._history[-1]["content"])
            if ctx:
                system_content += f"\n\nRelevant from past conversations:\n{ctx}"
        if self._context_hint:
            system_content += f"\n\n{self._context_hint}"
            self._context_hint = ""  # consume after one turn
        system: Message = {"role": "system", "content": system_content}
        tail = self._history[-(self._max_turns * 2):]
        return [system, *tail]

    def chat(self, user_text: str) -> str:
        """Add user turn, stream LLM reply, return the full reply string."""
        self._history.append({"role": "user", "content": user_text})
        log.info("conversation.user", text=user_text)

        reply = "".join(self._backend.chat(self._build_messages())).strip()

        self._history.append({"role": "assistant", "content": reply})
        log.info("conversation.assistant", text=reply)
        if self._memory:
            self._memory.store_turn(user_text, reply)
        return reply

    def stream_chat(self, user_text: str) -> Iterator[str]:
        """Streaming variant — yields text chunks as they arrive.

        Appends the full assembled reply to history once the stream is exhausted.
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
        if self._memory:
            self._memory.store_turn(user_text, reply)
