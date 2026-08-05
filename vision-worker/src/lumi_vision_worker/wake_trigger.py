"""Writes the cross-process trigger files the main app polls for:

  - `data_dir/.wake_trigger.json` — wake Lumi. Consumed by FileTriggerWake
    (src/lumi/audio/wake_word.py). Written on a wave gesture.
  - `data_dir/.barge_in.json` — interrupt Lumi mid-reply. Consumed by
    BargeInWatcher (src/lumi/runtime/barge_in.py). Written on an open palm.

Bare filesystem writes, no HTTP hop — both keep working even if the main
app's web server is down, since neither depends on it at all (see the
plan's systemd unit note on this same point). It's also the only channel
available: the voice loop is a *third* process (`lumi-voice`), separate
from both this worker and `lumi-web`, so an HTTP push to the web app
couldn't reach it regardless.

The worker deliberately does NOT know whether Lumi is currently speaking —
it writes an open-palm trigger every time it sees one, and the main app
decides whether that's meaningful right now (BargeInWatcher only polls
during the SPEAK phase). Keeping the state machine on one side of the
process boundary is what lets this stay a one-way, fire-and-forget write.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

_WAKE_FILE = ".wake_trigger.json"
_BARGE_IN_FILE = ".barge_in.json"


def _write_trigger(data_dir: Path, filename: str, source: str) -> None:
    """Atomic write (temp file + os.replace) so the reader's poll never sees
    a half-written file — same pattern the main app's own
    persistence.py:_atomic_write_text uses for user_settings.json."""
    path = data_dir / filename
    payload = {"source": source, "ts": datetime.now(UTC).isoformat()}
    fd, tmp = tempfile.mkstemp(prefix=f"{filename}.", suffix=".tmp", dir=str(data_dir))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(payload))
        os.replace(tmp, path)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise


def write_wake_trigger(data_dir: Path, source: str) -> None:
    """Wake Lumi. Only a wave gesture writes this (user decision,
    2026-07-06) — presence never does."""
    _write_trigger(data_dir, _WAKE_FILE, source)


def write_barge_in_trigger(data_dir: Path, source: str) -> None:
    """Interrupt an in-flight reply. Written on every open palm regardless
    of what Lumi is doing; the main app ignores it unless she's speaking."""
    _write_trigger(data_dir, _BARGE_IN_FILE, source)
