"""Web chat — type to Lumi from the browser.

Same SkillRouter, ConversationManager, and audit log as the voice loop, so
what works here is what works when you speak. Single-user session: history
lives in `app.state.chat`.

Pending hotkey/clipboard context: consumed at the top of each turn, mirrored
to the chat history as a small "📎 Selection added" entry the user sees just
above their message. Same path as the voice loop.

UI flow:
  * Browser POSTs to /chat/stream and reads back a Server-Sent Events stream.
    Each `data: {"chunk": "..."}` event is a fresh token (or full text from a
    native skill). A final `event: done` carries handler/skill/elapsed_ms.
  * /chat/send is the non-streaming fallback (returns the whole turn at once).
    Kept for non-JS clients, integration tests, and as the simpler reference
    implementation.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Annotated, AsyncIterator

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, StreamingResponse

from ....audio.tts import _PrintTTS
from ....config import get_settings
from ....log import get_logger
from ....host_helper.send_to_lumi import consume_pending
from ....llm import make_llm_backend
from ....runtime.conversation import ConversationManager
from ....runtime.errors import safe_error_message
from ....runtime.memory import MemoryStore
from ....skills.audit_log import AuditLog
from ....skills.router import SkillRouter
from ..persistence import load_settings

log = get_logger(__name__)
router = APIRouter()


@dataclass
class ChatMessage:
    role: str           # "user" | "lumi" | "context"
    text: str
    handler: str = ""   # "native" | "openclaw" | "llm" | ""
    skill: str = ""
    elapsed_ms: float = 0.0
    ts: str = field(default_factory=lambda: datetime.now().strftime("%H:%M:%S"))


@dataclass
class ChatSession:
    history: list[ChatMessage] = field(default_factory=list)
    router: SkillRouter | None = None
    conversation: ConversationManager | None = None
    audit: AuditLog | None = None
    memory: object | None = None        # MemoryStore | None — typed loosely to dodge optional-dep import
    # mtime of user_settings.json at session-build time. The next chat
    # turn checks the file's current mtime; if it has changed we rebuild
    # the session so toggles in /settings (memory_enabled, openclaw_enabled,
    # cloud_llm_*) take effect without a process restart.
    settings_mtime: float = 0.0


def _settings_mtime(data_dir) -> float:
    """Wall-clock mtime of user_settings.json, or 0 if it doesn't exist yet.
    Used to detect dashboard-driven settings changes and invalidate the
    cached chat session — without this, toggling memory_enabled (or any
    other setting that participates in build_cloud_bridge or memory
    wiring) wouldn't take effect until the process restarted."""
    p = data_dir / "user_settings.json"
    try:
        return p.stat().st_mtime
    except OSError:
        return 0.0


def _get_or_build_session(request: Request) -> ChatSession:
    """One ChatSession per app process, rebuilt when user_settings.json
    changes. Built lazily on first /chat hit."""
    state = request.app.state
    data_dir = state.data_dir
    mtime = _settings_mtime(data_dir)
    existing = getattr(state, "chat_session", None)
    if existing is not None and existing.settings_mtime == mtime:
        return existing

    cfg = get_settings()
    user = load_settings(data_dir)

    llm = make_llm_backend(cfg, user_settings=user)
    memory = MemoryStore(data_dir) if user.memory_enabled and MemoryStore.is_available() else None
    # Shared session helper — same wiring as the voice loop in main.py, so
    # cloud-mode + PII masking can't drift between the two surfaces.
    from ....runtime.session import build_cloud_bridge  # noqa: PLC0415

    bridge, pseudo, _mode = build_cloud_bridge(
        user, openclaw_enabled=user.openclaw_enabled,
    )
    conv = ConversationManager(llm, mode=cfg.mode, memory=memory, pseudonymizer=pseudo)
    audit = AuditLog(data_dir)
    sk_router = SkillRouter(
        conversation=conv,
        tts=_PrintTTS(),
        bridge=bridge,
        audit_log=audit,
        clipboard_enabled=user.clipboard_enabled,
        data_dir=data_dir,
        pseudonymizer=pseudo,   # also mask audit-log entries in cloud mode
        disabled_native_skills=list(user.disabled_native_skills),
    )
    # Preserve in-flight chat history across a settings-driven rebuild —
    # changing your memory toggle shouldn't blow away the current
    # conversation, just affect what happens on subsequent turns.
    prior_history = existing.history if existing is not None else []
    session = ChatSession(
        history=prior_history, router=sk_router, conversation=conv,
        audit=audit, memory=memory, settings_mtime=mtime,
    )
    state.chat_session = session
    return session


