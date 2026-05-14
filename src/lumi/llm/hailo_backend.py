"""HailoBackend — production LLM inference on the AI HAT+ 2 NPU.

Stub for Phase 5. The interface mirrors OllamaBackend so swapping the backend
is a config-only change (`LLM_BACKEND=hailo` instead of `ollama`). The real
implementation will load a quantized `.hef` model via the hailo-platform
runtime and stream tokens off the NPU.

Why a stub now: keeps the import graph honest (`llm/__init__.py` can export it,
`make_llm_backend` can route to it for tests) and forces the production path
to fit the same `LLMBackend` ABC. Any deviation surfaces here, not in a
last-minute Phase 5 refactor.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from ..log import get_logger
from .ollama_backend import LLMBackend, Message

log = get_logger(__name__)


class HailoBackend(LLMBackend):
    """Streams token chunks from a Hailo-compiled LLM on the AI HAT+ 2.

    Constructor arguments are deliberately the same shape as OllamaBackend so
    the dispatch in `make_llm_backend` reads cleanly. Loading is lazy — the
    Hailo runtime is only imported when the backend is actually used.
    """

    def __init__(self, model_path: Path | str, model_name: str = "qwen2.5-1.5b") -> None:
        self._model_path = Path(model_path)
        self._model_name = model_name
        self._runtime: object | None = None

    @property
    def model(self) -> str:
        return f"hailo:{self._model_name}"

    def chat(self, messages: list[Message]) -> Iterator[str]:
        runtime = self._get_runtime()
        # Phase 5: prompt-format the messages for the HEF and stream decode.
        # Stub raises clearly so accidental selection in dev surfaces early.
        raise NotImplementedError(
            "HailoBackend is a Phase 5 stub. Use ollama or mock backend on the laptop."
        )

    def _get_runtime(self) -> object:
        if self._runtime is None:
            try:
                import hailo_platform  # type: ignore[import-not-found]  # noqa: PLC0415
            except ImportError as exc:
                raise RuntimeError(
                    "hailo-platform runtime not installed. Available on the Pi 5 with AI HAT+ 2 only."
                ) from exc
            if not self._model_path.exists():
                raise FileNotFoundError(f"Hailo model not found: {self._model_path}")
            log.info("llm.backend.ready", backend="hailo", model=self._model_name)
            self._runtime = hailo_platform  # placeholder until Phase 5 wiring
        return self._runtime
