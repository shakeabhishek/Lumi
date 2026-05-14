"""Tests for the OpenWakeWord wake source.

We don't install openwakeword in the standard dev extras (it has its own
deps + model downloads), so these tests mock it out. They exercise the
fire/cooldown/threshold logic on synthetic predictions.
"""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock

import numpy as np
import pytest

from lumi.audio.wake_word import OpenWakeWordWake, PushToTalkWake


# ── PushToTalk ──────────────────────────────────────────────────────────────


def test_push_to_talk_eof_raises_keyboard_interrupt(monkeypatch) -> None:
    def _eof(_prompt: str) -> str:
        raise EOFError

    monkeypatch.setattr("builtins.input", _eof)
    with pytest.raises(KeyboardInterrupt):
        PushToTalkWake().wait_for_wake()


# ── OpenWakeWord — controlled simulation ───────────────────────────────────


def _make_wake_with_synthetic_predictions(
    scores: list[float], model: str = "hey_jarvis", threshold: float = 0.6, cooldown: float = 0.0
) -> tuple[OpenWakeWordWake, MagicMock, MagicMock]:
    """Build an OpenWakeWordWake with model + stream replaced by mocks.

    `scores` is the sequence of probabilities the fake model will return on
    each predict() call. The fake stream yields zeros.
    """
    w = OpenWakeWordWake(model=model, threshold=threshold, cooldown_s=cooldown)

    pred_iter = iter(scores)

    def predict(_samples: np.ndarray) -> dict[str, float]:
        try:
            return {model: next(pred_iter)}
        except StopIteration:
            w._stop.set()
            return {model: 0.0}

    fake_model = MagicMock()
    fake_model.predict.side_effect = predict
    fake_stream = MagicMock()
    fake_stream.read.return_value = (np.zeros(1280, dtype=np.int16).reshape(-1, 1), False)

    w._oww = fake_model
    w._stream = fake_stream
    return w, fake_model, fake_stream


def test_fires_when_score_crosses_threshold() -> None:
    w, _, _ = _make_wake_with_synthetic_predictions([0.1, 0.3, 0.9, 0.2])
    w._thread = threading.Thread(target=w._listen, daemon=True)
    w._thread.start()
    assert w._event.wait(timeout=2.0), "wake event should have fired"


def test_does_not_fire_below_threshold() -> None:
    w, _, _ = _make_wake_with_synthetic_predictions([0.1, 0.2, 0.3, 0.4, 0.5])
    w._thread = threading.Thread(target=w._listen, daemon=True)
    w._thread.start()
    fired = w._event.wait(timeout=0.5)
    w._stop.set()
    assert fired is False


def test_cooldown_suppresses_back_to_back_fires() -> None:
    # Two consecutive high scores, but cooldown is 10s — only the first should fire.
    w, _, _ = _make_wake_with_synthetic_predictions(
        [0.95, 0.95, 0.95], cooldown=10.0
    )
    fire_times: list[float] = []
    real_set = w._event.set

    def record_set() -> None:
        fire_times.append(time.monotonic())
        real_set()

    w._event.set = record_set  # type: ignore[method-assign]

    w._thread = threading.Thread(target=w._listen, daemon=True)
    w._thread.start()
    w._thread.join(timeout=1.0)
    assert len(fire_times) == 1, f"cooldown should suppress later fires; got {fire_times}"


def test_stop_closes_stream() -> None:
    w, _, fake_stream = _make_wake_with_synthetic_predictions([0.1])
    w.stop()
    fake_stream.stop.assert_called_once()
    fake_stream.close.assert_called_once()


def test_wait_for_wake_blocks_until_event() -> None:
    w, _, _ = _make_wake_with_synthetic_predictions([0.95], cooldown=0.0)
    # Manually start the bg thread (skip _ensure_started so we don't open a real mic).
    w._thread = threading.Thread(target=w._listen, daemon=True)
    w._thread.start()

    # First wait should return; event should be cleared after.
    t0 = time.monotonic()
    w._event.wait(timeout=1.0)
    w._event.clear()
    assert time.monotonic() - t0 < 1.0
    assert not w._event.is_set()
