"""Writes data_dir/.wake_trigger.json — the cross-process wake channel
consumed by the main app's FileTriggerWake (src/lumi/audio/wake_word.py).

Bare filesystem write, no HTTP hop — gesture-triggered wake keeps working
even if the main app's web server is down, since this doesn't depend on
it at all (see the plan's systemd unit note on this same point).
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path


def write_wake_trigger(data_dir: Path, source: str) -> None:
    """Atomic write (temp file + os.replace) so FileTriggerWake's poll
    never reads a half-written file — same pattern the main app's own
    persistence.py:_atomic_write_text uses for user_settings.json."""
    path = data_dir / ".wake_trigger.json"
    payload = {"source": source, "ts": datetime.now(UTC).isoformat()}
    fd, tmp = tempfile.mkstemp(prefix=".wake_trigger.", suffix=".tmp", dir=str(data_dir))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(payload))
        os.replace(tmp, path)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise
