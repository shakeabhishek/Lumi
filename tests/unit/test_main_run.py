"""Tests for main.py's `run()` CLI wiring.

Only covers the cloud-routing fix (2026-07-xx) — every other constructor in
`run()` is mocked out here purely so this one code path is reachable without
loading a real Whisper model, opening a real mic, or looping forever.
"""

from __future__ import annotations

import concurrent.futures
import time
from unittest.mock import MagicMock

import pytest

from lumi import main as main_mod


# ── _run_with_timeout ────────────────────────────────────────────────────
#
# Safety-net timeout added 2026-07-05 after a real hang was found on the
# Pi: a wedged Piper/aplay subprocess froze the whole voice loop with
# nothing to recover it. This wraps the two unbounded blocking calls in
# _voice_loop (first LLM chunk, and the whole speak_streaming call) so a
# *future* hang — regardless of cause — can't do the same thing.


def test_run_with_timeout_returns_result_when_fast_enough() -> None:
    result = main_mod._run_with_timeout(lambda x: x * 2, 21, timeout=1.0)
    assert result == 42


def test_run_with_timeout_passes_args_and_kwargs() -> None:
    def fn(a, b, *, c):
        return a + b + c

    result = main_mod._run_with_timeout(fn, 1, 2, c=3, timeout=1.0)
    assert result == 6


def test_run_with_timeout_raises_on_slow_call() -> None:
    def slow():
        time.sleep(5)
        return "too late"

    with pytest.raises(concurrent.futures.TimeoutError):
        main_mod._run_with_timeout(slow, timeout=0.05)


def test_run_with_timeout_does_not_block_on_shutdown() -> None:
    """Regression guard: a naive `with ThreadPoolExecutor() as pool:` would
    have pool.shutdown(wait=True) run on exit, blocking until the timed-out
    (still-running) thread finishes — defeating the entire point of the
    timeout. Assert the call returns promptly even though the background
    thread is still sleeping well past the timeout."""
    def slow():
        time.sleep(2)

    t0 = time.monotonic()
    with pytest.raises(concurrent.futures.TimeoutError):
        main_mod._run_with_timeout(slow, timeout=0.05)
    elapsed = time.monotonic() - t0
    assert elapsed < 1.0, f"expected prompt return, took {elapsed:.2f}s"


def test_run_with_timeout_propagates_exception_from_call() -> None:
    def boom():
        raise ValueError("real failure")

    with pytest.raises(ValueError, match="real failure"):
        main_mod._run_with_timeout(boom, timeout=1.0)


def test_run_passes_user_settings_to_make_llm_backend(tmp_path, monkeypatch) -> None:
    """Regression test: `make_llm_backend(cfg)` alone (no user_settings)
    meant the voice loop never got RoutedBackend's cloud escalation even
    with cloud routing enabled in /settings/cloud — only OpenClaw skills
    did, via build_cloud_bridge. Locks in the fix: user_settings must be
    hoisted above and passed into make_llm_backend."""
    fake_user = MagicMock(name="user_settings")

    # Both of these are imported LOCALLY inside run() (`from X import Y`,
    # fetched fresh at call time) — patch at the source module, not
    # lumi.main, or the patch won't take effect.
    monkeypatch.setattr("lumi.ui.web.persistence.load_settings", lambda data_dir: fake_user)
    monkeypatch.setattr(
        "lumi.runtime.session.build_cloud_bridge",
        lambda user, *, openclaw_enabled: (None, None, "ollama"),
    )

    captured: dict[str, object] = {}

    def _fake_make_llm_backend(cfg, *, user_settings=None):
        captured["user_settings"] = user_settings
        return MagicMock(name="llm_backend")

    monkeypatch.setattr(main_mod, "make_llm_backend", _fake_make_llm_backend)
    monkeypatch.setattr(main_mod, "SoundDeviceInput", MagicMock())
    monkeypatch.setattr(main_mod, "VoiceID", MagicMock())
    monkeypatch.setattr(main_mod, "WhisperSTT", MagicMock())
    fake_memory_store = MagicMock(is_available=MagicMock(return_value=False))
    monkeypatch.setattr(main_mod, "MemoryStore", fake_memory_store)
    monkeypatch.setattr(main_mod, "AuditLog", MagicMock())
    monkeypatch.setattr(main_mod, "ConversationManager", MagicMock())
    monkeypatch.setattr(main_mod, "make_tts", MagicMock())
    monkeypatch.setattr(main_mod, "_make_wake_source", MagicMock())
    monkeypatch.setattr(main_mod, "SkillRouter", MagicMock())
    monkeypatch.setattr(main_mod, "PerfLog", MagicMock())
    monkeypatch.setattr(main_mod, "StateMachine", MagicMock())
    monkeypatch.setattr(main_mod, "secure_data_dir", MagicMock())

    def _fake_voice_loop(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(main_mod, "_voice_loop", _fake_voice_loop)

    cfg = main_mod.get_settings().model_copy(update={"data_dir": tmp_path})
    monkeypatch.setattr(main_mod, "get_settings", lambda: cfg)

    with pytest.raises(SystemExit):
        main_mod.run(log_level="INFO", backend="mock", mode="", list_devices=False, enroll=False)

    assert captured["user_settings"] is fake_user
