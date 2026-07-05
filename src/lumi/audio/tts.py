"""Text-to-speech.

Two backends:
- `PiperTTS`: neural TTS. What ships on the Pi. Needs a voice ONNX downloaded.
- `MacSayTTS`: shells out to macOS's built-in `say` command. Zero-setup on dev
  laptops — useful so the voice loop works the moment the project is cloned,
  before anyone downloads Piper voices.

The runtime depends on the `TTS` protocol, not either implementation.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Protocol

from ..log import get_logger

log = get_logger(__name__)


class TTS(Protocol):
    def speak(self, text: str) -> None:
        """Block until the text has been spoken."""

    @property
    def name(self) -> str: ...


class MacSayTTS:
    """macOS `say` command. Voice picked to match Lumi's warm/calm brand."""

    def __init__(self, voice: str = "Ava", rate: int = 180) -> None:
        self._voice = voice
        self._rate = rate

    @property
    def name(self) -> str:
        return f"mac-say:{self._voice}"

    def speak(self, text: str) -> None:
        if not text:
            return
        try:
            subprocess.run(
                ["say", "-v", self._voice, "-r", str(self._rate), text],
                check=True,
            )
        except FileNotFoundError:
            log.warning("`say` not available; falling back to print")
            print(f"[Lumi]: {text}")


class PiperTTS:
    """Piper neural TTS via the `piper` CLI.

    Voice ONNX + JSON must live at `voice_dir / voice_name.onnx{,.json}`.
    Piper streams raw 22050Hz mono s16 PCM to stdout; played back via
    `sounddevice` — the SAME library `hardware/audio_io.py` uses for mic
    capture — rather than piping into a separate `aplay`/`sox`/`ffplay`
    process.

    This used to shell out to `aplay`. Found on the Pi (2026-07-05, real
    hardware): after ANY prior sounddevice/PortAudio capture in the same
    process (i.e. every single turn, since mic.record() always runs
    first), the next `aplay` invocation failed with "audio open error" —
    reproduced in isolation with no wake-word code involved, so it's a
    PortAudio-vs-separate-ALSA-CLI-process conflict over the same
    hardware, not a wake-word-specific bug. Worse, Piper's own process
    then hung waiting on the wedged player, freezing the whole voice loop
    until manually killed. Routing playback through the same PortAudio
    abstraction as capture avoids the cross-library device-handle fight
    entirely — and simplifies the code, since the platform-specific
    aplay/sox/ffplay selection is no longer needed at all.
    """

    _SAMPLE_RATE = 22050
    _TARGET_RMS = 0.55

    def __init__(self, voice: str, voice_dir: Path, output_device: str | None = None) -> None:
        self._voice = voice
        self._voice_dir = voice_dir
        self._model_path = voice_dir / f"{voice}.onnx"
        self._output_device = output_device

    @property
    def name(self) -> str:
        return f"piper:{self._voice}"

    @classmethod
    def _boost_loudness(cls, samples: "np.ndarray") -> "np.ndarray":
        """Boost quiet speech up to a target average loudness, softly
        saturating any peaks that overflow instead of hard-clipping them.

        Found on the Pi (2026-07-05): even at 100% hardware volume, Piper's
        speech sounded "very low" — measured its peak amplitude was already
        at full scale (1.0) but RMS (average loudness) only ~0.15, vs. a
        test tone's ~0.64 (which the user confirmed was clearly audible at
        max volume). Normal for speech (quiet vowels, loud consonant peaks
        — high dynamic range) but it means hardware gain alone can't help
        further: the peaks are already maxed, so more gain just clips them
        without raising perceived loudness.

        First pass used a hard np.clip at a more conservative target
        (0.35) and still sounded "very low" — 0.35 RMS is meaningfully
        quieter than the tone's 0.64 that was confirmed audible. Raised
        the target to 0.55 (closer to that confirmed-audible level) and
        switched from a hard clip to tanh-based soft saturation: at this
        more aggressive gain, a lot of peaks now exceed [-1, 1], and a
        hard clip on that many samples would sound noticeably crunchy/
        distorted. tanh rounds over the loudest peaks smoothly (like
        analog tape saturation) instead of slamming them flat, while
        barely touching quiet samples (tanh(x) ≈ x for small x) — louder
        overall with less harshness than a hard clip at the same gain.
        """
        import numpy as np  # noqa: PLC0415

        rms = float(np.sqrt(np.mean(samples**2)))
        if rms < 1e-6:
            return samples
        gain = cls._TARGET_RMS / rms
        return np.tanh(samples * gain).astype(np.float32)

    def speak(self, text: str) -> None:
        if not text:
            return
        if not self._model_path.exists():
            raise FileNotFoundError(
                f"Piper voice not found: {self._model_path}. "
                "Download from https://github.com/rhasspy/piper/releases."
            )
        import numpy as np  # noqa: PLC0415
        import sounddevice as sd  # noqa: PLC0415

        piper = subprocess.Popen(
            ["piper", "--model", str(self._model_path), "--output-raw"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
        )
        raw_pcm, _stderr = piper.communicate(input=text.encode("utf-8"))
        if not raw_pcm:
            return
        # Piper's --output-raw is signed 16-bit PCM. Normalize to the
        # [-1, 1] float32 range sounddevice expects — a naive .astype
        # would reinterpret e.g. 32767 as 32767.0 instead of ~1.0,
        # producing garbage/clipped audio.
        samples = np.frombuffer(raw_pcm, dtype=np.int16).astype(np.float32) / 32768.0
        samples = self._boost_loudness(samples)
        sd.play(samples, samplerate=self._SAMPLE_RATE, device=self._output_device)
        sd.wait()


def speak_streaming(
    tts: TTS, chunks: Iterator[str], *, on_sentence: Callable[[str, bool], None] | None = None,
) -> None:  # noqa: F811
    """Buffer an LLM token stream into sentences and speak each as it completes.

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
    import threading  # noqa: PLC0415

    q: queue.Queue[tuple[str, bool] | None] = queue.Queue()

    def _worker() -> None:
        while True:
            item = q.get()
            if item is None:
                break
            sentence, is_last = item
            if on_sentence is not None:
                on_sentence(sentence, is_last)
            tts.speak(sentence)

    t = threading.Thread(target=_worker, daemon=True)
    t.start()

    buf = ""
    pending: str | None = None
    for chunk in chunks:
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
