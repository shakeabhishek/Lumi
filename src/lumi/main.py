"""Lumi — CLI entry point.

Subcommands:
  lumi run                          # voice loop (push-to-talk, Ollama backend)
  lumi run --backend mock           # no Ollama needed; great for first-run testing
  lumi run --mode code              # start in developer mode
  lumi run --enroll                 # record voice enrollment clips and exit
  lumi run --list-devices           # show available audio devices and exit
  lumi web                          # FastAPI dashboard at http://localhost:8080
  lumi hotkey                       # global send-to-Lumi hotkey daemon
  LUMI_LOG_LEVEL=DEBUG lumi run     # verbose logs
"""

from __future__ import annotations

import sys

import typer

from .audio.stt import WhisperSTT
from .audio.tts import TTS, make_tts, speak_streaming
from .audio.voice_id import VoiceID
from .audio.wake_word import PushToTalkWake, WakeSource
from .config import LLMBackendName, Mode, Settings, WakeStrategy, get_settings
from .hardware.audio_io import SoundDeviceInput
from .hardware.display import make_display
from .host_helper.send_to_lumi import consume_pending, format_hint
from .llm import make_llm_backend
from .log import configure_logging, get_logger
from .runtime.conversation import ConversationManager
from .runtime.memory import MemoryStore
from .runtime.perf import PerfLog, PipelineTimer
from .runtime.state_machine import LumiState, StateMachine
from .skills import AuditLog, OpenClawBridge, SkillRouter
from .ui.face.engine import FaceEngine

app = typer.Typer(name="lumi", add_completion=False, pretty_exceptions_enable=False)
log = get_logger(__name__)


def _make_wake_source(cfg: Settings) -> WakeSource:
    if cfg.wake == WakeStrategy.PUSH_TO_TALK:
        return PushToTalkWake()
    if cfg.wake == WakeStrategy.WAKE_WORD:
        from .audio.wake_word import OpenWakeWordWake  # noqa: PLC0415

        return OpenWakeWordWake(
            model=cfg.wake_word_model,
            threshold=cfg.wake_word_threshold,
            input_device=cfg.audio_input_device,
        )
    raise NotImplementedError(f"Wake strategy not yet implemented: {cfg.wake}")


def _enroll_voice(cfg: Settings, mic: SoundDeviceInput, voice_id: VoiceID) -> None:
    typer.echo("Voice enrollment: recording 3 clips of 5 seconds each.")
    clips = []
    for i in range(3):
        typer.echo(f"  Clip {i + 1}/3 — speak now...")
        clips.append(mic.record(5.0))
    voice_id.enroll(clips, cfg.audio_sample_rate)
    typer.echo("Enrollment saved. Set LUMI_VOICE_ID_ENABLED=true to activate verification.")


def _get_active_window_context(cfg: Settings) -> str:
    """Return a short context string about the foreground window, or '' if disabled/failed."""
    if not cfg.active_window_enabled:
        return ""
    try:
        from .host_helper import active_window  # noqa: PLC0415

        w = active_window.get()
        return str(w) if w else ""
    except Exception:
        return ""


