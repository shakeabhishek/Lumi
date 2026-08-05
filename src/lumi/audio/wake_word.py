"""Wake-word detection.

Four sources:
  - PushToTalkWake: press Enter to wake. Default for headless dev.
  - OpenWakeWordWake: continuous mic listening with on-device ONNX models.
    Lazy-imports openwakeword + sounddevice so the package stays optional.
  - FileTriggerWake: polls for a wake trigger dropped by the separate
    camera/gesture vision-worker process (wave gesture, presence).
  - CompositeWakeSource: races multiple sources, first to fire wins —
    used when camera_enabled pairs the primary source with
    FileTriggerWake so either voice or gesture can wake Lumi.

The interface (`WakeSource.wait_for_wake`) is what the runtime depends on, so
swapping detectors is a one-class change.

A note on names: openwakeword 0.4.0 ships 5 pre-trained models by default —
"alexa", "hey_mycroft", "hey_jarvis", "timer", "weather" (verified directly,
2026-07-02). "Hey Lumi" isn't pre-trained, so we use "hey_jarvis" as a proxy
until either a custom Lumi model is trained (openwakeword has a notebook for
this) or we swap to Porcupine, which generates custom wake words from a web
UI.
"""

from __future__ import annotations

import contextlib
import json
import threading
import time
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from pathlib import Path

from ..log import get_logger

log = get_logger(__name__)


class WakeSource(ABC):
    @abstractmethod
    def wait_for_wake(self) -> None:
        """Block until Lumi should wake up and start listening."""

    def stop(self) -> None:
        """Release any exclusive resources (e.g. a mic stream) the wake
        source is holding. Default no-op — most sources (PushToTalkWake)
        don't hold anything exclusive. OpenWakeWordWake overrides this to
        free the ALSA capture device so the voice loop's own recording
        stream can open right after wake fires (see its call site in
        _voice_loop — without this, mic.record() failed with "Device
        unavailable" because the wake listener's stream was still open,
        found live on the Pi 2026-07-02)."""


class PushToTalkWake(WakeSource):
    """Enter key = wake. Trivial, reliable, perfect for laptop dev."""

    def __init__(self, prompt: str = "[press Enter to talk to Lumi, Ctrl-C to quit] ") -> None:
        self._prompt = prompt

    def wait_for_wake(self) -> None:
        try:
            input(self._prompt)
        except EOFError:
            raise KeyboardInterrupt from None


