"""Text-to-speech.

Two backends:
- `PiperTTS`: neural TTS. What ships on the Pi. Needs a voice ONNX downloaded.
- `MacSayTTS`: shells out to macOS's built-in `say` command. Zero-setup on dev
  laptops — useful so the voice loop works the moment the project is cloned,
  before anyone downloads Piper voices.

The runtime depends on the `TTS` protocol, not either implementation.
"""

from __future__ import annotations

import contextlib
import platform
import shutil
import subprocess
import threading
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Protocol

from ..log import get_logger

log = get_logger(__name__)


class TTS(Protocol):
    def speak(self, text: str) -> None:
        """Block until the text has been spoken."""

    def stop(self) -> None:
        """Cut playback of the in-flight utterance immediately, from another
        thread. Must be safe to call when nothing is playing (no-op) and
        must cause any concurrent `speak()` to return promptly rather than
        finishing the utterance. This is what makes barge-in possible — see
        `speak_streaming`'s `cancel` parameter."""

    @property
    def name(self) -> str: ...


class MacSayTTS:
    """macOS `say` command. Voice picked to match Lumi's warm/calm brand."""

    def __init__(self, voice: str = "Ava", rate: int = 180) -> None:
        self._voice = voice
        self._rate = rate
        # Held so stop() can kill an in-flight utterance. `say` is a
        # subprocess rather than PortAudio playback, so this needs its own
        # handle — sd.stop() has no effect on it.
        self._proc: subprocess.Popen[bytes] | None = None
        self._stopped = threading.Event()

    @property
    def name(self) -> str:
        return f"mac-say:{self._voice}"

    def speak(self, text: str) -> None:
        if not text or self._stopped.is_set():
            return
        try:
            proc = subprocess.Popen(
                ["say", "-v", self._voice, "-r", str(self._rate), text],
            )
        except FileNotFoundError:
            log.warning("`say` not available; falling back to print")
            print(f"[Lumi]: {text}")
            return
        self._proc = proc
        # Re-checked after the process exists: stop() can land between the
        # is_set() check above and Popen returning, in which case it saw
        # _proc is None and had nothing to terminate.
        if self._stopped.is_set():
            with contextlib.suppress(Exception):
                proc.terminate()
        try:
            proc.wait()
        finally:
            self._proc = None

    def stop(self) -> None:
        self._stopped.set()
        proc = self._proc
        if proc is None:
            return
        with contextlib.suppress(Exception):
            proc.terminate()

    def reset(self) -> None:
        self._stopped.clear()


