"""Web chat — type to Lumi from the browser.

Same SkillRouter, ConversationManager, and audit log as the voice loop, so
what works here is what works when you speak. Single-user session: history
lives in `app.state.chat`.

Pending hotkey/clipboard context: consumed at the top of each turn, mirrored
to the chat history as a small "📎 Selection added" entry the user sees just
above their message. Same path as the voice loop.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from ....audio.tts import _PrintTTS
from ....config import get_settings
from ....host_helper.send_to_lumi import consume_pending
from ....llm import make_llm_backend
from ....runtime.conversation import ConversationManager
from ....runtime.errors import safe_error_message
from ....runtime.memory import MemoryStore
from ....skills.audit_log import AuditLog
from ....skills.router import SkillRouter
from ..persistence import load_settings

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


def _get_or_build_session(request: Request) -> ChatSession:
    """One ChatSession per app process. Built lazily on first /chat hit."""
    state = request.app.state
    existing = getattr(state, "chat_session", None)
    if existing is not None:
        return existing

    data_dir = state.data_dir
    cfg = get_settings()
    user = load_settings(data_dir)

    llm = make_llm_backend(cfg)
    memory = MemoryStore(data_dir) if user.memory_enabled and MemoryStore.is_available() else None
    conv = ConversationManager(llm, mode=cfg.mode, memory=memory)
    # Shared session helper — same wiring as the voice loop in main.py, so
    # cloud-mode + PII masking can't drift between the two surfaces.
    from ....runtime.session import build_cloud_bridge  # noqa: PLC0415

    bridge, pseudo, _mode = build_cloud_bridge(
        user, openclaw_enabled=user.openclaw_enabled,
    )
    audit = AuditLog(data_dir)
    sk_router = SkillRouter(
        conversation=conv,
        tts=_PrintTTS(),
        bridge=bridge,
        audit_log=audit,
        clipboard_enabled=user.clipboard_enabled,
        data_dir=data_dir,
        pseudonymizer=pseudo,   # also mask audit-log entries in cloud mode
    )
    session = ChatSession(history=[], router=sk_router, conversation=conv)
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

        last = AuditLog(data_dir).get_recent(n=1)
        handler = last[0]["source"] if last else "llm"
        skill = last[0]["skill"] if last else ""

        new_msgs.append(ChatMessage(
            role="lumi", text=reply, handler=handler, skill=skill, elapsed_ms=elapsed_ms,
        ))
        session.history.append(new_msgs[-1])

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


@router.post("/clear", response_class=HTMLResponse)
async def chat_clear(request: Request) -> HTMLResponse:
    session = _get_or_build_session(request)
    session.history.clear()
    if session.conversation is not None:
        session.conversation.clear()
    return HTMLResponse(
        '<div class="empty-state" style="padding:2rem">Cleared. Say something.</div>'
    )
