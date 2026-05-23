"""LLM backend abstraction — interface + Ollama + Mock implementations.

The `LLMBackend` ABC is intentionally placed here (not a separate base.py)
because the llm/ package has a single real backend in V1. When hailo_backend.py
lands in the hardware phase, it imports `LLMBackend` from here.

Callers wanting the full reply as a string: `"".join(backend.chat(msgs))`
Callers doing streaming TTS: iterate `backend.chat(msgs)` directly.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from typing import Any

from ..config import LLMBackendName, Settings
from ..log import get_logger

log = get_logger(__name__)

Message = dict[str, str]


class LLMBackend(ABC):
    @abstractmethod
    def chat(self, messages: list[Message]) -> Iterator[str]:
        """Yield response text chunks. Consume fully to get the complete reply."""

    @property
    @abstractmethod
    def model(self) -> str: ...


class OllamaBackend(LLMBackend):
    def __init__(self, host: str, model_name: str) -> None:
        self._host = host
        self._model_name = model_name
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            import ollama  # noqa: PLC0415

            self._client = ollama.Client(host=self._host)
            log.info("llm.backend.ready", backend="ollama", model=self._model_name, host=self._host)
        return self._client

    @property
    def model(self) -> str:
        return f"ollama:{self._model_name}"

    def chat(self, messages: list[Message]) -> Iterator[str]:
        client = self._get_client()
        log.debug("llm.request", n_messages=len(messages))
        stream = client.chat(
            model=self._model_name,
            messages=messages,
            stream=True,
        )
        for chunk in stream:
            content: str = chunk.message.content
            if content:
                yield content


class MockLLMBackend(LLMBackend):
    """Test double — yields word-by-word to exercise streaming consumers."""

    def __init__(self, response: str = "I heard you.") -> None:
        self._response = response
        self.received_messages: list[list[Message]] = []

    @property
    def model(self) -> str:
        return "mock"

    def chat(self, messages: list[Message]) -> Iterator[str]:
        self.received_messages.append(messages)
        for word in self._response.split():
            yield word + " "


def make_llm_backend(cfg: Settings) -> LLMBackend:
    if cfg.llm_backend == LLMBackendName.MOCK:
        return MockLLMBackend()
    if cfg.llm_backend == LLMBackendName.OLLAMA:
        return OllamaBackend(cfg.ollama_host, cfg.ollama_model)
    if cfg.llm_backend == LLMBackendName.HAILO:
        from .hailo_backend import HailoBackend  # noqa: PLC0415

        return HailoBackend(host=cfg.hailo_host, model_name=cfg.hailo_model)
    raise ValueError(f"Unknown LLM backend: {cfg.llm_backend}")
