"""On-disk storage hardening.

Lumi's data_dir collects everything sensitive: conversation embeddings,
audit log, voice embedding, pending hotkey context, cached settings,
and the OpenClaw provider config that mirrors a plaintext API key.

By default, mkdir() uses the user's umask (typically 022 → 0755 on the
created directory). On a shared workstation that means other local users
can read everything. We tighten to 0700 (owner read/write/execute only)
on first creation, AND on every subsequent startup so the invariant
holds for installs that started under the old behaviour.

This is at-rest hardening. The privacy promise was always "your data
stays on the device"; this makes it accurate for "the device" =
your-user-account-only, not "anyone with shell access."
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

from ..log import get_logger

log = get_logger(__name__)

_DIR_MODE = stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR        # 0700
_FILE_MODE = stat.S_IRUSR | stat.S_IWUSR                        # 0600

# Files we care enough about to lock down explicitly. Everything else in
# the data_dir inherits the directory's 0700 (since it's not traversable
# by other users anyway, the file mode is belt-and-braces).
_SENSITIVE_FILE_NAMES: tuple[str, ...] = (
    "user_settings.json",
    "audit_log.jsonl",
    "owner_embedding.npy",
    ".pending_context.json",
    "perf_log.jsonl",
    "notes.jsonl",
    "journal.jsonl",
)


def secure_data_dir(data_dir: Path) -> None:
    """Create `data_dir` with 0700 perms (and tighten if it already exists).

    Idempotent. Logs once if anything changed; silent if everything was
    already correct."""
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        current = data_dir.stat().st_mode & 0o777
        if current != _DIR_MODE:
            os.chmod(data_dir, _DIR_MODE)
            log.info("storage.data_dir_perms_tightened", old=oct(current))

        # Per-file lockdown for the canonical sensitive files. Glob for
        # anything matching the sprite/sound-pack uploads pattern too.
        for name in _SENSITIVE_FILE_NAMES:
            p = data_dir / name
            if p.exists():
                _tighten_file(p)
    except OSError as exc:
        log.warning("storage.secure_failed", error=str(exc))


def _tighten_file(path: Path) -> None:
    try:
        mode = path.stat().st_mode & 0o777
        if mode != _FILE_MODE:
            os.chmod(path, _FILE_MODE)
    except OSError:
        pass