class OpenWakeWordWake(WakeSource):
    """Continuous mic listening via openwakeword (local, on-device, ONNX).

    Runs a background thread that streams 16 kHz mono audio and feeds 1280-sample
    (80 ms) frames into the model. `wait_for_wake()` blocks on a threading.Event
    that the background thread sets when the model's score crosses `threshold`.
    Cooldown prevents back-to-back fires from a single utterance.
    """

    _FRAME_LEN = 1280            # 80 ms at 16 kHz — openwakeword's required chunk size
    _SAMPLE_RATE = 16000

    def __init__(
        self,
        model: str = "hey_jarvis",
        threshold: float = 0.6,
        cooldown_s: float = 2.0,
        input_device: int | str | None = None,
    ) -> None:
        self._model_name = model
        self._threshold = threshold
        self._cooldown_s = cooldown_s
        self._input_device = input_device
        self._event = threading.Event()
        self._oww: object | None = None
        self._stream: object | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    # ── public ──────────────────────────────────────────────────────────────

    def wait_for_wake(self) -> None:
        self._ensure_started()
        self._event.wait()
        self._event.clear()

    def stop(self) -> None:
        """Close the capture stream and let the background thread exit,
        freeing the ALSA device. Deliberately does NOT discard the loaded
        model (`self._oww`) — `_ensure_started()` reuses it on the next
        `wait_for_wake()` call so a stop/restart cycle (once per voice-loop
        turn) doesn't pay openwakeword's model-load cost every time."""
        self._stop.set()
        if self._stream is not None:
            try:
                self._stream.stop()  # type: ignore[attr-defined]
                self._stream.close()  # type: ignore[attr-defined]
            except Exception:
                pass
        self._stream = None
        self._thread = None  # lets _ensure_started() rebuild on next wait

    # ── internals ───────────────────────────────────────────────────────────

    def _ensure_started(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()  # undo a prior stop() so the new thread's loop runs
        if self._oww is None:
            self._oww = self._load_model()
        self._open_stream()
        self._thread = threading.Thread(target=self._listen, daemon=True)
        self._thread.start()
        log.info("wake.openwakeword.started", model=self._model_name, threshold=self._threshold)

    def _load_model(self) -> object:
        from openwakeword.model import Model  # noqa: PLC0415

        # Bare constructor, deliberately no kwargs: `wakeword_models=` /
        # `inference_framework=` were removed in openwakeword 0.4.0 (verified
        # directly against the installed version, 2026-07-02 — passing them
        # raises `TypeError: AudioFeatures.__init__() got an unexpected
        # keyword argument 'inference_framework'`). Model() bare loads all 5
        # default pretrained models; _listen() below already picks just
        # `self._model_name` out of the returned scores dict, so loading the
        # others too costs a little idle CPU but changes nothing behaviorally.
        return Model()

    def _open_stream(self) -> None:
        import sounddevice as sd  # noqa: PLC0415

        self._stream = sd.InputStream(
            samplerate=self._SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=self._FRAME_LEN,
            device=self._input_device,
        )
        self._stream.start()  # type: ignore[attr-defined]

    def _listen(self) -> None:
        import numpy as np  # noqa: PLC0415
        from time import monotonic  # noqa: PLC0415

        last_fire = 0.0
        try:
            while not self._stop.is_set():
                frame, _overflowed = self._stream.read(self._FRAME_LEN)  # type: ignore[attr-defined]
                samples = np.frombuffer(frame, dtype=np.int16) if isinstance(frame, bytes) else frame[:, 0]
                scores = self._oww.predict(samples)  # type: ignore[union-attr]
                score = float(scores.get(self._model_name, 0.0))
                if score >= self._threshold and (monotonic() - last_fire) >= self._cooldown_s:
                    log.info("wake.fired", score=round(score, 3))
                    last_fire = monotonic()
                    self._event.set()
        except Exception as exc:
            log.warning("wake.listen_error", error=str(exc))


class FileTriggerWake(WakeSource):
    """Polls data_dir/.wake_trigger.json, dropped by the separate
    vision-worker process (wave gesture or presence sit-down — see
    vision-worker/src/lumi_vision_worker/wake_trigger.py).

    Poll-based, not inotify: zero new dependencies, and a wake trigger
    has no latency budget tighter than ~150ms — a wave gesture takes the
    user the better part of a second to perform. Mirrors
    OpenWakeWordWake's background-thread + threading.Event shape, but the
    "sensor" is a file stat instead of an audio stream.

    Relies on stop() being called between voice-loop turns (already true
    today, via the same call site that frees OpenWakeWordWake's mic
    stream) to gate WHEN this polls at all: the poll thread only runs
    between wait_for_wake() calls, i.e. during IDLE, so a presence/wave
    trigger written mid-conversation just sits unread in the file until
    the loop returns to idle — at which point _MAX_TRIGGER_AGE_S decides
    whether it's still relevant or should be discarded as stale.
    """

    _MAX_TRIGGER_AGE_S = 5.0  # stale-trigger guard — same idea as
    # host_helper/send_to_lumi.py's pending-context max age: if Lumi was
    # mid-turn when the file landed, don't fire on a wave from 30s ago.

    def __init__(self, data_dir: Path, poll_s: float = 0.15) -> None:
        self._path = data_dir / ".wake_trigger.json"
        self._poll_s = poll_s
        self._event = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def wait_for_wake(self) -> None:
        self._ensure_started()
        self._event.wait()
        self._event.clear()

    def stop(self) -> None:
        self._stop.set()
        self._thread = None  # next wait_for_wake() rebuilds, same idiom as OpenWakeWordWake.stop()

    def _ensure_started(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()

    def _poll_loop(self) -> None:
        while not self._stop.is_set():
            self._check_once()
            time.sleep(self._poll_s)

    def _check_once(self) -> None:
        try:
            if not self._path.exists():
                return
            raw = self._path.read_text(encoding="utf-8")
            self._path.unlink(missing_ok=True)
            payload = json.loads(raw)
            ts = datetime.fromisoformat(payload.get("ts", ""))
            age = (datetime.now(UTC) - ts).total_seconds()
            if age > self._MAX_TRIGGER_AGE_S:
                log.info(
                    "wake.gesture_trigger_stale", age_s=round(age, 1), source=payload.get("source"),
                )
                return
            log.info("wake.gesture_trigger_consumed", source=payload.get("source"))
            self._event.set()
        except (OSError, ValueError, json.JSONDecodeError):
            pass


class CompositeWakeSource(WakeSource):
    """First-to-fire-wins wrapper over multiple wake sources. Built for
    camera_enabled=True: races the configured primary wake source
    (OpenWakeWordWake in production, PushToTalkWake in dev) against
    FileTriggerWake.

    Caveat, deliberately not hard-blocked: PushToTalkWake.wait_for_wake()
    blocks on input(), which Python cannot cancel from another thread.
    Composing it here is safe in practice only because laptop dev has no
    real camera/vision-worker running, so the file side never fires. The
    pairing this is actually built for is OpenWakeWordWake +
    FileTriggerWake on real hardware, where both children ARE cleanly
    stoppable.
    """

    def __init__(self, sources: list[WakeSource]) -> None:
        self._sources = sources
        self._event = threading.Event()

    def wait_for_wake(self) -> None:
        self._event.clear()
        for src in self._sources:
            threading.Thread(target=self._wait_one, args=(src,), daemon=True).start()
        self._event.wait()

    def _wait_one(self, src: WakeSource) -> None:
        try:
            src.wait_for_wake()
            self._event.set()
        except Exception as exc:
            log.warning("wake.composite_child_error", source=type(src).__name__, error=str(exc))

    def stop(self) -> None:
        for src in self._sources:
            with contextlib.suppress(Exception):
                src.stop()
