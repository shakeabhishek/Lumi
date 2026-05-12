"""Tests for VoiceID — enrollment, verification, and persistence."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from lumi.audio.voice_id import VoiceID, _THRESHOLD


_AUDIO = np.zeros(16000, dtype=np.float32)


class TestNoEnrollment:
    def test_trusts_everyone_when_no_embedding(self) -> None:
        v = VoiceID(data_dir=None)
        assert v.is_owner(_AUDIO, 16000) is True

    def test_trusts_everyone_when_data_dir_but_no_file(self, tmp_path: Path) -> None:
        v = VoiceID(data_dir=tmp_path)
        assert v.is_owner(_AUDIO, 16000) is True


class TestEnrollment:
    def _enroll(self, tmp_path: Path, embedding: np.ndarray) -> VoiceID:
        v = VoiceID(data_dir=tmp_path)
        encoder = MagicMock()
        encoder.embed_utterance.return_value = embedding
        with patch.object(VoiceID, "_get_encoder", return_value=encoder):
            v.enroll([_AUDIO, _AUDIO, _AUDIO], 16000)
        return v

    def test_embedding_saved_to_disk(self, tmp_path: Path) -> None:
        self._enroll(tmp_path, np.array([1.0, 0.0, 0.0]))
        assert (tmp_path / "owner_embedding.npy").exists()

    def test_embedding_loaded_on_init(self, tmp_path: Path) -> None:
        emb = np.array([0.5, 0.5, 0.0])
        np.save(tmp_path / "owner_embedding.npy", emb)
        v = VoiceID(data_dir=tmp_path)
        assert v._embedding is not None
        assert np.allclose(v._embedding, emb)

    def test_accepts_matching_voice(self, tmp_path: Path) -> None:
        v = self._enroll(tmp_path, np.array([1.0, 0.0, 0.0]))
        encoder = MagicMock()
        encoder.embed_utterance.return_value = np.array([1.0, 0.0, 0.0])
        with patch.object(VoiceID, "_get_encoder", return_value=encoder):
            assert v.is_owner(_AUDIO, 16000) is True

    def test_rejects_orthogonal_voice(self, tmp_path: Path) -> None:
        v = self._enroll(tmp_path, np.array([1.0, 0.0, 0.0]))
        encoder = MagicMock()
        # Cosine similarity = dot([0,1,0], [1,0,0]) = 0.0 < threshold
        encoder.embed_utterance.return_value = np.array([0.0, 1.0, 0.0])
        with patch.object(VoiceID, "_get_encoder", return_value=encoder):
            assert v.is_owner(_AUDIO, 16000) is False

    def test_threshold_boundary_above(self, tmp_path: Path) -> None:
        v = self._enroll(tmp_path, np.array([1.0, 0.0]))
        encoder = MagicMock()
        encoder.embed_utterance.return_value = np.array([_THRESHOLD, 0.0])
        with patch.object(VoiceID, "_get_encoder", return_value=encoder):
            assert v.is_owner(_AUDIO, 16000) is True

    def test_degrades_gracefully_on_encoder_error(self, tmp_path: Path) -> None:
        v = self._enroll(tmp_path, np.array([1.0, 0.0, 0.0]))
        with patch.object(VoiceID, "_get_encoder", side_effect=RuntimeError("no model")):
            assert v.is_owner(_AUDIO, 16000) is True