class PiperTTS:
    """Piper neural TTS via the `piper` Python package's PiperVoice API —
    NOT the `piper` CLI, and NOT a fresh subprocess per sentence.

    Voice ONNX + JSON must live at `voice_dir / voice_name.onnx{,.json}`.
    Audio plays back via `sounddevice` — the SAME library
    `hardware/audio_io.py` uses for mic capture — rather than piping into
    a separate `aplay`/`sox`/`ffplay` process.

    History of two real bugs found on the Pi, both from hardware testing:

    1. (2026-07-05) Used to shell out to `aplay` for playback. After ANY
       prior sounddevice/PortAudio capture in the same process (i.e.
       every single turn, since mic.record() always runs first), the
       next `aplay` invocation failed with "audio open error" — a
       PortAudio-vs-separate-ALSA-CLI-process conflict over the same
       hardware. Worse, Piper's own process then hung waiting on the
       wedged player, freezing the whole voice loop until manually
       killed. Fixed by routing playback through the same PortAudio
       abstraction as capture (sd.play/sd.wait) instead.

    2. (2026-07-05) User reported "sound starts 4-5s after the animation
       and caption appear." Measured directly: synthesizing via a fresh
       `subprocess.Popen(["piper", ...])` per sentence took ~3.7-5.6s —
       but a 4x longer sentence only took ~1.5x longer, ruling out
       per-character inference cost. Confirmed by loading the model via
       PiperVoice.load() ONCE and calling .synthesize() repeatedly:
       per-call time dropped to ~0.4-0.7s. The ~3.5s+ "synthesis time"
       was almost entirely subprocess-startup + ONNX-model-load
       overhead, paid fresh on every sentence. A different voice-quality
       tier didn't help (tested "low" vs "medium" — nearly identical
       time, since the fixed cost wasn't from inference), and neither
       did a higher CPU scheduling priority (only ~5% faster — Chromium
       CPU contention wasn't the primary bottleneck either). Since the
       voice loop is already a long-lived process, loading the model
       ONCE (lazily, on first speak() call) and reusing the same
       PiperVoice for every subsequent sentence for the rest of the
       process's lifetime is the actual fix.
    """

    _TARGET_RMS = 1.8

    def __init__(self, voice: str, voice_dir: Path, output_device: str | None = None) -> None:
        self._voice = voice
        self._voice_dir = voice_dir
        self._model_path = voice_dir / f"{voice}.onnx"
        self._output_device = output_device
        self._piper_voice: object | None = None  # lazy-loaded, then kept resident
        # Barge-in latch — see stop()/reset() for why sd.stop() alone isn't
        # enough to suppress an utterance.
        self._stopped = threading.Event()

    @property
    def name(self) -> str:
        return f"piper:{self._voice}"

    def _ensure_loaded(self) -> object:
        if self._piper_voice is None:
            if not self._model_path.exists():
                raise FileNotFoundError(
                    f"Piper voice not found: {self._model_path}. "
                    "Download from https://github.com/rhasspy/piper/releases."
                )
            from piper import PiperVoice  # noqa: PLC0415

            self._piper_voice = PiperVoice.load(str(self._model_path))
        return self._piper_voice

    @classmethod
    def _boost_loudness(cls, samples: "np.ndarray") -> "np.ndarray":
        """Boost quiet speech up to a target average loudness using
        per-window (not whole-clip) gain — a simple compressor, not just
        a single static gain — then softly saturate any remaining peaks.

        Found on the Pi (2026-07-05): even at 100% hardware volume,
        Piper's speech sounded "very low." Two earlier passes both used
        ONE static gain factor for the entire utterance (computed from
        its overall RMS), with tanh softening whatever exceeded [-1, 1]:
        target 0.35 (hard clip), then 0.55, then 0.9 (tanh) — the user
        directly confirmed, live, that 0.9 was STILL "very low." Measured
        why raising the target further wouldn't help: tanh's returns
        diminish sharply (target 0.55/0.75/0.95/1.2 → actual RMS only
        0.39/0.46/0.52/0.57, with clipping-adjacent samples growing
        0.6%→6.7%) — a single global gain is fundamentally capped,
        because speech's quiet vowels and loud consonants share ONE
        multiplier; raising it enough to make the quiet parts audible
        over-saturates the loud parts, and the overall RMS barely moves
        either way.

        Fix: compute gain per ~93ms window (2048 samples at 22050Hz) from
        THAT window's own RMS, so quiet segments get boosted much harder
        than loud ones — this is what a basic compressor does. Gains are
        linearly interpolated between window centers (not applied as a
        hard step) to avoid audible zipper/pumping artifacts at window
        boundaries. Near-silent windows (RMS below a floor) are left
        essentially untouched rather than amplified toward the target —
        otherwise the noise floor between words would get boosted into
        audible hiss. A gain ceiling keeps any single window from being
        pushed to an extreme multiplier. Finishes with the same tanh
        safety saturation as before, since even per-window gain can still
        produce local overs.

        Windowing alone (with target still at 0.9) only moved actual
        clip RMS from ~0.14 to ~0.52 on a real sample — barely past the
        old single-gain result, since already-loud windows don't need
        boosting and dominate the clip's overall energy either way. The
        real payoff of windowing is that a MUCH higher target no longer
        costs proportionally more distortion (loud windows stay
        untouched; only quiet ones get pushed harder) — measured target
        1.8 landing at actual RMS ~0.65, matching the confirmed-audible
        test tone's ~0.64, at ~14% samples near saturation (soft tanh
        rounding, not a hard digital wall). Raised the target to 1.8 on
        that basis.
        """
        import numpy as np  # noqa: PLC0415

        n = samples.shape[0]
        if n == 0:
            return samples

        window = 2048
        n_windows = max(1, -(-n // window))  # ceil division
        gains = np.ones(n_windows, dtype=np.float32)
        silence_floor = 0.01  # below this, treat as noise/silence — don't amplify
        max_gain = 20.0
        for i in range(n_windows):
            start = i * window
            seg = samples[start:start + window]
            seg_rms = float(np.sqrt(np.mean(seg**2))) if seg.size else 0.0
            if seg_rms > silence_floor:
                gains[i] = min(cls._TARGET_RMS / seg_rms, max_gain)

        window_centers = (np.arange(n_windows, dtype=np.float32) + 0.5) * window
        sample_positions = np.arange(n, dtype=np.float32)
        smooth_gain = np.interp(sample_positions, window_centers, gains).astype(np.float32)

        return np.tanh(samples * smooth_gain).astype(np.float32)

    def speak(self, text: str) -> None:
        # Latch checked first, before the model load, so a barge-in that
        # already fired doesn't pay for work whose output gets discarded.
        if not text or self._stopped.is_set():
            return
        import numpy as np  # noqa: PLC0415
        import sounddevice as sd  # noqa: PLC0415

        voice = self._ensure_loaded()
        # Re-checked before and after synthesis: it's ~0.4-0.7s per sentence
        # on the Pi, a wide enough window for a barge-in to land inside, and
        # it shouldn't still produce audio afterwards.
        if self._stopped.is_set():
            return
        chunks = list(voice.synthesize(text))  # type: ignore[attr-defined]
        if not chunks or self._stopped.is_set():
            return
        # AudioChunk.audio_float_array is already [-1, 1] float — no
        # int16 normalization needed (that was only ever an artifact of
        # going through the CLI's raw-PCM stdout).
        samples = np.concatenate([c.audio_float_array for c in chunks]).astype(np.float32)
        samples = self._boost_loudness(samples)
        sd.play(samples, samplerate=chunks[0].sample_rate, device=self._output_device)
        sd.wait()

    def stop(self) -> None:
        """Cut playback mid-utterance. `sd.stop()` aborts the PortAudio
        stream, which is what unblocks the `sd.wait()` in speak().

        The latch matters as much as the sd.stop(): a barge-in can land in
        the window between two sentences, or during the ~0.4-0.7s of Piper
        synthesis before playback starts, where there is no active stream
        for sd.stop() to abort. Without the latch that utterance would
        still play. Cleared by `reset()` at the start of the next turn.
        """
        self._stopped.set()
        with contextlib.suppress(Exception):
            import sounddevice as sd  # noqa: PLC0415

            sd.stop()

    def reset(self) -> None:
        """Clear a previous stop() so this instance can speak again. Called
        by speak_streaming at the start of each reply — PiperTTS is loaded
        once and reused for the whole process lifetime, so the latch has to
        be per-turn, not per-instance."""
        self._stopped.clear()


_CANCEL_POLL_S = 0.05


def speak_streaming(
    tts: TTS,
    chunks: Iterator[str],
    *,
    on_sentence: Callable[[str, bool], None] | None = None,
    cancel: threading.Event | None = None,
) -> bool:  # noqa: F811
    """Buffer an LLM token stream into sentences and speak each as it completes.

    Returns True if the whole reply was spoken, False if it was cut short by
    `cancel` — the caller needs to know which happened so an interrupted
    turn can be logged and captioned differently from a completed one.

    `cancel`, if given, is an Event any other thread can set to barge in
    (open-palm gesture, ReSpeaker button, see runtime/barge_in.py). It cuts
    audio mid-sentence rather than at the next boundary — a barge-in that
    politely finished the current sentence would feel broken, because the
    sentence is exactly what the user is interrupting. Concretely:

      * a watcher thread calls `tts.stop()` the moment the event fires,
        which aborts PortAudio playback and unblocks the `sd.wait()` inside
        `PiperTTS.speak()`;
      * the worker stops pulling sentences off the queue, so everything
        already synthesized-but-unplayed is dropped rather than drained.
        That's the open question the GestureBadge comment flagged — dropping
        is the answer, since holding it would just replay stale speech;
      * the producer stops consuming the LLM stream, so a long reply doesn't
        keep generating into a void.

    Known limit, deliberately not papered over: if the LLM stream itself
    stalls with nothing queued, the producer is blocked inside
    `for chunk in chunks` and Python can't interrupt that from another
    thread. Cancellation lands when the next chunk arrives. This doesn't
    affect real barge-in — you can only interrupt speech that's playing,
    which means sentences are queued — and main.py's `_SPEAK_TIMEOUT_S`
    already backstops a genuinely wedged stream.

    Runs TTS in a background thread so audio plays while the LLM continues
    generating the next sentence — significantly reduces perceived latency.

    `on_sentence`, if given, is called once per sentence — the SAME MOMENT
    the worker thread is about to speak it, not the moment it's parsed off
    the incoming chunk stream — with `(sentence_text, is_last_sentence)`.
    This distinction matters: cloud LLM chunks routinely contain several
    complete sentences at once (found in real use, 2026-07-05, after the
    RoutedBackend cloud-first flip), so if the callback fired at parse
    time, all of that chunk's captions would fire in a burst milliseconds
    apart while the worker thread is still speaking through them one at a
    time — visually indistinguishable from "only the last one ever
    appeared," even though every sentence really was queued. Firing from
    the worker keeps captions in lockstep with what's actually audible.

    Deliberately just the ONE sentence, not the cumulative reply so far: an
    earlier cumulative design made the voice loop's live caption grow to
    contain the entire reply, which for a multi-sentence answer ate up the
    whole screen instead of reading like live captions (found in real use,
    2026-07-02). `is_last_sentence=True` on the final call lets the caller
    mark that turn's caption as complete without a separate full-text push.

    Determining "is this the last sentence" also can't happen at parse
    time — more chunks (and more sentences) might still be coming. Each
    sentence is held back one slot (`pending`) until the FOLLOWING
    sentence is parsed (confirming the held one wasn't last) or the
    stream ends (confirming it was) — a one-item lookahead, not a
    cumulative buffer.
    """
    import queue  # noqa: PLC0415
    import re  # noqa: PLC0415

    q: queue.Queue[tuple[str, bool] | None] = queue.Queue()
    # Set by whichever side notices the cancel first (watcher or producer).
    aborted = threading.Event()
    # Set when the worker is done, so the watcher thread doesn't outlive the
    # call it belongs to.
    finished = threading.Event()

    # PiperTTS is loaded once and reused for the whole process lifetime, so
    # a stop() from a previous turn's barge-in would otherwise still be
    # latched and silence this reply.
    reset = getattr(tts, "reset", None)
    if callable(reset):
        reset()

    def _cancel_watcher() -> None:
        assert cancel is not None
        while not finished.is_set():
            if cancel.wait(timeout=_CANCEL_POLL_S):
                aborted.set()
                with contextlib.suppress(Exception):
                    tts.stop()
                return

    def _worker() -> None:
        try:
            while True:
                item = q.get()
                if item is None:
                    break
                if aborted.is_set():
                    # Drain without speaking. Can't just break: the producer
                    # may still be putting, and it needs a consumer to avoid
                    # blocking on an unbounded-but-unread queue.
                    continue
                sentence, is_last = item
                if on_sentence is not None:
                    on_sentence(sentence, is_last)
                tts.speak(sentence)
        finally:
            finished.set()

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    watcher: threading.Thread | None = None
    if cancel is not None:
        watcher = threading.Thread(target=_cancel_watcher, daemon=True)
        watcher.start()

    buf = ""
    pending: str | None = None
    for chunk in chunks:
        if cancel is not None and cancel.is_set():
            aborted.set()
            break
        buf += chunk
        # Split on sentence-ending punctuation followed by whitespace
        parts = re.split(r"(?<=[.!?…])\s+", buf)
        for part in parts[:-1]:
            clean = part.strip()
            if clean:
                if pending is not None:
                    q.put((pending, False))
                pending = clean
        buf = parts[-1]

    # On abort, skip the final flush entirely — there's no point marking a
    # last sentence as final when we're not going to speak it.
    if not aborted.is_set():
        if buf.strip():
            # A trailing, punctuation-less remainder is the true final piece —
            # whatever was pending (if anything) is confirmed NOT last.
            if pending is not None:
                q.put((pending, False))
            q.put((buf.strip(), True))
        elif pending is not None:
            # Stream ended exactly on a sentence boundary — the held-back
            # sentence IS the final one after all.
            q.put((pending, True))
    q.put(None)
    t.join()
    finished.set()
    if watcher is not None:
        watcher.join(timeout=1.0)
    return not aborted.is_set()


def make_tts(piper_voice: str, voice_dir: Path, output_device: str | None = None) -> TTS:
    """Choose the best available TTS for this machine."""
    piper_onnx = voice_dir / f"{piper_voice}.onnx"
    if shutil.which("piper") and piper_onnx.exists():
        log.info("tts.backend", backend="piper", voice=piper_voice)
        return PiperTTS(piper_voice, voice_dir, output_device=output_device)
    if platform.system() == "Darwin" and shutil.which("say"):
        log.info("tts.backend", backend="mac-say", reason="piper not configured")
        return MacSayTTS()
    log.warning("tts.backend", backend="print", reason="no usable TTS backend found")
    return _PrintTTS()


class _PrintTTS:
    @property
    def name(self) -> str:
        return "print"

    def speak(self, text: str) -> None:
        print(f"[Lumi]: {text}")

    def stop(self) -> None:
        """Nothing to cut — printing is instantaneous, so there's never an
        in-flight utterance to abort. Present to satisfy the TTS protocol."""

    def reset(self) -> None:
        """No latch to clear (see stop())."""
