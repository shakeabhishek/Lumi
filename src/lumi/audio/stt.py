"""Speech-to-text via faster-whisper.

`faster-whisper` uses CTranslate2 internally — smaller and faster than
openai-whisper, and runs comfortably on the Pi 5 CPU once we get there.

The `tiny` model is ~75MB and gives roughly 0.5s transcription on short clips.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from ..log import get_logger

log = get_logger(__name__)


class WhisperSTT:
    def __init__(
        self,
        model_name: str = "tiny",
        compute_type: str = "int8",
        cache_dir: Path | None = None,
        language: str = "en",
    ) -> None:
        self._model_name = model_name
        self._compute_type = compute_type
        self._cache_dir = cache_dir
        self._language = language
        self._model = None

    def _load(self) -> None:
        if self._model is not None:
            return
        from faster_whisper import WhisperModel  # noqa: PLC0415

        log.info("loading whisper", model=self._model_name, compute=self._compute_type)
        self._model = WhisperModel(
            self._model_name,
            device="cpu",
            compute_type=self._compute_type,
            download_root=str(self._cache_dir) if self._cache_dir else None,
        )

    def transcribe(self, audio: np.ndarray, sample_rate: int = 16000) -> str:
        """Block, return the transcribed text. Empty string on silence."""
        self._load()
        assert self._model is not None

        # faster-whisper expects float32 16kHz mono. Resampling if needed is out of
        # scope here — sample at 16k upstream.
        if sample_rate != 16000:
            raise ValueError(
                f"WhisperSTT expects 16kHz audio, got {sample_rate}Hz. Resample upstream."
            )
        if audio.dtype != np.float32:
            audio = audio.astype(np.float32)

        segments, info = self._model.transcribe(
            audio,
            language=self._language,
            beam_size=1,
            vad_filter=True,
        )
        text = " ".join(seg.text.strip() for seg in segments).strip()
        log.debug("stt.result", text=text, duration_s=info.duration)
        return text
