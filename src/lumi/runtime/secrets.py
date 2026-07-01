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

import json
import os
import tempfile
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


def _file_read() -> dict[str, str]:
    p = _secrets_file()
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except Exception:
        return {}


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
        store = _file_read()
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
    """Remove the secret. Silent no-op if it didn't exist."""
    try:
        if _keychain_ok():
            _client().delete_password(_SERVICE, key)  # type: ignore[attr-defined]
        else:
            store = _file_read()
            if key in store:
                del store[key]
                _file_write(store)
        log.info("secrets.deleted", key=key)
    except Exception:
        pass


def mask(value: str) -> str:
    """Render-safe preview of a secret: "sk-…d4f3" or "(not set)"."""
    if not value:
        return "(not set)"
    if len(value) <= 8:
        return "•" * len(value)
    return f"{value[:4]}…{value[-4:]}"