@router.get("/", response_class=HTMLResponse)
async def chat_index(request: Request) -> HTMLResponse:
    session = _get_or_build_session(request)
    settings = load_settings(request.app.state.data_dir)
    cfg = get_settings()
    return request.app.state.templates.TemplateResponse(
        request, "chat.html",
        {
            "settings": settings,
            "messages": session.history,
            "model": cfg.ollama_model,
            "backend": cfg.llm_backend.value,
            "memory_active": session.memory is not None,
        },
    )


@router.post("/send", response_class=HTMLResponse)
async def chat_send(
    request: Request,
    message: Annotated[str, Form()],
) -> HTMLResponse:
    """Run one turn through the real router; return the appended messages."""
    data_dir = request.app.state.data_dir
    user = load_settings(data_dir)
    session = _get_or_build_session(request)
    assert session.router is not None and session.conversation is not None

    new_msgs: list[ChatMessage] = []

    # Pending context (from hotkey / /api/context) — surface, then inject.
    if user.clipboard_enabled:
        pending = consume_pending(data_dir)
        if pending:
            from ....host_helper.send_to_lumi import format_hint  # noqa: PLC0415

            session.conversation.set_context_hint(format_hint(pending))
            text = pending.get("text", "")
            source = pending.get("source", "clipboard")
            preview = text[:160].replace("\n", " ")
            new_msgs.append(ChatMessage(
                role="context",
                text=f"📎 {source} added ({len(text)} chars): {preview}{'…' if len(text) > 160 else ''}",
            ))
            session.history.append(new_msgs[-1])

    msg = message.strip()
    if msg:
        new_msgs.append(ChatMessage(role="user", text=msg))
        session.history.append(new_msgs[-1])

        t0 = time.perf_counter()
        try:
            reply = session.router.handle(msg)
        except Exception as exc:
            reply = safe_error_message(exc, where="chat.send")
        elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)

        last = session.audit.get_recent(n=1) if session.audit else []
        handler = last[0]["source"] if last else "llm"
        skill = last[0]["skill"] if last else ""

        new_msgs.append(ChatMessage(
            role="lumi", text=reply, handler=handler, skill=skill, elapsed_ms=elapsed_ms,
        ))
        session.history.append(new_msgs[-1])

        # Memory write-back for non-LLM paths — same rationale as in
        # /chat/stream. ConversationManager handles the LLM path
        # internally; native/openclaw/tool paths need this hook.
        if session.memory is not None and reply and handler in {"llm", "openclaw", "tool"}:
            try:
                session.memory.store_turn(msg, reply)  # type: ignore[attr-defined]
            except Exception as exc:
                log.warning("chat.memory_store_failed", error=str(exc))

        # If the cloud subprocess failed silently this turn, surface a
        # one-shot notice so the user knows their cloud LLM isn't engaged
        # and what to do about it. Subsequent failures of the same kind
        # don't re-spam — only new (or post-success) failures notify.
        if session.router._bridge is not None:        # noqa: SLF001  intentional, router exposes none
            notice = session.router._bridge.cloud_failure_notice()  # noqa: SLF001
            if notice:
                new_msgs.append(ChatMessage(role="context", text=f"⚠ {notice}"))
                session.history.append(new_msgs[-1])

    return request.app.state.templates.TemplateResponse(
        request, "chat_messages.html",
        {"messages": new_msgs},
    )


_STREAM_SENTINEL = object()

# Cap on how long any single token (or whole-reply chunk for OpenClaw
# / native skills) can take before we abort the stream. Long enough to
# survive a cold cloud-LLM round-trip (~30s for Gemini through the
# OpenClaw subprocess); short enough that a stuck generator can't
# park an executor thread forever and starve the pool.
_CHUNK_TIMEOUT_S = 45.0


