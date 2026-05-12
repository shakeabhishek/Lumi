"""Lumi — CLI entry point.

Usage:
  lumi                          # normal run (push-to-talk, Ollama backend)
  lumi --backend mock           # no Ollama needed; great for first-run testing
  lumi --mode code              # start in developer mode
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
from .llm import make_llm_backend
from .log import configure_logging, get_logger
from .runtime.conversation import ConversationManager

app = typer.Typer(name="lumi", add_completion=False, pretty_exceptions_enable=False)
log = get_logger(__name__)


def _make_wake_source(cfg: Settings) -> WakeSource:
    if cfg.wake == WakeStrategy.PUSH_TO_TALK:
        return PushToTalkWake()
    raise NotImplementedError(f"Wake strategy not yet implemented: {cfg.wake}")


def _voice_loop(
    cfg: Settings,
    wake: WakeSource,
    mic: SoundDeviceInput,
    stt: WhisperSTT,
    conversation: ConversationManager,
    tts: TTS,
    voice_id: VoiceID,
) -> None:
    typer.echo(
        f"Lumi is ready.  backend={cfg.llm_backend.value}  mode={cfg.mode.value}  "
        f"record={cfg.audio_record_duration_s}s"
    )
    log.info("lumi.ready", wake=cfg.wake.value, mode=cfg.mode.value, llm=cfg.llm_backend.value)

    while True:
        wake.wait_for_wake()

        audio = mic.record(cfg.audio_record_duration_s)

        if not voice_id.is_owner(audio, cfg.audio_sample_rate):
            log.info("voice_id.rejected")
            continue

        typer.echo("Transcribing...", nl=False)
        text = stt.transcribe(audio, cfg.audio_sample_rate)
        typer.echo("\r              \r", nl=False)  # clear the transcribing line

        if not text:
            typer.echo("(silence or noise — try again)")
            log.info("stt.silence")
            continue

        typer.echo(f"You:  {text}")

        try:
            reply = conversation.chat(text)
        except Exception as exc:
            log.error("llm.error", error=str(exc))
            typer.echo(f"[LLM error: {exc}]", err=True)
            continue

        typer.echo(f"Lumi: {reply}")
        tts.speak(reply)


@app.command()
def run(
    log_level: str = typer.Option("INFO", "--log-level", envvar="LUMI_LOG_LEVEL", help="Log level"),
    backend: str = typer.Option("", "--backend", help="Override LUMI_LLM_BACKEND (ollama/mock)"),
    mode: str = typer.Option("", "--mode", help="Override LUMI_MODE (general/code/focus/dictation)"),
    list_devices: bool = typer.Option(False, "--list-devices", help="Print audio devices and exit"),
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
    stt = WhisperSTT(
        model_name=cfg.whisper_model,
        compute_type=cfg.whisper_compute,
        cache_dir=cfg.models_dir,
    )
    llm = make_llm_backend(cfg)
    conversation = ConversationManager(llm, mode=cfg.mode)
    tts = make_tts(cfg.piper_voice, cfg.models_dir / "piper")
    voice_id = VoiceID()
    wake = _make_wake_source(cfg)

    typer.echo("Loading Whisper model...")
    stt._load()  # warm up before the first keypress so latency lands at startup

    try:
        _voice_loop(cfg, wake, mic, stt, conversation, tts, voice_id)
    except KeyboardInterrupt:
        typer.echo("\nGoodbye.")
        sys.exit(0)