def _voice_loop(
    cfg: Settings,
    wake: WakeSource,
    mic: SoundDeviceInput,
    stt: WhisperSTT,
    router: SkillRouter,
    tts: TTS,
    voice_id: VoiceID,
    conversation: ConversationManager,
    sm: StateMachine,
    face: FaceEngine,
    perf_log: PerfLog,
) -> None:
    typer.echo(
        f"Lumi is ready.  backend={cfg.llm_backend.value}  mode={cfg.mode.value}  "
        f"record={cfg.audio_record_duration_s}s  "
        f"openclaw={'on' if cfg.openclaw_enabled else 'off'}  "
        f"memory={'on' if cfg.memory_enabled else 'off'}  "
        f"voice_id={'on' if cfg.voice_id_enabled else 'off'}  "
        f"clipboard={'on' if cfg.clipboard_enabled else 'off'}  "
        f"active_window={'on' if cfg.active_window_enabled else 'off'}"
    )
    log.info(
        "lumi.ready",
        wake=cfg.wake.value,
        mode=cfg.mode.value,
        llm=cfg.llm_backend.value,
    )

    while True:
        sm.transition(LumiState.IDLE)
        face.show()
        wake.wait_for_wake()

        timer = PipelineTimer()

        sm.transition(LumiState.LISTEN)
        face.show()

        # --- Failure mode: audio device disconnect ---
        try:
            audio = mic.record(cfg.audio_record_duration_s)
        except Exception as exc:
            log.warning("mic.error", error=str(exc))
            typer.echo("(mic error — check your audio device)", err=True)
            continue

        if cfg.voice_id_enabled and not voice_id.is_owner(audio, cfg.audio_sample_rate):
            log.info("voice_id.rejected")
            continue

        # --- Failure mode: STT crash ---
        try:
            text = stt.transcribe(audio, cfg.audio_sample_rate)
        except Exception as exc:
            log.warning("stt.error", error=str(exc))
            typer.echo("(transcription failed — try again)", err=True)
            continue

        timer.mark("stt_ms")

        if not text:
            typer.echo("(silence or noise — try again)")
            log.info("stt.silence")
            continue

        typer.echo(f"You:  {text}")

        window_ctx = _get_active_window_context(cfg)
        if window_ctx:
            conversation.set_context_hint(f"User's active window: {window_ctx}")
            log.info("context.active_window", window=window_ctx)

        # Hotkey-injected context ("Send to Lumi"). Replaces any earlier hint
        # for this turn — the explicit user action wins over the implicit
        # active-window grab.
        pending = consume_pending(cfg.data_dir) if cfg.clipboard_enabled else None
        if pending:
            conversation.set_context_hint(format_hint(pending))
            log.info("context.hotkey", source=pending.get("source"), chars=len(pending.get("text", "")))

        sm.transition(LumiState.THINK)
        face.show()

        # --- Streaming LLM → TTS ---
        try:
            chunks = router.handle_streaming(text)
            # Collect first chunk to detect errors early before TTS starts
            first = next(iter(chunks), None)
            if first is None:
                reply_text = "Sorry, I didn't get a response."
                tts.speak(reply_text)
            else:
                timer.mark("router_ms")
                typer.echo("Lumi: ", nl=False)
                sm.transition(LumiState.SPEAK)
                face.show()

                def _echo_and_stream() -> Iterator[str]:
                    yield first
                    for chunk in chunks:
                        yield chunk

                collected: list[str] = []

                def _collecting_chunks() -> Iterator[str]:
                    for chunk in _echo_and_stream():
                        collected.append(chunk)
                        typer.echo(chunk, nl=False)
                        yield chunk

                # --- Failure mode: TTS crash ---
                try:
                    speak_streaming(tts, _collecting_chunks())
                except Exception as exc:
                    log.warning("tts.error", error=str(exc))
                reply_text = "".join(collected)
                typer.echo("")  # newline after streamed output
        except Exception as exc:
            log.error("router.error", error=str(exc))
            reply_text = "Sorry, something went wrong. Please try again."
            typer.echo(f"Lumi: {reply_text}")
            typer.echo(f"[error: {exc}]", err=True)
            sm.transition(LumiState.SPEAK)
            face.show()
            try:
                tts.speak(reply_text)
            except Exception:
                pass

        timer.mark("tts_ms")
        perf_log.record(timer)
        log.info("perf.turn", **timer.summary())


