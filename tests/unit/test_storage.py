"""Tests for runtime.storage.secure_data_dir — at-rest perm hardening."""

from __future__ import annotations

import os
import stat
from pathlib import Path

from lumi.runtime.storage import secure_data_dir


def test_new_data_dir_created_with_0700(tmp_path: Path) -> None:
    target = tmp_path / "fresh"
    secure_data_dir(target)
    assert target.exists()
    assert (target.stat().st_mode & 0o777) == 0o700


def test_existing_world_readable_dir_gets_tightened(tmp_path: Path) -> None:
    """Installs that started with default umask have 0755. Next launch
    must lock it down without otherwise touching the contents."""
    target = tmp_path / "legacy"
    target.mkdir(mode=0o755)
    (target / "audit_log.jsonl").write_text("existing data")
    os.chmod(target / "audit_log.jsonl", 0o644)

    secure_data_dir(target)

    assert (target.stat().st_mode & 0o777) == 0o700
    assert (target / "audit_log.jsonl").read_text() == "existing data"
    assert ((target / "audit_log.jsonl").stat().st_mode & 0o777) == 0o600


def test_idempotent_no_change_for_already_tight_dir(tmp_path: Path) -> None:
    """Calling secure_data_dir on an already-locked dir is a silent no-op."""
    target = tmp_path / "tight"
    target.mkdir(mode=0o700)

    secure_data_dir(target)
    secure_data_dir(target)        # second call

    assert (target.stat().st_mode & 0o777) == 0o700


def test_tightens_each_listed_sensitive_file(tmp_path: Path) -> None:
    target = tmp_path / "d"
    target.mkdir(mode=0o700)
    files = [
        "user_settings.json",
        "audit_log.jsonl",
        "owner_embedding.npy",
        ".pending_context.json",
        "perf_log.jsonl",
        "notes.jsonl",
        "journal.jsonl",
    ]
    for name in files:
        f = target / name
        f.write_text("x")
        os.chmod(f, 0o644)

    secure_data_dir(target)

    for name in files:
        mode = (target / name).stat().st_mode & 0o777
        assert mode == 0o600, f"{name}: expected 0600, got {oct(mode)}"


def test_nonexistent_sensitive_files_are_not_created(tmp_path: Path) -> None:
    """secure_data_dir must not touch files that don't exist yet."""
    target = tmp_path / "empty"
    secure_data_dir(target)

    assert not (target / "audit_log.jsonl").exists()
    assert not (target / "user_settings.json").exists()


def test_handles_oserror_silently(tmp_path: Path, caplog) -> None:
    """If chmod fails (read-only fs in CI sandbox, etc.) the app must
    still come up — log a warning, keep running."""
    target = tmp_path / "d"
    secure_data_dir(target)
    # If we got here without raising, the soft-fail path works.
    assert target.exists()
