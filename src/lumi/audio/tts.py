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
    Piper streams audio to stdout; we pipe it through `aplay`/`afplay` to play.
    """

    def __init__(self, voice: str, voice_dir: Path) -> None:
        self._voice = voice
        self._voice_dir = voice_dir
        self._model_path = voice_dir / f"{voice}.onnx"

    @property
    def name(self) -> str:
        return f"piper:{self._voice}"

    def _player_cmd(self) -> list[str]:
        # Cheap audio sink that reads raw PCM 22050Hz mono s16 from stdin.
        if platform.system() == "Darwin":
            # macOS doesn't ship aplay; use sox if present, else fall back to ffplay.
            if shutil.which("sox"):
                return ["sox", "-t", "raw", "-r", "22050", "-e", "signed", "-b", "16",
                        "-c", "1", "-", "-d"]
            if shutil.which("ffplay"):
                return ["ffplay", "-autoexit", "-nodisp", "-f", "s16le",
                        "-ar", "22050", "-ac", "1", "-"]
        return ["aplay", "-r", "22050", "-f", "S16_LE", "-t", "raw"]

    def speak(self, text: str) -> None:
        if not text:
            return
        if not self._model_path.exists():
            raise FileNotFoundError(
                f"Piper voice not found: {self._model_path}. "
                "Download from https://github.com/rhasspy/piper/releases."
            )
        piper = subprocess.Popen(
            ["piper", "--model", str(self._model_path), "--output-raw"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
        )
        player = subprocess.Popen(self._player_cmd(), stdin=piper.stdout)
        assert piper.stdin is not None
        piper.stdin.write(text.encode("utf-8"))
        piper.stdin.close()
        player.wait()
        piper.wait()


def speak_streaming(
    tts: TTS, chunks: Iterator[str], *, on_sentence: Callable[[str, bool], None] | None = None,
) -> None:  # noqa: F811
    """Buffer an LLM token stream into sentences and speak each as it completes.

    Runs TTS in a background thread so audio plays while the LLM continues
    generating the next sentence — significantly reduces perceived latency.

    `on_sentence`, if given, is called once per sentence boundary — the same
    moment it's queued for TTS — with `(sentence_text, is_last_sentence)`.
    Deliberately just the ONE sentence, not the cumulative reply so far: an
    earlier cumulative design made the voice loop's live caption grow to
    contain the entire reply, which for a multi-sentence answer ate up the
    whole screen instead of reading like live captions (found in real use,
    2026-07-02). `is_last_sentence=True` on the final call lets the caller
    mark that turn's caption as complete without a separate full-text push.
    """
    import queue  # noqa: PLC0415
    import re  # noqa: PLC0415
    import threading  # noqa: PLC0415

    q: queue.Queue[str | None] = queue.Queue()

    def _worker() -> None:
        while True:
            sentence = q.get()
            if sentence is None:
                break
            tts.speak(sentence)

    t = threading.Thread(target=_worker, daemon=True)
    t.start()

    buf = ""
    last_sentence = ""
    for chunk in chunks:
        buf += chunk
        # Split on sentence-ending punctuation followed by whitespace
        parts = re.split(r"(?<=[.!?…])\s+", buf)
        for part in parts[:-1]:
            clean = part.strip()
            if clean:
                q.put(clean)
                last_sentence = clean
                if on_sentence is not None:
                    on_sentence(clean, False)
        buf = parts[-1]

    if buf.strip():
        clean = buf.strip()
        q.put(clean)
        last_sentence = clean
        if on_sentence is not None:
            on_sentence(clean, True)
    elif on_sentence is not None and last_sentence:
        # Stream ended exactly on a sentence boundary — the last real
        # sentence already fired with is_last_sentence=False above.
        # Re-fire the SAME text marked final so the caller still gets a
        # definitive "this turn's caption is complete" signal.
        on_sentence(last_sentence, True)
    q.put(None)
    t.join()


def make_tts(piper_voice: str, voice_dir: Path) -> TTS:
    """Choose the best available TTS for this machine."""
    piper_onnx = voice_dir / f"{piper_voice}.onnx"
    if shutil.which("piper") and piper_onnx.exists():
        log.info("tts.backend", backend="piper", voice=piper_voice)
        return PiperTTS(piper_voice, voice_dir)
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