@app.command()
def run(
    log_level: str = typer.Option("INFO", "--log-level", envvar="LUMI_LOG_LEVEL", help="Log level"),
    backend: str = typer.Option("", "--backend", help="Override LUMI_LLM_BACKEND (ollama/mock)"),
    mode: str = typer.Option("", "--mode", help="Override LUMI_MODE (general/code/focus/dictation)"),
    list_devices: bool = typer.Option(False, "--list-devices", help="Print audio devices and exit"),
    enroll: bool = typer.Option(False, "--enroll", help="Record voice enrollment clips and exit"),
) -> None:
    configure_logging(log_level)

    if list_devices:
        from .hardware.audio_io import list_devices as _list_devices  # noqa: PLC0415

        typer.echo(_list_devices())
        raise typer.Exit()

    cfg = get_settings()
    if backend:
        cfg = cfg.model_copy(update={"llm_backend": LLMBackendName(backend)})
    if mode:
        cfg = cfg.model_copy(update={"mode": Mode(mode)})

    mic = SoundDeviceInput(
        sample_rate=cfg.audio_sample_rate,
        device=cfg.audio_input_device,
    )
    voice_id = VoiceID(cfg.data_dir)

    if enroll:
        _enroll_voice(cfg, mic, voice_id)
        raise typer.Exit()

    stt = WhisperSTT(
        model_name=cfg.whisper_model,
        compute_type=cfg.whisper_compute,
        cache_dir=cfg.models_dir,
    )
    llm = make_llm_backend(cfg)

    memory: MemoryStore | None = None
    if cfg.memory_enabled and MemoryStore.is_available():
        memory = MemoryStore(cfg.data_dir)

    conversation = ConversationManager(llm, mode=cfg.mode, memory=memory)
    tts = make_tts(cfg.piper_voice, cfg.models_dir / "piper")
    wake = _make_wake_source(cfg)

    bridge: OpenClawBridge | None = None
    if cfg.openclaw_enabled:
        bridge = OpenClawBridge(cfg.openclaw_url, cfg.openclaw_token)
    audit_log = AuditLog(cfg.data_dir)
    router = SkillRouter(
        conversation=conversation,
        tts=tts,
        bridge=bridge,
        audit_log=audit_log,
        clipboard_enabled=cfg.clipboard_enabled,
        data_dir=cfg.data_dir,
    )
    perf_log = PerfLog(cfg.data_dir)

    display = make_display(cfg.face_width, cfg.face_height)
    sm = StateMachine()
    face = FaceEngine(
        display=display,
        theme=cfg.face_theme,
        color=cfg.face_color,
        models_dir=cfg.models_dir,
    )
    sm.on_state_change(face.set_state)

    with typer.progressbar(length=1, label="Loading Whisper model") as progress:
        stt._load()
        progress.update(1)

    try:
        _voice_loop(cfg, wake, mic, stt, router, tts, voice_id, conversation, sm, face, perf_log)
    except KeyboardInterrupt:
        typer.echo("\nGoodbye.")
        display.close()
        sys.exit(0)


