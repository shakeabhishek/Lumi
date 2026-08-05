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

A note on names — **Lumi does not answer to "Hey Lumi" yet.** openwakeword
ships only pre-trained models: `alexa`, `hey_jarvis`, `hey_marvin`,
`hey_mycroft`, `weather`, and a family of timer phrases (enumerated directly
off the installed package on the Pi, 2026-08-05). There is no `hey_lumi`, so
the shipping default is `hey_jarvis` as a stand-in. That's a product-identity
gap, not just a config detail: the tagline promises "Hey Lumi" and the
onboarding flow invites the user to *name* their Lumi, but the device
currently wakes to someone else's name. Tracked in ROADMAP.md — the fix is a
custom-trained model, see `docs/wake-word-training.md`.

Two corrections to an earlier note here (2026-07-02) that read "bare
constructor, deliberately no kwargs" because `wakeword_models=` raised
TypeError:

  1. That kwarg wasn't *removed* in 0.4.0, it was **renamed** to
     `wakeword_model_paths` (verified against the installed version,
     2026-08-05). Custom ONNX models can be loaded — the capability was
     there all along under a different name, so the fallback to a bare
     `Model()` was unnecessary.
  2. Loading by explicit path changes the score-dict keys. Bare `Model()`
     keys on friendly names (`hey_jarvis`); `wakeword_model_paths=[...]`
     keys on the **file stem** (`hey_jarvis_v0.1`). `_listen()` looks up
     `self._model_name` in that dict, so a mismatch means the lookup
     silently returns 0.0 and the wake word never fires, with no error
     anywhere. `_load_model()` now validates the configured name against
     what actually loaded and logs `wake.model_missing` at error level
     rather than going quietly deaf.
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
        model_path: Path | None = None,
    ) -> None:
        """`model` is the score-dict key to watch. `model_path`, if given,
        points at a custom-trained ONNX (e.g. a "Hey Lumi" model) to load
        instead of the bundled set — its file stem must equal `model`, since
        that's how openwakeword keys path-loaded models."""
        self._model_name = model
        self._threshold = threshold
        self._cooldown_s = cooldown_s
        self._input_device = input_device
        self._model_path = model_path
        # Resolved in _open_stream() once the device can be probed. Defaults
        # keep the no-resample path intact for 16 kHz-capable hardware.
        self._capture_rate = self._SAMPLE_RATE
        self._capture_frame_len = self._FRAME_LEN
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

        # A custom-trained model (the "Hey Lumi" path — see
        # docs/wake-word-training.md) is loaded by explicit path, and ONLY
        # it: no reason to also run inference on five phrases we ignore.
        # Otherwise fall back to the bundled pretrained set.
        #
        # `inference_framework=` genuinely is gone in 0.4.0 — don't re-add
        # it. `wakeword_model_paths=` is the current name for what used to
        # be `wakeword_models=`.
        if self._model_path is not None and self._model_path.exists():
            model = Model(wakeword_model_paths=[str(self._model_path)])
            log.info("wake.model_loaded", source="custom", path=str(self._model_path))
        else:
            if self._model_path is not None:
                log.warning(
                    "wake.custom_model_absent",
                    path=str(self._model_path),
                    falling_back_to="bundled pretrained models",
                )
            model = Model()
            log.info("wake.model_loaded", source="bundled")

        # Guard the silent-deafness failure: _listen() looks the configured
        # name up in predict()'s score dict, and a miss just reads as 0.0
        # forever — the wake word would never fire and nothing would say
        # why. Note the two key conventions: bundled models key on friendly
        # names ("hey_jarvis"), path-loaded ones on the file stem
        # ("hey_lumi" for hey_lumi.onnx).
        loaded = getattr(model, "models", None)
        available = sorted(loaded.keys()) if isinstance(loaded, dict) else []
        if available and self._model_name not in available:
            log.error(
                "wake.model_missing",
                requested=self._model_name,
                available=available,
                consequence="wake word will NEVER fire — score lookup returns 0.0",
            )
        return model

    def _open_stream(self) -> None:
        import sounddevice as sd  # noqa: PLC0415

        from .resample import StreamResampler, pick_capture_rate  # noqa: PLC0415

        # openwakeword's 16 kHz requirement is not negotiable — its
        # melspectrogram frontend is trained at that rate and takes 1280-sample
        # (80 ms) frames. Feeding it 48 kHz doesn't error, it silently wrecks
        # accuracy. Lumi's USB mic can't do 16 kHz at all, so the stream opens
        # at whatever the device accepts and each block is converted down.
        self._capture_rate = pick_capture_rate(self._input_device, self._SAMPLE_RATE)
        # Blocksize scaled so each read yields exactly one post-resample frame:
        # 3840 at 48 kHz, 3528 at 44.1 kHz (3528 * 160/441 == 1280 exactly).
        self._capture_frame_len = round(
            self._FRAME_LEN * self._capture_rate / self._SAMPLE_RATE,
        )
        # Stateful, not per-block: filtering each frame independently would
        # put a step discontinuity at every 80 ms boundary — 12.5 clicks a
        # second into the very model that's listening for a short pattern.
        self._resampler = StreamResampler(self._capture_rate, self._SAMPLE_RATE)
        self._stream = sd.InputStream(
            samplerate=self._capture_rate,
            channels=1,
            dtype="int16",
            blocksize=self._capture_frame_len,
            device=self._input_device,
        )
        self._stream.start()  # type: ignore[attr-defined]

    def _to_model_frame(self, samples: object) -> object:
        """Resample one captured block to exactly _FRAME_LEN int16 samples."""
        import numpy as np  # noqa: PLC0415

        if self._capture_rate == self._SAMPLE_RATE:
            return samples
        # Resampled as raw int16 magnitudes rather than normalised floats: the
        # FIR has unity DC gain, so levels survive, and it saves a scaling
        # round-trip. float32's 24-bit mantissa covers int16 exactly.
        converted = self._resampler.process(np.asarray(samples, dtype=np.float32))
        # The FIR can overshoot slightly on transients — clip before the cast
        # so a loud consonant wraps to a negative sample instead of clipping.
        converted = np.clip(converted, -32768.0, 32767.0)
        frame = converted.astype(np.int16)
        # openwakeword wants EXACTLY _FRAME_LEN; guard the off-by-one that
        # fractional ratios can produce rather than trusting the arithmetic.
        if frame.shape[0] > self._FRAME_LEN:
            frame = frame[: self._FRAME_LEN]
        elif frame.shape[0] < self._FRAME_LEN:
            frame = np.pad(frame, (0, self._FRAME_LEN - frame.shape[0]))
        return frame

    def _listen(self) -> None:
        from time import monotonic  # noqa: PLC0415

        import numpy as np  # noqa: PLC0415

        last_fire = 0.0
        try:
            while not self._stop.is_set():
                frame, _overflowed = self._stream.read(self._capture_frame_len)  # type: ignore[attr-defined]
                samples = (
                    np.frombuffer(frame, dtype=np.int16)
                    if isinstance(frame, bytes)
                    else frame[:, 0]
                )
                scores = self._oww.predict(self._to_model_frame(samples))  # type: ignore[union-attr]
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
