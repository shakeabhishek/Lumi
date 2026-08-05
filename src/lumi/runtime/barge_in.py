"""Barge-in: letting the user cut Lumi off mid-reply.

Until 2026-08-05 there was no way to stop Lumi speaking by any means. Of the
four cancel surfaces the V1 input model promises, none worked: the wake
source is stopped for the duration of a turn (mic-stream conflict), the
ReSpeaker button was never wired past MockGPIO, and open palm / thumbs-down
were classified, badged, and then dropped. A long reply played to completion
no matter what the user did — on a voice-first device with no hardware AEC,
the most-felt flaw in daily use.

This module is the consumer side. Triggers arrive as a file drop at
`data_dir/.barge_in.json`, written by whichever process saw the interrupt:

  - the vision-worker on an open palm
    (`vision-worker/src/lumi_vision_worker/wake_trigger.py`)
  - anything else that wants to interrupt — the ReSpeaker button handler
    lands here too, rather than reaching into the voice loop's threads.

A file rather than HTTP because the voice loop is its own process
(`lumi-voice`), separate from both the vision worker and `lumi-web`, so an
HTTP push to the web app can't reach it. Same reasoning and same shape as
the wave-gesture wake path (`FileTriggerWake` in audio/wake_word.py), which
this deliberately mirrors — one cross-process idiom, not two.

Armed only around the SPEAK phase, for two reasons. It keeps the poll off
the CPU while idle, and more importantly "interrupt" is meaningless when
there's nothing to interrupt: an open palm at idle should not silently arm a
trap that kills the *next* reply before it starts.
"""

from __future__ import annotations

import contextlib
import json
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

from ..log import get_logger

log = get_logger(__name__)

# Faster than FileTriggerWake's 0.15s. Wake has no tight latency budget (a
# wave takes the user most of a second to perform), but barge-in is judged
# on feeling instant — the user is already talking over her. 20 stats/sec,
# and only while she's actually speaking.
_POLL_S = 0.05

# Much tighter than the wake path's 5s. A barge-in is only meaningful
# against the utterance it was aimed at; a palm from even a couple of
# seconds ago probably targeted the previous sentence, which has already
# finished playing.
_MAX_TRIGGER_AGE_S = 1.5


class BargeInWatcher:
    """Watches for interrupt triggers and exposes them as a threading.Event
    that `audio/tts.py:speak_streaming(cancel=...)` consumes.

    One instance per voice loop, armed and disarmed around each reply:

        watcher = BargeInWatcher(cfg.data_dir)
        cancel = watcher.arm()
        completed = speak_streaming(tts, chunks, cancel=cancel)
        watcher.disarm()
    """

    def __init__(self, data_dir: Path, poll_s: float = _POLL_S) -> None:
        self._path = data_dir / ".barge_in.json"
        self._poll_s = poll_s
        self._event = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._source: str | None = None

    @property
    def source(self) -> str | None:
        """What triggered the last barge-in ('gesture:open_palm',
        'button', ...), for the audit log. None if it wasn't triggered."""
        return self._source

    def arm(self) -> threading.Event:
        """Start watching; returns the Event to hand to speak_streaming.

        Discards any trigger already on disk first. Without that, an open
        palm from before the reply started — say, while Lumi was still
        thinking — would fire the instant she opened her mouth, which reads
        as "she refuses to speak" rather than "I interrupted her."
        """
        self._event.clear()
        self._source = None
        self._discard_stale()
        self._stop.clear()
        if self._thread is None:
            self._thread = threading.Thread(target=self._poll_loop, daemon=True)
            self._thread.start()
        return self._event

    def disarm(self) -> None:
        """Stop watching. Same rebuild-on-next-arm idiom as
        OpenWakeWordWake.stop() / FileTriggerWake.stop()."""
        self._stop.set()
        self._thread = None

    def _discard_stale(self) -> None:
        with contextlib.suppress(OSError):
            self._path.unlink(missing_ok=True)

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
            source = str(payload.get("source", "unknown"))
            ts = datetime.fromisoformat(payload.get("ts", ""))
            age = (datetime.now(UTC) - ts).total_seconds()
            if age > _MAX_TRIGGER_AGE_S:
                log.info("barge_in.trigger_stale", age_s=round(age, 2), source=source)
                return
            log.info("barge_in.triggered", source=source)
            self._source = source
            self._event.set()
        except (OSError, ValueError, json.JSONDecodeError):
            # Same tolerance as FileTriggerWake: a half-written or corrupt
            # trigger is dropped, and the next one self-heals. Never let a
            # bad file take down the voice loop.
            pass


def request_barge_in(data_dir: Path, source: str) -> None:
    """Write a barge-in trigger from inside the main app's process tree —
    used by the ReSpeaker button handler. The vision-worker has its own copy
    (it can't import this package: MediaPipe needs protobuf 4.x, chromadb
    needs 7.x), so if this payload shape changes, change
    `vision-worker/src/lumi_vision_worker/wake_trigger.py` with it.
    """
    import os  # noqa: PLC0415
    import tempfile  # noqa: PLC0415

    path = data_dir / ".barge_in.json"
    payload = {"source": source, "ts": datetime.now(UTC).isoformat()}
    fd, tmp = tempfile.mkstemp(prefix=".barge_in.", suffix=".tmp", dir=str(data_dir))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(payload))
        os.replace(tmp, path)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise
