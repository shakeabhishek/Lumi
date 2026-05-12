"""Speaker verification — recognizes the device owner via Resemblyzer.

Enrollment: record several clips, compute mean speaker embedding, persist to disk.
Verification: embed new clip, compare cosine similarity against stored embedding.

Falls back to trusting everyone when:
  - not yet enrolled (no embedding file)
  - resemblyzer not installed
  - any runtime error
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from ..log import get_logger

log = get_logger(__name__)

_THRESHOLD = 0.75


class VoiceID:
    def __init__(self, data_dir: Path | None = None) -> None:
        self._embedding_path = (data_dir / "owner_embedding.npy") if data_dir else None
        self._embedding: np.ndarray | None = self._load()

    def enroll(self, audio_samples: list[np.ndarray], sample_rate: int) -> None:  # noqa: ARG002
        """Compute mean speaker embedding from enrollment clips and persist to disk."""
        encoder = self._get_encoder()
        embeddings = [encoder.embed_utterance(a) for a in audio_samples]
        self._embedding = np.mean(embeddings, axis=0)
        if self._embedding_path:
            self._embedding_path.parent.mkdir(parents=True, exist_ok=True)
            np.save(self._embedding_path, self._embedding)
        log.info("voice_id.enrolled")

    def is_owner(self, audio: np.ndarray, sample_rate: int) -> bool:  # noqa: ARG002
        if self._embedding is None:
            return True
        try:
            encoder = self._get_encoder()
            emb = encoder.embed_utterance(audio)
            similarity = float(np.dot(emb, self._embedding))
            log.info("voice_id.check", similarity=round(similarity, 3))
            return similarity >= _THRESHOLD
        except Exception:
            return True

    @staticmethod
    def _get_encoder() -> object:
        from resemblyzer import VoiceEncoder  # noqa: PLC0415

        return VoiceEncoder()

    def _load(self) -> np.ndarray | None:
        if self._embedding_path and self._embedding_path.exists():
            return np.load(self._embedding_path)
        return None
