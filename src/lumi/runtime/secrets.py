"""Secret storage for Lumi (cloud LLM API keys, future paid-service tokens).

Two backends, chosen automatically:

  1. **OS keychain** (preferred) — via `keyring`, talking to macOS Keychain,
     Linux Secret Service (gnome-keyring / KWallet), or Windows Credential
     Manager. This is what a developer laptop uses.

  2. **0600 file fallback** — on a headless device (e.g. the Pi appliance)
     there is *no* keychain daemon, so `keyring` resolves to its `fail`
     backend. Rather than making cloud features impossible on the shipping
     hardware, we fall back to a `0600` JSON file inside the already-`0700`
     `data_dir`. This matches the reality that OpenClaw *already* needs the
     key in a `0600` file (`~/.openclaw/openclaw.json`) because it can't read
     a keychain either.

     *Design note (revised 2026-07-01):* the earlier invariant was "never
     fall back to plaintext." That held for the laptop, but on the Pi the key
     unavoidably lives in a `0600` file for OpenClaw regardless, so refusing a
     file here only blocked cloud setup without improving real security. On a
     single-user, non-network-shared device the `0600`-in-`0700-dir` file is
     the honest protection; full-disk encryption is the V2 hardening step.

What lives in `user_settings.json` either way: only the *fact* that a secret
is set (a boolean) plus non-sensitive provider/model names — never the secret.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

from ..log import get_logger

log = get_logger(__name__)

_SERVICE = "lumi"
# Filename of the fallback store; also listed in runtime.storage so
# secure_data_dir() tightens it to 0600 on every launch (defence in depth).
SECRETS_FILENAME = ".secrets.json"


class BackendUnavailable(RuntimeError):
    """Raised when neither the keychain nor the file fallback is reachable."""


# ── keychain backend ─────────────────────────────────────────────────────────
def _client() -> object:
    import keyring  # noqa: PLC0415

    return keyring


def _keychain_ok() -> bool:
    """True iff a *real* OS keychain backend is reachable (not null/fail).

    Note: the marker lives in the *module* path (e.g. ``keyring.backends.fail``),
    not the class name (which is just ``Keyring``), so we match the full
    ``module.ClassName``.
    """
    try:
        backend = _client().get_keyring()  # type: ignore[attr-defined]
        ident = f"{type(backend).__module__}.{type(backend).__name__}".lower()
        return "null" not in ident and "fail" not in ident
    except Exception:
        return False


# ── 0600 file fallback ───────────────────────────────────────────────────────
def _secrets_file() -> Path:
    # Resolved from Settings so it tracks LUMI_DATA_DIR / the ./data default.
    from ..config import Settings  # noqa: PLC0415

    return Settings().data_dir / SECRETS_FILENAME


class SecretStoreUnreadable(RuntimeError):
    """The secrets file exists but couldn't be parsed.

    Raised only on the read-modify-write path. Treating an unreadable store as
    empty there is how you silently destroy every other secret — see
    `_file_read`'s `strict` argument.
    """


def _file_read(*, strict: bool = False) -> dict[str, str]:
    """Load the secrets file.

    `strict` distinguishes the two callers, which need opposite behaviour on a
    damaged file:

      * **reads** (`get_secret`) want `strict=False` — a missing key and an
        unreadable store both mean "no value", and raising would take down a
        voice turn over a secret that may not even be configured.
      * **read-modify-write** (`set_secret`/`delete_secret`) MUST use
        `strict=True`. Those do `store = read(); store[k] = v; write(store)`,
        so a read that quietly returns `{}` writes back a store containing
        *only* the new key and erases everything else.

    That is not hypothetical. On the device (2026-08-06) `data/.secrets.json`
    held a single entry named `k` with `cloud_llm_api_key` gone, and the cloud
    LLM had been silently falling back to the local 1.5B model as a result.
    """
    p = _secrets_file()
    if not p.exists():
        return {}          # legitimately empty — safe for both callers
    try:
        raw = p.read_text(encoding="utf-8")
    except OSError as exc:
        if strict:
            raise SecretStoreUnreadable(f"cannot read {p.name}") from exc
        return {}
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except ValueError as exc:
        if strict:
            raise SecretStoreUnreadable(f"{p.name} is not valid JSON") from exc
        return {}
    if not isinstance(data, dict):
        if strict:
            raise SecretStoreUnreadable(f"{p.name} does not contain an object")
        return {}
    return {str(k): str(v) for k, v in data.items()}


@contextlib.contextmanager
def _file_lock() -> Iterator[None]:
    """Serialise read-modify-write across processes.

    Three separate processes touch this file — `lumi-web`, `lumi-voice`, and
    the `lumi keys` CLI. Without a lock, two concurrent `set_secret` calls both
    read the old store, both add their own key, and the second write drops the
    first one's. A classic lost update, and with three long-lived writers it's
    a matter of when rather than whether.

    `flock` on a sidecar file rather than the secrets file itself, so the
    atomic `os.replace` in `_file_write` (which swaps the inode out from under
    any handle) can't invalidate the lock mid-cycle. Best-effort: if flock
    isn't available the operation still proceeds unserialised rather than
    failing, which is the pre-existing behaviour.
    """
    p = _secrets_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    lock_path = p.with_suffix(p.suffix + ".lock")
    try:
        import fcntl  # noqa: PLC0415
    except ImportError:                     # pragma: no cover - non-POSIX
        yield
        return
    fd = None
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    except OSError:                         # pragma: no cover
        yield
    finally:
        if fd is not None:
            with contextlib.suppress(OSError):
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)


def _file_write(store: dict[str, str]) -> None:
    p = _secrets_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=p.name + ".", suffix=".tmp", dir=str(p.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(store))
        os.chmod(tmp, 0o600)
        os.replace(tmp, p)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise


# ── public API (backend-agnostic) ────────────────────────────────────────────
def backend_kind() -> str:
    """'keychain' or 'file' — for UI/CLI to tell the user where the key lives."""
    return "keychain" if _keychain_ok() else "file"


def is_available() -> bool:
    """True iff secrets can be stored. Always true now (file fallback)."""
    return True


def set_secret(key: str, value: str) -> None:
    """Store `value` under (service="lumi", key=key). Empty value deletes it."""
    if not value:
        delete_secret(key)
        return
    if _keychain_ok():
        _client().set_password(_SERVICE, key, value)  # type: ignore[attr-defined]
    else:
        # strict + locked: this is the read-modify-write path, where treating a
        # damaged store as empty would erase every other secret.
        with _file_lock():
            store = _file_read(strict=True)
            store[key] = value
            _file_write(store)
    log.info("secrets.set", key=key, backend=backend_kind())


def get_secret(key: str) -> str:
    """Return the stored secret, or empty string if not set."""
    try:
        if _keychain_ok():
            return _client().get_password(_SERVICE, key) or ""  # type: ignore[attr-defined]
        return _file_read().get(key, "")
    except Exception:
        return ""


def delete_secret(key: str) -> None:
    """Remove the secret. Silent no-op if it didn't exist.

    Deliberately still swallows errors — callers use this for cleanup and
    factory reset, where a failure shouldn't abort the wider operation. But it
    now uses the strict, locked read so a damaged store can't turn "delete one
    key" into "delete everything".
    """
    try:
        if _keychain_ok():
            _client().delete_password(_SERVICE, key)  # type: ignore[attr-defined]
        else:
            with _file_lock():
                store = _file_read(strict=True)
                if key in store:
                    del store[key]
                    _file_write(store)
        log.info("secrets.deleted", key=key)
    except SecretStoreUnreadable:
        log.warning("secrets.delete_skipped_unreadable_store", key=key)
    except Exception:
        pass


def mask(value: str) -> str:
    """Render-safe preview of a secret: "sk-…d4f3" or "(not set)"."""
    if not value:
        return "(not set)"
    if len(value) <= 8:
        return "•" * len(value)
    return f"{value[:4]}…{value[-4:]}"
