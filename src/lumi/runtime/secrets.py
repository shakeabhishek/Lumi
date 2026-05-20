"""OS-native secret storage for Lumi.

API keys (cloud LLM providers, future paid services) NEVER touch disk in
plaintext. We delegate to `keyring`, which talks to:
  - macOS Keychain
  - Linux Secret Service (gnome-keyring / KWallet)
  - Windows Credential Manager

What lives in `user_settings.json` (the file under the gitignored data/ dir):
  - The fact that a secret has been set (a boolean flag)
  - Provider name + model name — non-sensitive
  - NOT the secret itself

What lives in the OS keychain:
  - The actual API key string, under service name "lumi" and key name like
    "cloud_llm_api_key".

If `keyring` isn't installed or there's no backend (rare; happens in CI),
`SecretStore` raises BackendUnavailable and the calling code shows the
user a clear message — we deliberately do NOT fall back to plaintext.
"""

from __future__ import annotations

from ..log import get_logger

log = get_logger(__name__)

_SERVICE = "lumi"


class BackendUnavailable(RuntimeError):
    """Raised when no OS keyring backend is reachable."""


def _client() -> object:
    try:
        import keyring  # noqa: PLC0415
    except ImportError as exc:
        raise BackendUnavailable(
            "the `keyring` package is not installed — run "
            "`uv pip install -e '.[secrets]'`"
        ) from exc
    return keyring


def is_available() -> bool:
    """Lightweight probe — returns True iff a real backend is reachable."""
    try:
        kr = _client()
        backend = kr.get_keyring()  # type: ignore[attr-defined]
        # Reject the "null" backend (no real OS store) and the "fail" backend.
        name = type(backend).__name__.lower()
        return "null" not in name and "fail" not in name
    except Exception:
        return False


def set_secret(key: str, value: str) -> None:
    """Store `value` under (service="lumi", key=key) in the OS keychain.

    Empty values delete the secret — useful for clearing a key from the UI.
    """
    kr = _client()
    if not value:
        delete_secret(key)
        return
    kr.set_password(_SERVICE, key, value)  # type: ignore[attr-defined]
    log.info("secrets.set", key=key)


def get_secret(key: str) -> str:
    """Return the stored secret, or empty string if not set."""
    try:
        kr = _client()
        return kr.get_password(_SERVICE, key) or ""  # type: ignore[attr-defined]
    except BackendUnavailable:
        return ""


def delete_secret(key: str) -> None:
    """Remove the secret. Silent no-op if it didn't exist."""
    try:
        kr = _client()
        kr.delete_password(_SERVICE, key)  # type: ignore[attr-defined]
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