@router.post("/stream")
async def chat_stream(
    request: Request,
    message: Annotated[str, Form()],
) -> StreamingResponse:
    """SSE streaming variant of /chat/send.

    Wire protocol:
      data: {"chunk": "..."}\\n\\n            — reply text fragment
      event: context\\n
      data: {"text": "📎 ..."}\\n\\n           — context bubble (optional, leads)
      event: done\\n
      data: {"handler":"llm","skill":"","elapsed_ms":1234}\\n\\n
                                              — terminal metadata, sent last

    The user message itself is NOT echoed back — the client renders it
    optimistically on submit, before the request is fired.
    """
    data_dir = request.app.state.data_dir
    user = load_settings(data_dir)
    session = _get_or_build_session(request)
    assert session.router is not None and session.conversation is not None

    msg = message.strip()
    if not msg:
        async def empty() -> AsyncIterator[bytes]:
            yield b'event: done\ndata: {"handler":"","skill":"","elapsed_ms":0}\n\n'
        return StreamingResponse(empty(), media_type="text/event-stream")

    # Append the user message to session history exactly once, server-side,
    # before we start streaming. The client already rendered it optimistically.
    session.history.append(ChatMessage(role="user", text=msg))

    # Consume pending hotkey/clipboard context (same contract as /chat/send).
    pending = None
    context_payload = None
    if user.clipboard_enabled:
        pending = consume_pending(data_dir)
        if pending:
            from ....host_helper.send_to_lumi import format_hint  # noqa: PLC0415

            session.conversation.set_context_hint(format_hint(pending))
            text = pending.get("text", "")
            source = pending.get("source", "clipboard")
            preview = text[:160].replace("\n", " ")
            ellipsis = "…" if len(text) > 160 else ""
            ctx_text = f"📎 {source} added ({len(text)} chars): {preview}{ellipsis}"
            context_payload = {"text": ctx_text}
            session.history.append(ChatMessage(role="context", text=ctx_text))

    async def stream() -> AsyncIterator[bytes]:
        # 1. Context bubble (if any) — leads the stream so the UI can show it
        #    above the reply as it lands.
        if context_payload is not None:
            yield (
                b"event: context\ndata: "
                + json.dumps(context_payload).encode()
                + b"\n\n"
            )

        # 2. Reply tokens. handle_streaming() yields chunks for the LLM path
        #    and a single chunk for native skills / OpenClaw bridge — same
        #    SSE shape either way, the client doesn't have to care.
        #    Also publish face-state transitions to /device-display/events
        #    so the device screen tracks chat turns in real time.
        from .device_display import publish_face_state  # noqa: PLC0415

        await publish_face_state(request, "think")

        # Outer try/finally guarantees the face returns to IDLE no matter
        # how this generator exits — normal completion, an exception, OR
        # cancellation. The latter matters: if the client disconnects (or
        # this whole worker gets killed mid-request, e.g. a service
        # restart) while still awaiting the FIRST chunk, Starlette cancels
        # this generator at that await point. asyncio.CancelledError is a
        # BaseException in modern Python, so it is NOT caught by the plain
        # `except Exception` blocks below — without this outer finally,
        # execution would jump straight past step 6 and never publish
        # "idle", leaving the device-display stuck showing "Thinking…"
        # until some unrelated future turn happens to complete (observed
        # on the real Pi, 2026-07-02 — the actual root cause, not merely
        # a demonstration of a theoretical edge case).
        try:
            t0 = time.perf_counter()
            collected: list[str] = []
            loop = asyncio.get_event_loop()

            first_chunk_seen = False
            gen = None
            try:
                gen = session.router.handle_streaming(msg)
            except Exception as exc:
                err = safe_error_message(exc, where="chat.stream")
                collected.append(err)
                yield b"data: " + json.dumps({"chunk": err}).encode() + b"\n\n"
            else:
                try:
                    while True:
                        # Each next(gen) runs in a worker thread so the chunk
                        # producer (which can block on httpx / Ollama) doesn't
                        # freeze the event loop.
                        #
                        # Hard cap per chunk — if the producer hangs for any
                        # reason (Ollama wedged, network dropping packets,
                        # OpenClaw subprocess stuck) we'd otherwise park this
                        # executor thread forever and starve the pool. After
                        # _CHUNK_TIMEOUT_S we surface a graceful error chunk
                        # and bail. Sized for cold cloud-LLM latency + a
                        # safety margin.
                        try:
                            chunk = await asyncio.wait_for(
                                loop.run_in_executor(None, next, gen, _STREAM_SENTINEL),
                                timeout=_CHUNK_TIMEOUT_S,
                            )
                        except asyncio.TimeoutError:
                            err = "(reply timed out — falling back to local on next turn)"
                            collected.append(err)
                            yield b"data: " + json.dumps({"chunk": err}).encode() + b"\n\n"
                            break
                        if chunk is _STREAM_SENTINEL:
                            break
                        if not first_chunk_seen:
                            first_chunk_seen = True
                            await publish_face_state(request, "speak")
                        collected.append(chunk)
                        yield b"data: " + json.dumps({"chunk": chunk}).encode() + b"\n\n"
                        # Bail fast if the browser tab went away. Without
                        # this we'd keep pulling chunks out of the generator
                        # (each blocking an executor thread) for an audience
                        # of nobody — exactly the pattern that filled the
                        # default thread pool in Phase 4's soak.
                        if await request.is_disconnected():
                            break
                except Exception as exc:
                    err = safe_error_message(exc, where="chat.stream")
                    collected.append(err)
                    yield b"data: " + json.dumps({"chunk": err}).encode() + b"\n\n"
            finally:
                # Always close the generator — releases sockets / file
                # handles / OpenClaw subprocess pipes that handle_streaming
                # may be holding. Without this, a partial consumption (early
                # break, exception, timeout) leaves resources dangling until
                # the GC eventually collects.
                if gen is not None:
                    try:
                        gen.close()
                    except Exception:
                        pass

            elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)

            # 3. Record the assembled reply in session history with metadata
            #    pulled from the audit log (router.handle_streaming wrote the
            #    audit entry for us with the right source label).
            last = session.audit.get_recent(n=1) if session.audit else []
            handler = last[0]["source"] if last else "llm"
            skill = last[0]["skill"] if last else ""
            reply_text = "".join(collected)
            session.history.append(ChatMessage(
                role="lumi", text=reply_text,
                handler=handler, skill=skill, elapsed_ms=elapsed_ms,
            ))

            # 3b. Persist the exchange to long-term memory if enabled.
            # ConversationManager already stores LLM-path turns from inside
            # stream_chat(), but native/openclaw paths never reach that code
            # — they're handled by the router/bridge directly. Storing here
            # covers those too, so "what did we talk about earlier?" works
            # regardless of how we answered. Skip native skills since
            # those are mostly utility (timer / volume / mode) and not
            # worth recall.
            if session.memory is not None and reply_text and handler in {"llm", "openclaw", "tool"}:
                try:
                    session.memory.store_turn(msg, reply_text)  # type: ignore[attr-defined]
                except Exception as exc:
                    log.warning("chat.memory_store_failed", error=str(exc))

            # 4. Cloud-failure one-shot notice — same logic as /chat/send.
            if session.router._bridge is not None:                # noqa: SLF001
                notice = session.router._bridge.cloud_failure_notice()  # noqa: SLF001
                if notice:
                    session.history.append(ChatMessage(role="context", text=f"⚠ {notice}"))
                    yield (
                        b"event: notice\ndata: "
                        + json.dumps({"text": f"⚠ {notice}"}).encode()
                        + b"\n\n"
                    )

            # 5. Terminal "done" so the client knows to finalise the bubble.
            meta = {"handler": handler, "skill": skill, "elapsed_ms": elapsed_ms}
            yield b"event: done\ndata: " + json.dumps(meta).encode() + b"\n\n"
        finally:
            # 6. Face back to IDLE for the device display — guaranteed,
            # see the comment above this try block.
            await publish_face_state(request, "idle")

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            # Disable nginx-style proxy buffering so chunks arrive in
            # real time when Lumi is reverse-proxied (e.g. on the Pi).
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache",
        },
    )


@router.post("/clear", response_class=HTMLResponse)
async def chat_clear(request: Request) -> HTMLResponse:
    session = _get_or_build_session(request)
    session.history.clear()
    if session.conversation is not None:
        session.conversation.clear()
    return HTMLResponse(
        '<div class="empty-state" style="padding:2rem">Cleared. Say something.</div>'
    )
