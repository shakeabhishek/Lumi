// Optimistic + streaming chat UI for /chat.
//
// The previous flow waited for the server to return the full HTML partial
// before either bubble appeared — qwen2.5:7b can take 4-10s on a longer
// answer, so the user sat staring at the input wondering if their message
// went through. Two changes:
//
//   1. On submit, render the user's message bubble immediately, clear the
//      input, drop a placeholder Lumi bubble underneath. Server hasn't
//      been hit yet.
//   2. POST to /chat/stream, read the response as a text/event-stream,
//      append each `data: {"chunk": "..."}` event to the placeholder.
//      A final `event: done` finalises the metadata row (handler / skill /
//      ms badge) so it lines up with the non-streaming path's layout.
//
// CSRF: __LUMI_CSRF__ is set in the base template's <script> block.
// SSE-via-fetch (rather than EventSource) is what lets us POST with a
// proper CSRF header — EventSource is GET-only and can't carry headers.

(function () {
  const form = document.getElementById('chat-form');
  const log = document.getElementById('chat-log');
  const input = document.getElementById('chat-input');
  const clearBtn = document.getElementById('chat-clear');
  const lumiName = (form && form.dataset.lumiName) || 'Lumi';

  if (!form || !log || !input) return;            // page hydration race

  // `?prefill=foo` lets onboarding step 9 hand the user's first
  // message off to chat without needing a separate transport. Strip
  // it from the URL after consuming so a reload doesn't re-fire.
  (function maybePrefill() {
    const params = new URLSearchParams(window.location.search);
    const msg = params.get('prefill');
    if (!msg) return;
    history.replaceState(null, '', window.location.pathname);
    input.value = msg;
    // Defer submit by a tick so the page paints first — the user
    // sees their message land in the input before the spinner fires.
    setTimeout(() => form.requestSubmit(), 60);
  })();

  function now() {
    const d = new Date();
    return d.toTimeString().slice(0, 8);          // HH:MM:SS
  }

  function scrollToBottom() {
    log.scrollTop = log.scrollHeight;
  }

  // Empty-state placeholder is the only child when the log is fresh.
  // Strip it the first time we add a real bubble.
  function removeEmptyState() {
    const empty = log.querySelector('.empty-state');
    if (empty) empty.remove();
  }

  function renderUserBubble(text) {
    removeEmptyState();
    const row = document.createElement('div');
    row.className = 'chat-row chat-row--user';
    row.innerHTML =
      '<div class="chat-meta"><span class="who">You</span><span>' + now() + '</span></div>' +
      '<div class="chat-bubble chat-bubble--user"></div>';
    row.querySelector('.chat-bubble--user').textContent = text;
    log.appendChild(row);
    scrollToBottom();
    return row;
  }

  function renderContextBubble(text) {
    removeEmptyState();
    const row = document.createElement('div');
    row.className = 'chat-row chat-row--context';
    row.innerHTML = '<div class="chat-bubble chat-bubble--context"></div>';
    row.querySelector('.chat-bubble--context').textContent = text;
    log.appendChild(row);
    scrollToBottom();
  }

  function renderLumiPlaceholder() {
    removeEmptyState();
    const row = document.createElement('div');
    row.className = 'chat-row chat-row--lumi chat-row--streaming';
    row.innerHTML =
      '<div class="chat-meta">' +
      '<span class="who"></span>' +
      '<span class="badge-slot"></span>' +
      '<span class="ms-slot"></span>' +
      '<span class="ts-slot">' + now() + '</span>' +
      '</div>' +
      '<div class="chat-bubble chat-bubble--lumi"><span class="reply-text"></span><span class="chat-caret">▍</span></div>';
    row.querySelector('.who').textContent = lumiName;
    log.appendChild(row);
    scrollToBottom();
    return row;
  }

  function finalizeLumi(row, meta) {
    row.classList.remove('chat-row--streaming');
    const caret = row.querySelector('.chat-caret');
    if (caret) caret.remove();
    if (meta) {
      const badgeSlot = row.querySelector('.badge-slot');
      const msSlot = row.querySelector('.ms-slot');
      if (badgeSlot && meta.handler) {
        const b = document.createElement('span');
        b.className = 'badge ' + meta.handler;
        b.textContent = meta.handler + (meta.skill ? ':' + meta.skill : '');
        badgeSlot.appendChild(b);
      }
      if (msSlot) msSlot.textContent = (meta.elapsed_ms || 0) + ' ms';
    }
  }

  // SSE parsing over a fetch streaming body. EventSource doesn't support
  // POST or custom headers, so we hand-roll the parser.
  async function readSseStream(response, onEvent) {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let idx;
      while ((idx = buffer.indexOf('\n\n')) >= 0) {
        const raw = buffer.slice(0, idx);
        buffer = buffer.slice(idx + 2);
        onEvent(parseSseFrame(raw));
      }
    }
  }

  function parseSseFrame(text) {
    const lines = text.split('\n');
    let event = 'message';
    let dataParts = [];
    for (const line of lines) {
      if (line.startsWith('event:')) event = line.slice(6).trim();
      else if (line.startsWith('data:')) dataParts.push(line.slice(5).trimStart());
    }
    let data = null;
    if (dataParts.length) {
      try { data = JSON.parse(dataParts.join('\n')); }
      catch (_) { data = { raw: dataParts.join('\n') }; }
    }
    return { event, data };
  }

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const msg = input.value.trim();
    if (!msg) return;

    // Optimistic: render user bubble + Lumi placeholder before we hit the
    // wire. Clear the input so the user can keep typing.
    renderUserBubble(msg);
    const lumiRow = renderLumiPlaceholder();
    const replyEl = lumiRow.querySelector('.reply-text');
    input.value = '';
    input.focus();

    let resp;
    try {
      resp = await fetch('/chat/stream', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/x-www-form-urlencoded',
          'X-CSRF-Token': window.__LUMI_CSRF__ || '',
        },
        body: new URLSearchParams({ message: msg }),
      });
    } catch (err) {
      replyEl.textContent = "(connection error — Lumi can't be reached)";
      finalizeLumi(lumiRow, { handler: 'error', skill: '', elapsed_ms: 0 });
      return;
    }

    if (!resp.ok || !resp.body) {
      replyEl.textContent = '(server error — refresh and try again)';
      finalizeLumi(lumiRow, { handler: 'error', skill: '', elapsed_ms: 0 });
      return;
    }

    let finalMeta = null;
    try {
      await readSseStream(resp, ({ event, data }) => {
        if (event === 'context' && data && data.text) {
          // Context bubble lands BEFORE the user message visually. Move it
          // into place by inserting at the row above the user message.
          // (User row is the most-recent appended one before placeholder.)
          const userRow = log.children[log.children.length - 2];
          const ctxRow = document.createElement('div');
          ctxRow.className = 'chat-row chat-row--context';
          ctxRow.innerHTML = '<div class="chat-bubble chat-bubble--context"></div>';
          ctxRow.querySelector('.chat-bubble--context').textContent = data.text;
          log.insertBefore(ctxRow, userRow);
          scrollToBottom();
        } else if (event === 'notice' && data && data.text) {
          renderContextBubble(data.text);
        } else if (event === 'done' && data) {
          finalMeta = data;
        } else if ((event === 'message' || !event) && data && typeof data.chunk === 'string') {
          replyEl.textContent += data.chunk;
          scrollToBottom();
        }
      });
    } catch (err) {
      // mid-stream failure
      if (!replyEl.textContent) {
        replyEl.textContent = '(stream interrupted)';
      }
    }
    finalizeLumi(lumiRow, finalMeta);
  });

  if (clearBtn) {
    clearBtn.addEventListener('click', async () => {
      if (!confirm('Clear chat history (this turn + conversation memory)?')) return;
      try {
        await fetch('/chat/clear', {
          method: 'POST',
          headers: { 'X-CSRF-Token': window.__LUMI_CSRF__ || '' },
        });
      } catch (_) { /* best-effort */ }
      log.innerHTML =
        '<div class="empty-state">Cleared. Say something.</div>';
      input.focus();
    });
  }
})();