@app.command()
def doctor() -> None:
    """Diagnose send-to-Lumi: permissions, clipboard, hotkey, simulated copy."""
    import os as _os  # noqa: PLC0415
    import time as _time  # noqa: PLC0415
    from .host_helper import clipboard as _clip  # noqa: PLC0415
    from .host_helper.send_to_lumi import default_combo, _is_macos  # noqa: PLC0415
    from .ui.web.persistence import load_settings  # noqa: PLC0415

    configure_logging("WARNING")
    cfg = get_settings()
    user = load_settings(cfg.data_dir)

    def _ok(msg: str) -> None: typer.echo(f"  ✓ {msg}")
    def _warn(msg: str) -> None: typer.echo(f"  ! {msg}")
    def _fail(msg: str) -> None: typer.echo(f"  ✗ {msg}")
    def _section(label: str) -> None: typer.echo(f"\n── {label} ──")

    if _is_macos():
        _section("macOS host")
        term_program = _os.environ.get("TERM_PROGRAM", "(unknown)")
        _ok(f"running under: {term_program}")
        typer.echo(
            "  ! On macOS, Accessibility permission is required for the GLOBAL HOTKEY\n"
            "    AND the simulated Cmd+C. Grant it to the terminal app you launched\n"
            "    lumi from, not to Python:\n"
            "      System Settings → Privacy & Security → Accessibility → '+'\n"
            f"    Add: {term_program if term_program != '(unknown)' else 'your terminal'}\n"
            "    Then fully quit and relaunch that terminal."
        )

    _section("settings")
    if user.clipboard_enabled:
        _ok("clipboard_enabled = true")
    else:
        _fail("clipboard_enabled = false — flip it in Settings → Privacy")
    saved = user.hotkey_combo or default_combo()
    _ok(f"hotkey_combo = {saved}")

    _section("pynput")
    try:
        import pynput  # noqa: F401, PLC0415
        _ok("pynput importable")
    except ImportError:
        _fail("pynput not installed — run: uv pip install -e '.[host]'")
        return

    _section("clipboard read")
    before = _clip.read()
    if before is None:
        _fail("clipboard.read() returned None (pbpaste / xclip / wl-paste missing or empty)")
    else:
        _ok(f"current clipboard: {len(before)} chars{' (empty)' if not before else ''}")

    _section("simulated copy self-test")
    typer.echo("  → select some text in another app, then come back to this terminal")
    typer.echo("  → press Enter to run the test (the test SIMULATES Cmd/Ctrl+C and reads clipboard)")
    typer.confirm("  ready?", default=True, abort=False)
    from pynput.keyboard import Controller, Key  # noqa: PLC0415

    original = _clip.read() or ""
    _time.sleep(0.2)
    kb = Controller()
    mod = Key.cmd if _is_macos() else Key.ctrl
    try:
        with kb.pressed(mod):
            kb.press("c"); kb.release("c")
        _time.sleep(0.25)
    except Exception as exc:
        _fail(f"simulating Cmd+C raised {type(exc).__name__}: {exc}")
        _warn("on macOS: System Settings → Privacy & Security → Accessibility — "
              "make sure your terminal (Terminal/iTerm/Warp/VS Code) is checked.")
        return

    after = _clip.read() or ""
    if after and after != original:
        preview = after[:60].replace("\n", " ")
        _ok(f"simulated copy worked. captured: {preview}…")
    elif after == original and after:
        _warn("simulated copy did not change the clipboard. likely causes:")
        _warn(" - no text was selected when you pressed Enter, OR")
        _warn(" - macOS Accessibility permission denied for this terminal")
    else:
        _warn("clipboard still empty after simulated copy — same accessibility check")

    _section("data dir")
    _ok(f"data_dir = {cfg.data_dir}")
    pending = cfg.data_dir / ".pending_context.json"
    if pending.exists():
        _warn(f"pending context file exists ({pending}) — the voice loop hasn't consumed it yet")


@app.command()
def hotkey(
    no_copy_sim: bool = typer.Option(
        False, "--no-copy-sim",
        help="Skip the simulated Cmd+C — only read what's already on the clipboard (Tier 1 only).",
    ),
) -> None:
    """Run the global-hotkey 'Send to Lumi' daemon (Cmd+Shift+L / Ctrl+Shift+L).

    Captures the currently selected text from any app and queues it as context
    for Lumi's next conversation turn. Requires Accessibility permission on
    macOS the first time it simulates a keystroke.
    """
    from .host_helper.send_to_lumi import HotkeyDaemon  # noqa: PLC0415
    from .ui.web.persistence import load_settings  # noqa: PLC0415

    configure_logging("INFO")
    cfg = get_settings()
    if not cfg.clipboard_enabled:
        typer.echo(
            "Clipboard reading is disabled. Enable it in Settings → Privacy "
            "(or set LUMI_CLIPBOARD_ENABLED=true) before running the hotkey daemon.",
            err=True,
        )
        raise typer.Exit(1)
    user = load_settings(cfg.data_dir)
    HotkeyDaemon(
        data_dir=cfg.data_dir,
        simulate_copy=not no_copy_sim,
        combo=user.hotkey_combo or None,   # falls back to platform default
    ).run()


@app.command()
def web(
    port: int = typer.Option(8080, "--port", help="Port to listen on"),
    host: str = typer.Option("0.0.0.0", "--host", help="Host to bind"),  # noqa: S104
    reload: bool = typer.Option(False, "--reload", help="Auto-reload on code changes (dev)"),
) -> None:
    """Start the Lumi web dashboard (http://localhost:8080)."""
    try:
        import uvicorn  # noqa: PLC0415
    except ImportError:
        typer.echo("Web deps not installed. Run: uv pip install -e '[.web]'", err=True)
        raise typer.Exit(1) from None

    from .ui.web.app import create_app  # noqa: PLC0415

    configure_logging("INFO")
    cfg = get_settings()
    web_app = create_app(cfg.data_dir)
    typer.echo(f"Lumi dashboard → http://localhost:{port}")
    uvicorn.run(web_app, host=host, port=port, reload=reload)
