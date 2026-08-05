"""Tests for the OpenWakeWord wake source.

We don't install openwakeword in the standard dev extras (it has its own
deps + model downloads), so these tests mock it out. They exercise the
fire/cooldown/threshold logic on synthetic predictions.
"""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from lumi.audio.wake_word import (
    CompositeWakeSource,
    FileTriggerWake,
    OpenWakeWordWake,
    PushToTalkWake,
    WakeSource,
)

# ── PushToTalk ──────────────────────────────────────────────────────────────


def test_push_to_talk_eof_raises_keyboard_interrupt(monkeypatch) -> None:
    def _eof(_prompt: str) -> str:
        raise EOFError

    monkeypatch.setattr("builtins.input", _eof)
    with pytest.raises(KeyboardInterrupt):
        PushToTalkWake().wait_for_wake()


def test_push_to_talk_stop_is_a_safe_noop() -> None:
    """_voice_loop calls wake.stop() unconditionally after every wake fire
    (to free the mic for recording, see OpenWakeWordWake.stop()) —
    PushToTalkWake never holds an exclusive stream, so this must not
    raise (the WakeSource ABC provides this default)."""
    PushToTalkWake().stop()  # must not raise


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


def test_stop_clears_thread_so_ensure_started_rebuilds() -> None:
    """Regression test for a real bug found on the Pi (2026-07-02):
    OpenWakeWordWake's own capture stream stayed open forever, so when
    _voice_loop's mic.record() then tried to open ITS OWN stream on the
    same ReSpeaker device, ALSA rejected it ("Device unavailable") every
    single time the wake word fired. Fix: stop() must reset _thread to
    None so the NEXT wait_for_wake()'s _ensure_started() actually rebuilds
    the stream (freeing the device in between) instead of no-op'ing on
    its `if self._thread is not None: return` guard."""
    w, fake_model, _ = _make_wake_with_synthetic_predictions([0.1])
    w._thread = MagicMock()  # pretend already running
    w.stop()
    assert w._thread is None


def test_stop_preserves_loaded_model_to_avoid_reload_cost() -> None:
    """stop()/restart happens once per voice-loop turn — must not force a
    full openwakeword model reload (onnxruntime session init) every turn."""
    w, fake_model, _ = _make_wake_with_synthetic_predictions([0.1])
    w._oww = fake_model
    w.stop()
    assert w._oww is fake_model


def test_load_model_calls_bare_constructor() -> None:
    """Regression lock for the openwakeword 0.4.0 compatibility fix.

    The old call — Model(wakeword_models=[...], inference_framework="onnx")
    — raises TypeError against the real 0.4.0 API (verified on the Pi,
    2026-07-02): those kwargs were removed. _load_model() must call Model()
    with no arguments; _listen() already picks the configured model name out
    of the returned scores dict regardless of how many models loaded."""
    fake_model_cls = MagicMock()
    fake_module = MagicMock()
    fake_module.Model = fake_model_cls

    with patch.dict(sys.modules, {"openwakeword": MagicMock(), "openwakeword.model": fake_module}):
        w = OpenWakeWordWake(model="hey_jarvis")
        w._load_model()

    fake_model_cls.assert_called_once_with()


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


# ── FileTriggerWake ─────────────────────────────────────────────────────────


def _write_trigger(data_dir, source: str, age_s: float = 0.0) -> None:
    """Directly write a trigger file, bypassing the vision-worker's own
    client — this test only cares about FileTriggerWake's consumption
    side. age_s lets a test simulate an already-stale trigger."""
    ts = datetime.now(UTC) - timedelta(seconds=age_s)
    path = data_dir / ".wake_trigger.json"
    path.write_text(json.dumps({"source": source, "ts": ts.isoformat()}), encoding="utf-8")


def test_file_trigger_wake_fires_on_fresh_trigger(tmp_path) -> None:
    wake = FileTriggerWake(tmp_path, poll_s=0.02)
    _write_trigger(tmp_path, source="gesture:wave")

    fired = threading.Event()

    def _wait() -> None:
        wake.wait_for_wake()
        fired.set()

    t = threading.Thread(target=_wait, daemon=True)
    t.start()
    assert fired.wait(timeout=2.0), "wake should have fired on a fresh trigger file"
    wake.stop()


def test_file_trigger_wake_ignores_stale_trigger(tmp_path) -> None:
    wake = FileTriggerWake(tmp_path, poll_s=0.02)
    _write_trigger(tmp_path, source="presence", age_s=FileTriggerWake._MAX_TRIGGER_AGE_S + 1.0)

    fired = threading.Event()

    def _wait() -> None:
        wake.wait_for_wake()
        fired.set()

    t = threading.Thread(target=_wait, daemon=True)
    t.start()
    assert not fired.wait(timeout=0.5), "a stale trigger must not fire wake"
    wake.stop()


def test_file_trigger_wake_consumes_the_file() -> None:
    """The trigger file must be deleted after being read, whether fresh
    or stale — otherwise the same trigger could fire repeatedly."""
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        _write_trigger(data_dir, source="gesture:wave")
        wake = FileTriggerWake(data_dir, poll_s=0.02)
        wake._check_once()
        assert not (data_dir / ".wake_trigger.json").exists()


def test_file_trigger_wake_no_file_does_not_fire(tmp_path) -> None:
    wake = FileTriggerWake(tmp_path, poll_s=0.02)
    wake._check_once()
    assert not wake._event.is_set()


def test_file_trigger_wake_stop_allows_rebuild(tmp_path) -> None:
    wake = FileTriggerWake(tmp_path)
    wake._thread = MagicMock()  # pretend already running
    wake.stop()
    assert wake._thread is None


# ── CompositeWakeSource ──────────────────────────────────────────────────────


class _FakeWakeSource(WakeSource):
    """Fires immediately if `fires` is True, otherwise blocks forever
    until stop() is called."""

    def __init__(self, fires: bool) -> None:
        self._fires = fires
        self._stopped = threading.Event()
        self.stop_called = False

    def wait_for_wake(self) -> None:
        if self._fires:
            return
        self._stopped.wait()

    def stop(self) -> None:
        self.stop_called = True
        self._stopped.set()


def test_composite_returns_as_soon_as_fast_source_fires() -> None:
    fast = _FakeWakeSource(fires=True)
    slow = _FakeWakeSource(fires=False)
    composite = CompositeWakeSource([fast, slow])

    t0 = time.monotonic()
    composite.wait_for_wake()
    assert time.monotonic() - t0 < 1.0


def test_composite_stop_reaches_all_children() -> None:
    a = _FakeWakeSource(fires=False)
    b = _FakeWakeSource(fires=False)
    composite = CompositeWakeSource([a, b])
    composite.stop()
    assert a.stop_called
    assert b.stop_called


def test_composite_child_error_does_not_prevent_other_child_from_firing() -> None:
    class _BrokenWakeSource(WakeSource):
        def wait_for_wake(self) -> None:
            raise RuntimeError("simulated child failure")

    broken = _BrokenWakeSource()
    working = _FakeWakeSource(fires=True)
    composite = CompositeWakeSource([broken, working])

    t0 = time.monotonic()
    composite.wait_for_wake()
    assert time.monotonic() - t0 < 1.0, "a broken child must not block the composite forever"
