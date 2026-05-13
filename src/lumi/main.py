"""Lumi — CLI entry point.

Usage:
  lumi                          # normal run (push-to-talk, Ollama backend)
  lumi --backend mock           # no Ollama needed; great for first-run testing
  lumi --mode code              # start in developer mode
  lumi --enroll                 # record voice enrollment clips and exit
  LUMI_LOG_LEVEL=DEBUG lumi     # verbose logs
  lumi --list-devices           # show available audio devices and exit
"""

from __future__ import annotations

import sys

import typer

from .audio.stt import WhisperSTT
from .audio.tts import TTS, make_tts
from .audio.voice_id import VoiceID
from .audio.wake_word import PushToTalkWake, WakeSource
from .config import LLMBackendName, Mode, Settings, WakeStrategy, get_settings
from .hardware.audio_io import SoundDeviceInput
from .hardware.display import make_display
from .llm import make_llm_backend
from .log import configure_logging, get_logger
from .runtime.conversation import ConversationManager
from .runtime.memory import MemoryStore
from .runtime.state_machine import LumiState, StateMachine
from .skills import AuditLog, OpenClawBridge, SkillRouter
from .ui.face.engine import FaceEngine

app = typer.Typer(name="lumi", add_completion=False, pretty_exceptions_enable=False)
log = get_logger(__name__)


def _make_wake_source(cfg: Settings) -> WakeSource:
    if cfg.wake == WakeStrategy.PUSH_TO_TALK:
        return PushToTalkWake()
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

        if not text:
            typer.echo("(silence or noise — try again)")
            log.info("stt.silence")
            continue

        typer.echo(f"You:  {text}")

        # Inject active window context once per turn so the LLM knows what's on screen
        window_ctx = _get_active_window_context(cfg)
        if window_ctx:
            conversation.set_context_hint(f"User's active window: {window_ctx}")
            log.info("context.active_window", window=window_ctx)

        sm.transition(LumiState.THINK)
        face.show()

        # --- Failure mode: router / LLM / skill error ---
        try:
            reply = router.handle(text)
        except Exception as exc:
            log.error("router.error", error=str(exc))
            reply = "Sorry, something went wrong. Please try again."
            typer.echo(f"[error: {exc}]", err=True)

        typer.echo(f"Lumi: {reply}")
        sm.transition(LumiState.SPEAK)
        face.show()

        # --- Failure mode: TTS crash ---
        try:
            tts.speak(reply)
        except Exception as exc:
            log.warning("tts.error", error=str(exc))
            # Text already printed above — user can read it even if TTS fails


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
    )

    display = make_display(cfg.face_width, cfg.face_height)
    sm = StateMachine()
    face = FaceEngine(display=display, theme=cfg.face_theme, color=cfg.face_color)
    sm.on_state_change(face.set_state)

    with typer.progressbar(length=1, label="Loading Whisper model") as progress:
        stt._load()
        progress.update(1)

    try:
        _voice_loop(cfg, wake, mic, stt, router, tts, voice_id, conversation, sm, face)
    except KeyboardInterrupt:
        typer.echo("\nGoodbye.")
        display.close()
        sys.exit(0)


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
