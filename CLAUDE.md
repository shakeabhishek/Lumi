# Lumi

> Your AI companion. Always on. Always yours.

Lumi is a portable physical AI desk companion that plugs into any computer via USB-C. It runs an LLM locally on dedicated AI hardware, listens through onboard microphones, speaks back through an onboard speaker, watches for gestures through an onboard camera, and shows a friendly animated face on a small display. The whole experience is meant to feel warm, calm, and deeply personal — an AI that lives on your desk, knows you, and never sends your data anywhere it doesn't have to.

---

## Project status

**Pre-hardware design phase.** All major architecture decisions are locked
in. Pi 5 + AI HAT+ 2 + Hailo on order. Software runs on a laptop; the
mocked hardware interfaces remain only for the wake-word / mic / camera
paths — the **device display is now a React/Vite app rendered by a
Chromium kiosk on the Pi** (pivot 2026-05-24, see "Device display
architecture" below), so no pygame display swap is needed when hardware
arrives.

**Phases 1-4 complete.** 475+ unit tests passing. Voice loop, web chat
with optimistic send + token streaming, ChromaDB memory, audit log, 8
native skills, hotkey "send to Lumi" (global Cmd+Alt+L), perf log, data
export + factory reset, OS-keychain secret storage, dev-panel skill
test, journal auto-summary, 9-step onboarding, sprite-pack upload UI
(`/settings/sprites`), React device display at `/device-display/` with
live SSE state push.

**Privacy + robustness sprint (audit 2026-05-21) complete.** 22 findings
closed across security/privacy/UX/correctness. Architectural invariants
established (and tested) — see "Invariants & patterns" section below.

**V2 sequence #1 (cloud LLM end-to-end) verified 2026-05-23.** Real
Gemini call through the full PII-pseudonymizer → `npx openclaw agent
--local` subprocess → unmasked reply path. Four real bugs surfaced and
fixed: test fixtures had leaked into the developer's `~/.openclaw/
openclaw.json`; `_PROVIDERS` used wrong `api` strings vs OpenClaw's
MODEL_APIS enum; `sync_to_openclaw` didn't purge stale Lumi providers
on switch; bridge was missing `--local` + parsing the wrong stream.
All locked down with tests.

**Device-display pivot 2026-05-24.** Replaced the pygame face renderers
(pixel/vector/terminal/chrome compositor) with a React/Vite/Tailwind
app at `src/lumi/ui/device_display/`, served by FastAPI at
`/device-display/`. Rationale: the pygame face couldn't match Figma's
visual fidelity within reasonable effort, and the Pi 5's 16 GB RAM
comfortably supports a Chromium kiosk pointed at localhost. Backend
publishes face-state transitions via an in-process broadcaster
(`ui/web/device_bus.py`); the React `useDeviceState()` hook subscribes
via SSE at `/device-display/events`. Sprite packs from
`/settings/sprites` flow through to the React display via the existing
data_dir/bundled fallback chain.

**Runtime architecture — the honest version**

Two paths, chosen automatically based on whether a cloud LLM API key is
configured in `/settings/cloud`:

1. **V1 hybrid (default, no cloud key)**: SkillRouter → native Python
   skill OR `OpenClawBridge(runtime_mode="ollama")` → direct Ollama
   `/api/chat` with our Python tool defs → our `_SKILL_IMPLS` registry
   handlers (weather, wikipedia, currency, news). Hit 94% on the
   Phase-1 viability test. OpenClaw service is NOT in the runtime path.
   Skill manifests in `~/.openclaw/workspace/skills/<name>/SKILL.md`
   serve as the catalog source-of-truth (so the `lumi skills` CLI
   shows what's installed) but are documentation only — they don't get
   surfaced as callable tools to the local LLM.

2. **V2 cloud (when an Anthropic/OpenAI/Gemini key is set)**: SkillRouter
   → native Python skill OR `OpenClawBridge(runtime_mode="openclaw_cloud")`
   → shells out to `npx openclaw agent --agent main --message …`. OpenClaw
   gateway uses the cloud LLM (synced via
   `skills.openclaw_operator.sync_to_openclaw`) as its agent operator.
   Our **JS plugins** in `openclaw-service/plugins/<name>/` register as
   real OpenAI-style `tool_calls` against the gateway. Cloud LLM emits
   tool_calls reliably, plugin handlers execute, results stream back.
   Unlocks the entire OpenClaw plugin ecosystem (100+ community plugins
   ride on the same path).

**Why the JS plugins matter in BOTH paths but are only invoked in V2**:
local small models (1.5B/1.7B/8B llama/7B qwen — all tested) won't emit
tool_calls through OpenClaw's ~13K-token agent prompt. They see the
tools but pick "roleplay the answer" over "emit a structured call." The
JS plugins are loaded and visible in either mode; only the cloud LLM
actually drives them.

The Python tool impls in V1 hybrid are deliberately duplicates of the JS
plugins for the same skill. Two backends, same skill name. V1 hybrid is
the always-works floor; V2 cloud is the rich ceiling.

---

## Product identity

**Tagline:** Your AI companion. Always on. Always yours.

**Primary role:** Personal AI desk companion — ambient presence, proactive intelligence, physical ritual, knows YOU.

**Secondary role:** Developer copilot add-on (Claude Code integration in V2).

**Brand voice:** Warm, calm, deeply personal, privacy-first, premium. Not snarky, not corporate, not robotic.

**What makes Lumi different from ChatGPT or Claude.ai:**
- Physical presence on your desk
- Truly local AI (V1 has zero cloud LLM dependency for inference)
- Ambient awareness via camera and microphones
- Owns its data — your conversations, embeddings, and preferences live on the device
- Extensible via OpenClaw's skill ecosystem (curated for safety in V1)

---

## Architecture overview

Lumi runs a **purely onboard LLM** for V1 — no cloud LLM calls during inference. WiFi is available for OpenClaw skills that need network access (email, calendar, weather, etc.) but the LLM itself stays local.

```
┌────────────────────────────────────────────────────────────────┐
│                          LUMI DEVICE                            │
│                                                                  │
│  ┌─────────────┐    ┌──────────────┐    ┌─────────────────┐    │
│  │   Camera    │ ──▶│   AI HAT+ 2  │◀── │  Microphones    │    │
│  │  (CSI bus)  │    │  (PCIe bus)  │    │  (I2S via HAT)  │    │
│  └─────────────┘    │              │    └─────────────────┘    │
│                     │  - LLM       │                            │
│  ┌─────────────┐    │  - MediaPipe │    ┌─────────────────┐    │
│  │  Display    │◀── │  (8GB RAM)   │ ──▶│    Speaker      │    │
│  │  (SPI bus)  │    │              │    │  (analog)       │    │
│  └─────────────┘    └──────┬───────┘    └─────────────────┘    │
│                            │                                     │
│                     ┌──────▼───────┐                            │
│                     │   Pi 5 16GB  │ ──── USB-C ──▶ Host PC     │
│                     │              │                            │
│                     │  - Lumi app  │                            │
│                     │  - Whisper   │                            │
│                     │  - Piper     │                            │
│                     │  - ChromaDB  │      ┌───────────────┐    │
│                     │  - FastAPI   │ ◀──▶ │  OpenClaw     │    │
│                     │              │ HTTP │  (Node.js)    │    │
│                     │              │      └───────────────┘    │
│                     └──────┬───────┘                            │
│                            │                                     │
│                            ▼ WiFi (for OpenClaw skills only)    │
└────────────────────────────────────────────────────────────────┘
```

**Compute & memory split:**
- **AI HAT+ 2 (8GB dedicated RAM)**: LLM inference, MediaPipe gesture recognition. Isolated memory pool.
- **Pi 5 (16GB system RAM)**: OS, Lumi Python app, Whisper, Piper, ChromaDB, FastAPI, **OpenClaw service (Node.js)**, audio pipeline, **Chromium kiosk** rendering the device display from `localhost:8080/device-display/`. ~13 GB free at idle; Chromium adds ~500-800 MB which still leaves comfortable headroom.

**Why memory separation works:** AI HAT+ 2 handles the heavy LLM workload in its own 8GB. Pi RAM is never used for LLM inference, so OpenClaw + the FastAPI server + the Chromium kiosk all share the 16 GB system pool. Confirmed memory headroom ~12 GB free at idle even with Chromium running.

## Device display architecture

The screen on Lumi's body is a Chromium kiosk pointing at the local
FastAPI server's `/device-display/` route. The React app at
`src/lumi/ui/device_display/` is built once via `npm run build` and
served as static files by FastAPI; state flows backend → frontend over
SSE:

```
[StateMachine in voice loop]  ── HTTP POST /api/state ──▶  [DeviceBus singleton]
[ChatSession in web chat]     ── publish_face_state() ──▶  [in src/lumi/ui/web/]
[Weather + CPU sampler]       ── publish() ─────────────▶
                                                           │
                                                           ▼
                                    GET /device-display/events  (SSE)
                                                           │
                                                           ▼
                                  React useDeviceState() → re-render
```

`DeviceBus` (`src/lumi/ui/web/device_bus.py`) is an in-process pub/sub
with last-snapshot caching, so a new SSE subscriber gets the current
state immediately. Slow subscribers drop oldest frames rather than
backing up publishers.

**Data flow (typical voice query, native skill):**
```
Mic → Whisper Tiny (CPU) → text
    → Skill router → native Python skill (fast path)
    → LLM via AI HAT+ 2 → response
    → Piper TTS (CPU) → audio → speaker
```

**Data flow (voice query, OpenClaw skill):**
```
Mic → Whisper Tiny (CPU) → text
    → Skill router → OpenClaw skill
    → OpenClaw orchestrates: LLM (via custom Hailo provider) + tool calls
    → Result → Piper TTS (CPU) → audio → speaker
```

**Data flow (gesture):**
```
Camera → MediaPipe via AI HAT+ 2 → hand landmarks
       → gesture classifier → action
```

---

## V1 hardware

| Category | Component | Purpose |
|---|---|---|
| **Core compute** | Raspberry Pi 5 (16GB) | Main computer, runs Lumi OS + OpenClaw |
| | Raspberry Pi AI HAT+ 2 | LLM + vision inference (40 TOPS, 8GB onboard RAM) |
| | Active cooler for Pi 5 | Thermal management (required) |
| **Storage** | SanDisk Extreme Pro 256GB A2 microSD | OS, models, ChromaDB, user data |
| **Display** | Waveshare 3.5" IPS SPI display (480x320) | Lumi's animated face |
| **Audio** | ReSpeaker 2-Mics Pi HAT V2.0 | Mics + speaker output + 3 RGB LEDs + 1 button |
| | 3-5W 4Ω speaker with JST connector | Voice output |
| **Camera** | Pi Camera Module 3 Wide | Gestures + presence detection (102° FOV, autofocus) |
| | CSI ribbon cable (Pi 5 fine-pitch) | Pi 5 uses smaller CSI connector |
| **Power & wiring** | USB-C to USB-C cable (1m, braided) | Connection to host PC |
| | Pi 5 official 27W USB-C power supply | Power during dev / when not host-powered |
| | Premium jumper wire kit | SPI display GPIO connections |
| **Structure** | M2.5 standoffs + screws kit | HAT stacking |
| | Acrylic mounting plate | Bare-bones V1 base |
| | Self-adhesive rubber feet | Non-slip base |

**PCIe lane usage:** Single PCIe lane on Pi 5 is dedicated to AI HAT+ 2. NVMe storage is intentionally not used — onboard storage is microSD only.

---

## V1 software stack

```
Layer                     Component                  Notes
─────────────────────────────────────────────────────────────────────────
Operating system          Raspberry Pi OS Lite       64-bit, headless
                          (Bookworm or Trixie)

Runtime                   Python 3.11+               Lumi core
                          Node.js 20+                OpenClaw service

Speech-to-text            Whisper Tiny               ~150MB, runs on Pi CPU
                                                      ~0.5s for short clips

Text-to-speech            Piper TTS                  ~100MB, runs on Pi CPU
                                                      Warm voice personality

Wake word                 OpenWakeWord or Porcupine  Local detection
                          (curated name palette)      "Hey Lumi" + alternatives

Local LLM                 Qwen2.5 1.5B               Runs on AI HAT+ 2
                                                      Quantized for Hailo
                                                      (qwen2:1.5b lacks tool support)

Vision                    MediaPipe Hand Landmarks   Runs on AI HAT+ 2
                          + custom gesture classifier 30 fps

Vector database           ChromaDB (embedded)        Local personal data
                                                      Up to ~1GB

Embedding model           all-MiniLM-L6              Generated during ingestion
                                                      Stored in ChromaDB

Skills framework          OpenClaw (Node.js)         Runs as systemd service on Pi
                                                      Custom LLM provider routes to Hailo
                                                      Curated skill set for V1

Web server                FastAPI                    Serves lumi.local
                                                      Onboarding, dashboard,
                                                      skill management

USB gadget                libcomposite               HID + Mass Storage + CDC
                                                      Native Pi 5 support

Audio I/O                 ALSA + ReSpeaker drivers   Mic capture + playback

System utility            log2ram                    Reduces SD card writes ~95%

Process supervisor        systemd                    All Lumi services
```

**Service architecture (systemd units):**
- `lumi.service` — main Python app runtime
- `lumi-web.service` — FastAPI dashboard
- `lumi-openclaw.service` — OpenClaw Node.js service (skills + agent)
- `lumi-gadget.service` — USB composite device setup
- `lumi-audio.service` — audio pipeline
- `lumi-camera.service` — vision pipeline

---

## Skills system

Lumi has **two skill layers** that work together:

```
Native Python skills              OpenClaw skills
──────────────────────────        ──────────────────────────
Fast, deterministic               Flexible, extensible
Hardware-near (audio, display)    Network-capable (email, calendar, news)
Simple commands                   Multi-step workflows possible
Always available                  Per-skill enable/disable
Examples:                         Examples:
  - "what time is it"               - "check my email"
  - "set timer 5 minutes"           - "what's on my calendar"
  - "switch to focus mode"          - "weather today"
  - "louder / quieter"              - "find file containing X"
                                    - "what's in the news"
                                    - "what's playing on Spotify"
                                    - "how's my machine doing"
```

**Skill router** (in Lumi Python runtime): On each user utterance, decides which layer handles it.

```python
class SkillRouter:
    def route(self, transcript: str) -> SkillHandler:
        # 1. Try native skill keyword match (fast, reliable)
        native = self.native_registry.match(transcript)
        if native:
            return native
        
        # 2. Fall back to OpenClaw (if enabled + skill matches)
        if self.openclaw_enabled:
            return OpenClawHandler(transcript)
        
        # 3. Pure LLM response (no skill)
        return DirectLLMHandler(transcript)
```

**Custom LLM provider for OpenClaw:** OpenClaw expects a cloud LLM (Claude, GPT). We write a custom provider that routes OpenClaw's LLM calls to:
- **Dev**: Ollama serving Qwen2.5 1.5B on laptop
- **Production**: Hailo runtime on AI HAT+ 2

Same provider interface, swappable backend by config.

**V1 curated OpenClaw skill set** (vetted for safety with 1.5B model):

Core — always included:
- `email_read` — IMAP read-only (dedicated account, no send, no delete)
- `calendar_read` — CalDAV read-only (dedicated account, no creation, no modification)
- `weather` — Public API, no auth needed
- `timer` — Local, no network
- `pomodoro` — 25/5 work-break cycle timer, local
- `file_search` — Local filesystem search, sandboxed to `sandbox/` directory only
- `reminder` — Local storage
- `news_headlines` — Free News API or RSS, read-only
- `wikipedia_lookup` — Public Wikimedia API, no auth, zero personal data risk
- `clipboard_read` — Reads current clipboard contents (user must grant permission)
- `system_stats` — CPU / RAM / disk usage, local, read-only
- `unit_converter` — Offline, deterministic (distance, weight, temp, etc.)
- `currency_exchange` — Live rates via free public API (e.g. exchangerate.host), no user data

Conditional V1 — add after viability test passes comfortably (≥85%):
- `spotify_status` — What's currently playing, read-only Spotify token (dedicated account)
- `github_notifications` — Unread notifications, read-only fine-grained PAT
- `git_status` — Read-only `git status` / `git log` on a single user-configured repo path

**Security model for all V1 skills:**
- All read-only at the protocol level (no write endpoints configured)
- External integrations use dedicated accounts, never the user's primary accounts
- `file_search` confined to `sandbox/` directory by skill config
- macOS Calendar / Contacts app access denied at OS Privacy level
- Every invocation logged to audit log (ChromaDB)
- Skills marketplace (ClawHub) disabled entirely in OpenClaw config

**Explicitly NOT in V1** (deferred for safety / capability reasons):
- Email send/draft — write action, defer to V2 with cloud LLM
- Calendar event creation — same
- Music control (play/pause/skip) — write action, V2
- Browser automation — too complex for 1.5B
- Shell execution — security risk
- File modification — security risk
- Multi-step chained skills (e.g. "summarise my day") — 1.5B struggles with orchestration, V2
- Any third-party ClawHub skills — security risk (known malware reports; marketplace disabled)

**Skill audit log:** Every OpenClaw skill invocation is logged with timestamp, skill name, input parameters, and result. User can view audit log in web dashboard. Builds trust through transparency.

---

## V1 input model

```
Voice                Primary input — wake word, commands, dictation
Camera gestures      Acknowledgments + presence detection
ReSpeaker button     One physical button — wake / cancel / push-to-talk
Web UI (lumi.local)  Settings, system prompt, voice enrollment, modes, skills
```

**Why no mechanical buttons or rotary encoder in V1:** Pushed to V2. V1 is intentionally minimalist to ship faster and lean into the ambient voice+vision differentiator.

**Volume control:** voice commands + web UI slider (no physical dial in V1).

**Yes/No confirmation:** voice ("yes"/"no") + gestures (thumbs up/down).

**Mode switching:** voice ("switch to focus mode") + web UI dropdown.

---

## Development plan & milestones

Six-phase plan. Phases 1-4 happen on laptop before hardware arrives. Phases 5-6 happen with real Lumi hardware. Each phase has a measurable **gate criterion**.

### Phase 1 (Week 1) — Foundation + OpenClaw viability proof ✅ COMPLETE

**Tasks** ✓ all done
- Initialize GitHub repo, project structure per the directory layout below
- Set up dev environment: Python 3.11+, Node.js 20+, Whisper, Piper, Ollama
- Install Qwen2.5 1.5B via Ollama (`ollama pull qwen2.5:1.5b`)
  - Note: `qwen2:1.5b` does not support Ollama's tools API; use `qwen2.5:1.5b`
- Implement basic voice loop: mic → Whisper → Ollama → Piper → speaker (laptop)
- Install OpenClaw, configure with local Ollama as LLM provider
- Run tool-calling reliability test: 50 invocations across 5 simple skills
  - `weather`, `timer`, `file_search`, `unit_converter`, `wikipedia_lookup`
  - (email_read + calendar_read swapped out — need dedicated accounts first; tested separately after gate)
  - Track: success rate, latency, hallucination instances

**Deliverables** ✓ all done
- Repo with directory structure committed
- Working laptop voice loop demo (19/19 unit tests passing)
- `docs/openclaw-viability-report.md` — **47/50 (94%) PASS**

**🚦 Gate criterion: PASSED (94%)**
- Result: 47/50 across 5 skills — well above the 80% threshold
- weather 9/10, timer 8/10, file_search 10/10, unit_converter 10/10, wikipedia_lookup 10/10
- Avg latency ~350-500ms per tool call on MacBook (will be higher on Pi, test on Hailo in Phase 5)
- Key finding: `wikipedia_lookup` requires explicit "look up on Wikipedia" phrasing — model answers
  general knowledge questions directly (correct behavior, not a reliability issue)
- **Decision: OpenClaw stays in V1.**

---

### Phase 2 (Week 2) — Lumi runtime + OpenClaw integration

Build the core runtime that orchestrates voice, LLM, skills, and OpenClaw.

**Tasks**
- State machine: idle → wake → listen → think → speak → idle
- Mode system: General / Code / Focus / Dictation (mode pre-configures system prompt)
- Conversation manager with ChromaDB integration
- Speaker verification via Resemblyzer (voice enrollment + recognition)
- ~~Face engine rendering to laptop window (3 face style options)~~ — superseded by the React device-display pivot (2026-05-24). The face now lives at `src/lumi/ui/device_display/` (React/Vite/Tailwind) served at `/device-display/`. Four face styles: pixel, vector (system emoji), terminal (macOS-window chrome around the kawaii bear), and sprite (uses our existing sprite-pack pipeline).
- **Mock hardware abstraction layer** (camera/audio/USB-gadget paths only — display is no longer a Frame/SPI swap; Chromium kiosk owns the panel):
  - `MockGPIO`, `MockI2C`, `MockUSBGadget`, `MockCameraIO`
  - Clean interfaces so real drivers swap in later
- **LLM backend abstraction**:
  - `OllamaBackend` (dev), `HailoBackend` (production — stubbed for now)
  - Used by both Lumi runtime AND OpenClaw's custom provider
- **OpenClaw integration**:
  - Custom LLM provider for OpenClaw pointing to `OllamaBackend`
  - Skill router (native first, OpenClaw fallback)
  - Implement 5 curated skills with clear input/output contracts
- Skill audit log persistence to ChromaDB

**Deliverables**
- Lumi runtime accepts voice input, routes to skills, returns voice output
- 5 OpenClaw skills working end-to-end
- All 5 skills logged to audit log with full trace
- Face animations render correctly through all state transitions

**🚦 Gate criterion:** End-to-end voice → skill → voice loop works for all 5 curated skills with ≥80% success rate on demo prompts.

---

### Phase 3 (Week 3) — Web UI + skill management + onboarding

Build the lumi.local dashboard that handles onboarding and ongoing configuration.

**Tasks**
- FastAPI scaffold + mDNS for `lumi.local`
- HTMX-based UI with warm cream/amber palette
- **9-step onboarding flow**:
  1. First plug-in / welcome animation
  2. WiFi setup
  3. Name your Lumi (curated palette of 10-15 wake-word-friendly names)
  4. Voice enrollment (5 spoken prompts)
  5. Voice personality (3-4 Piper voices, each with sample)
  6. Face style (pixel / vector / terminal, live preview)
  7. Permissions (granular toggles per data source)
  8. Work mode (Developer / Writer / Student / General)
  9. First conversation
- **Skill management dashboard**:
  - List of all OpenClaw skills with enable/disable toggles
  - Per-skill permission configuration
  - Audit log viewer with filterable history
  - Test invocation panel for debugging
- Memory browser (ChromaDB contents, what Lumi knows about you)
- System prompt editor
- Settings persistence

**Deliverables**
- Complete onboarding flow walkthroughs cleanly on laptop
- User can enable/disable individual OpenClaw skills
- User can see exactly what each skill has done (audit log)
- Onboarding completes in ~10 minutes for a fresh user

**🚦 Gate criterion:** A fresh user (no engineer help) can complete onboarding and have their first conversation. Test this by handing the laptop to a friend.

---

### Phase 4 (Week 4) — Host PC helper + integration testing

Build the host-side helper that runs on the user's computer.

**Tasks**
- USB HID injection module (test against another laptop / VM)
- Clipboard reading (macOS / Windows / Linux)
- Active window detection (cross-platform)
- Send-to-Lumi global hotkey (Cmd/Ctrl+Shift+L) — simulates Cmd+C, reads selection, queues as context for the next conversation turn. Implementation in `src/lumi/host_helper/send_to_lumi.py`; CLI: `lumi hotkey`; HTTP twin: `POST /api/context`. Permission-gated on `clipboard_enabled`. Right-click menus + browser extension are V2.
- First-run helper app (USB mass storage trick simulation)
- End-to-end integration testing across all features
- **Failure mode hardening**:
  - Skill timeout (OpenClaw skill takes >10s)
  - LLM hallucination (output doesn't match expected schema)
  - Permission denial (skill tries to access disabled resource)
  - Network failure (WiFi-dependent skill while offline)
  - Audio device disconnect / reconnect
  - All failure modes return graceful user-facing messages
- Performance profiling: measure latency at each pipeline stage

**Deliverables**
- "Laptop Lumi" fully functional — looks and feels like the real product
- Documented failure modes with handling
- Performance baseline numbers (voice query latency, skill execution latency, memory usage)

**🚦 Gate criterion:** Full feature-complete laptop Lumi running stably for 1 hour of continuous demo use without crashes or major user-visible errors.

---

### Phase 5 (Week 5-6, hardware arrives) — Hardware integration

Migrate from laptop mocks to real Pi 5 + AI HAT+ 2.

**Reference deployment**: the proven Pi 5 + Hailo + OpenClaw stack at
[tishyk/hailo-ollama-openclaw-adapter](https://github.com/tishyk/hailo-ollama-openclaw-adapter)
(MIT, pinned to **OpenClaw 2026.04.20**, runs `qwen3:1.7b` on Hailo-10H).
Their setup confirms three things we need to know:

1. **OpenClaw versions matter.** Pin to `2026.04.20`; later releases broke
   concurrency handling and the auth-profile schema. We hit this exact bug
   on `2026.5.7` — the HTTP /v1/chat/completions endpoint surfaces skills
   via system-prompt text rather than tool_calls, which our 1.5B model can't
   drive. Pinning to 2026.04.20 OR using OpenClaw's dashboard/session API
   (not the bare HTTP shim) is the right path.
2. **Hailo isn't fully Ollama-compatible.** Hailo 5.3.0+ tightened its
   JSON parser (rejects control chars anywhere in the request),
   forbids literal newlines in content, rejects mid-stream system
   messages, and requires conversations to open on a user turn.
   tishyk's adapter is a 526-line FastAPI translator that handles all
   of this between OpenClaw and Hailo on port 11435.
3. **Skill orchestration happens in OpenClaw's session/dashboard layer**, not
   `/v1/chat/completions`. To make community OpenClaw skills work, Lumi needs
   to drive OpenClaw via its session API (or run a headless dashboard agent
   that Lumi proxies to). The thin HTTP shim we tried in V1 was the wrong
   integration surface.

**Adapter decision (audited 2026-05-23):** we **do not** install or run
tishyk's adapter as a process. Lumi V1 is the only thing on the Pi that
talks to Hailo (OpenClaw in V2 cloud mode points at a cloud provider,
not Hailo). All seven of Hailo's wire-protocol rules — deep
control-char strip, ASCII-encoded JSON, drop empty messages,
system-first-only, conversation-starts-on-user, history cap, content
cap — are handled in-process by `_normalize_messages` /
`_encode_for_hailo` in `src/lumi/llm/hailo_backend.py`. tishyk's repo is
the **source of the quirk list**, not a runtime dependency. If Hailo
5.4+ ships a new quirk, port the fix into `hailo_backend.py` directly.

**Tasks**
- Flash base Pi OS Lite 64-bit, set up Pi dev environment
- Install Node.js 20+ on Pi (for OpenClaw)
- **Install OpenClaw 2026.04.20** specifically (not latest):
  `pnpm add -g openclaw@2026.04.20`
- Configure ALSA with ReSpeaker 2-Mics HAT
- Install Hailo runtime, load LLM models in `.hef` format
- **HailoBackend talks to Hailo directly** on `:8000`. Already wired:
  `cfg.hailo_host` defaults to `http://127.0.0.1:8000`,
  `cfg.hailo_model` to `qwen3:1.7b`. To switch the runtime to the
  Hailo path set `LUMI_LLM_BACKEND=hailo` in the env (Pi-side only).
  Protocol normalisation runs locally — see
  `_normalize_messages` / `_encode_for_hailo`.
- **Migrate skill orchestration** from our V1 hybrid (Python tools registry
  + Ollama tool_calls) to OpenClaw's session API — community skills become
  available without per-skill Python ports.
- Validate tool-calling reliability still ≥80% on Hailo via the new path
- Configure USB gadget composite mode in `/boot/config.txt`
- Configure the Waveshare 3.5" SPI display as a framebuffer device
  (`fbcon=map:N` + `fbtft_device` for the panel) so a windowing system
  can target it
- Configure Camera Module 3 Wide via libcamera
- Configure I2C bus (for future modular sensor expansion)
- **Replace each mocked hardware driver with real implementation**:
  - `MockGPIO` → real GPIO
  - `MockI2C` → real I2C
  - `MockUSBGadget` → real libcomposite
  - `MockCameraIO` → real libcamera
  - `OllamaBackend` → `HailoBackend`
- **Install the Chromium kiosk autostart unit** (see `os-image/etc/systemd/system/lumi-display.service`). Pointed at `http://localhost:8080/device-display/`, kiosk-mode chrome, autorestart on crash.
- Install MediaPipe gesture model on AI HAT+ 2
- Performance and stress testing with all subsystems active

**Deliverables**
- All laptop features running on real hardware
- Performance benchmarks comparing laptop vs hardware
- Memory headroom validation (Pi 5 RAM usage with OpenClaw + everything)
- Stress test results: 30 min concurrent voice + gesture + skills

**🚦 Gate criterion:** Real Lumi hardware matches laptop Lumi behavior with ≤2x latency penalty on voice query loop. RAM usage stays under 6GB on Pi (well within 16GB budget).

---

### Phase 6 (Week 7-8) — Lumi OS image build

Package the whole thing into a flashable .img file users can install.

**Tasks**
- Set up `pi-gen` recipe in `os-image/stage-lumi/`
- Bake in:
  - Pi OS Lite 64-bit base
  - Python runtime + all dependencies
  - Node.js 20+ + OpenClaw + curated skills
  - All AI models pre-downloaded (Whisper, Piper, MediaPipe, Qwen2.5 .hef)
  - ReSpeaker HAT drivers configured
  - Camera Module 3 configured
  - Hailo runtime + LLM models
  - USB gadget mode in `/boot/config.txt`
  - log2ram pre-installed
  - mDNS for `lumi.local`
  - All systemd services enabled
  - First-boot onboarding flow
- CI/CD pipeline (GitHub Actions or local script)
- Image versioning + SHA-256 hashing
- Fresh-flash test: blank SD → flash → onboarding → first conversation

**Deliverables**
- `lumi-os-1.0.0.img` (~6-8GB compressed)
- Build documentation (anyone can reproduce)
- `docs/release-notes/v1.0.0.md`
- V1 release candidate

**🚦 Gate criterion:** A fresh SanDisk SD card flashed with the image boots into a fully functional Lumi within 5 minutes. Onboarding completes successfully on first try.

---

## The Lumi OS image

V1 ships as a **custom Pi OS image** (`.img` file), built with `pi-gen`. Users flash one file with Raspberry Pi Imager and Lumi just works. Same pattern as Home Assistant OS, OctoPrint, RetroPie, etc.

**Release versioning:**
```
lumi-os-1.0.0.img        First release
lumi-os-1.0.1.img        Patch (bug fixes, new vetted skills)
lumi-os-1.1.0.img        Feature update
lumi-os-2.0.0.img        Major (V2 hardware support, cloud LLM)
```

Each release ships with a SHA-256 hash for verification.

---

## Onboarding flow (summary)

```
Step 1  First plug-in           USB mass storage trick mounts a helper
                                 Welcome animation plays on device

Step 2  WiFi setup               Web UI captures credentials via helper
                                 Required for OpenClaw skill internet access

Step 3  Name your Lumi           Curated palette of wake-word-friendly names
                                 Each plays a voice sample
                                 Default: "Lumi"

Step 4  Voice enrollment         5 spoken prompts of varied length
                                 Generates speaker embedding (~192-d vector)
                                 Captures user's name in their own voice

Step 5  Voice personality        Pick Lumi's voice (3-4 Piper options)

Step 6  Face style               Pixel / vector / terminal — live preview

Step 7  Permissions              Granular toggles:
                                 - Active window title
                                 - Clipboard
                                 - Files (pointed-to only)
                                 - Camera (gestures + presence)
                                 - WiFi for skills
                                 - Each OpenClaw skill individually

Step 8  Work mode                Developer / Writer / Student / General
                                 Pre-configures system prompt + skill defaults

Step 9  First conversation       Lumi greets user by name
                                 Asks "What are you working on?"
                                 No tutorial — just talking
```

---

## Web UI structure

Served at `lumi.local` via mDNS. FastAPI backend + HTMX frontend.

```
/                       Dashboard — Lumi's current state, recent conversations
/onboarding             First-run flow (Steps 1-9)
/settings/personality   System prompt editor, voice picker
/settings/memory        Memory browser — what Lumi knows about you
/settings/data          Permission toggles per data source
/settings/face          Face theme picker
/settings/voice         Voice enrollment management
/settings/modes         General / Code / Focus / Dictation
/skills                 Skill management — enable/disable, audit log per skill
/skills/audit-log       Full audit log of all skill invocations
/dev                    Developer mode — logs, debug, hardware status
```

---

## Privacy & data handling

**V1 commitment: local-first.** LLM inference stays on device. WiFi is used only by OpenClaw skills the user explicitly enables.

**Where data lives:**
```
User conversations          → ChromaDB on microSD
Speaker voice embedding     → Single file on microSD
User preferences            → JSON on microSD
LLM context cache           → AI HAT+ 2 RAM (volatile)
Skill audit log             → ChromaDB on microSD
Camera frames               → Never stored, never persisted
                              Only landmarks used, frames discarded after inference
```

**External data access (OpenClaw skills only, with explicit user consent):**
- Email server (IMAP) — read-only, user's own account
- Calendar server (CalDAV) — read-only, user's own account
- Weather API — public, no user data sent
- All skill network traffic logged in audit log

**Camera-active indicator:** NeoPixel on ReSpeaker HAT lights red when camera is active. Manual 3D-printed privacy cap for V1; integrated slider shutter for V2.

**Data export:** Export everything (conversations, embeddings, preferences, audit log) as a single archive via web UI.

**Data deletion:** "Forget everything" option wipes all user-specific data and resets to first-boot state without reflashing.

**On-disk perms:** `data_dir` is chmod 0700 and the canonical sensitive
files (`user_settings.json`, `audit_log.jsonl`, `owner_embedding.npy`,
`.pending_context.json`, `perf_log.jsonl`, `notes.jsonl`,
`journal.jsonl`) are 0600 — applied on every launch via
`runtime/storage.py:secure_data_dir()` so legacy installs tighten on
first boot under the new code.

**`~/.openclaw/openclaw.json`** mirrors the cloud LLM API key (OpenClaw
2026.04.20 doesn't read from a keychain). Written atomically with mode
0600 by `openclaw_operator._write_config_securely()`. Clearing the key
in `/settings/cloud` also purges every provider block from the file —
the key doesn't survive on disk after the user clears it.

**PII pseudonymization (cloud mode):** `runtime/privacy.py:Pseudonymizer`
masks emails, phones, SSN/ZIP, IPv4/IPv6, MAC, IBAN, US street
addresses, DOB (labelled), credit cards (Luhn-checked), JWTs,
AWS/GitHub/Google/Slack API keys, bearer-prefixed tokens, and the owner's
name plus any user-supplied vocabulary. Optional Presidio NER for
general person-name detection. Stable per-session pseudonyms
(`<EMAIL_1>`, `<PERSON_1>`). The pseudonymizer is constructed in
`runtime/session.py:build_cloud_bridge()` and threaded to:
- `OpenClawBridge` (masks `--message` argv before subprocess)
- `SkillRouter` (masks audit-log entries in cloud mode)
- `ConversationManager` (masks memory snippets on retrieval — defence in
  depth, since the conv manager only talks to the local backend today)

**Audit log integrity:** `get_recent()` skips individual corrupt JSON
lines instead of failing the whole read, so a crashed write doesn't
blank the viewer.

**Structured logs never carry raw user content** — conversation/assistant
text and active-window titles are reduced to `chars=<n>` fields. The
audit log is the only place content lives, and it's masked in cloud mode.

---

## Invariants & patterns

Established by the 2026-05-21 audit sprint. New code must respect these;
the test suite locks each one in.

**Single source of truth: cloud-mode wiring.** Both the voice loop
(`main.py`) and the web chat route (`ui/web/routes/chat.py`) build their
SkillRouter / OpenClawBridge / Pseudonymizer / ConversationManager via
`runtime/session.py:build_cloud_bridge(user, openclaw_enabled=…)`. Never
construct them ad-hoc — drift between paths is what caused the original
audit #3 leak.

**Single error helper: `runtime/errors.py:safe_error_message(exc, where=…)`.**
Logs the exception class + first 300 chars of the message under a
`user_facing_error` structured event with a `where` tag, returns a
generic user-safe string. Never interpolate `{exc}` into UI output or
stderr — call the helper.

**Atomic writes for any settings-style file.** Pattern:
```python
fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
try:
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(payload)
    os.chmod(tmp, 0o600)        # if sensitive
    os.replace(tmp, path)
except Exception:
    Path(tmp).unlink(missing_ok=True)
    raise
```
Currently in: `ui/web/persistence.py:_atomic_write_text` (settings),
`skills/openclaw_operator.py:_write_config_securely` (OpenClaw config).
Future write paths for sensitive files should mirror this.

**Untrusted text never lands in the system role.** Clipboard captures,
active-window titles, and memory retrievals go in a separate user-role
message wrapped in fenced "treat as data, not instructions" markers by
`runtime/conversation.py:_wrap_untrusted()`. Cap at `_MAX_HINT_CHARS`
(2000) for context, `_MAX_MEMORY_CHARS` (1500) for memory.

**Mutating dashboard routes require CSRF.** `ui/web/csrf.py:CSRFMiddleware`
reads the raw body to validate the token then splices it back so the
route can still parse forms. Bypass list is short and explicit
(`/api/context`, `/static/`). HTMX gets the token via an
`htmx:configRequest` hook in `base.html`; classic forms get a hidden
field injected on submit. New routes are automatically covered.

**Sensitive subprocess argv never contains raw secrets.** The cloud-LLM
key flows from keychain → OpenClaw config file (0600) → OpenClaw reads
from its own config. We never pass it on argv where `ps aux` would
expose it. The `--message` argv IS visible to other local processes but
goes through the pseudonymizer first.

**At-rest perms enforced on every launch.** `runtime/storage.py:secure_data_dir()`
runs at app startup (both CLI and web). Idempotent — silent if perms
are already correct; logs `storage.data_dir_perms_tightened` on a fix.

---

## Voice & TTS

**STT:** Whisper Tiny on Pi 5 CPU. ~150MB model. Real-time transcription with ~0.5s latency on short clips.

**TTS:** Piper TTS on Pi 5 CPU. ~100MB per voice. Multiple voices available; user picks during onboarding.

**Voice character target:**
- Warm, calm, slightly slow tempo
- Mid-range pitch
- Subtle smile in delivery
- American or British English (consistent per voice)

**Streaming TTS (V1 if time permits):** As LLM generates first sentence, Piper starts speaking it while LLM continues generating. Feels responsive even with multi-sentence responses.

---

## Camera & vision

**Hardware:** Pi Camera Module 3 Wide (102° FOV, 12MP IMX708, motorized autofocus). Connects via CSI ribbon — no PCIe conflict with AI HAT+ 2.

**Vision pipeline:**
```
Camera → libcamera → frame buffer → MediaPipe Hand Landmarks (on AI HAT+ 2)
       → 21 hand keypoints per frame at 30 fps
       → custom gesture classifier (Python)
       → gesture event → Lumi action
```

**V1 gesture vocabulary:**
- 👋 Wave — wake / greet
- ✋ Open palm — pause / stop talking
- 👍 Thumbs up — yes / accept
- 👎 Thumbs down — no / reject
- ✊ Closed fist — cancel / dismiss
- Presence detection (no gesture) — auto-wake when user sits down, sleep when user leaves

**Privacy by design:**
- Frames never written to disk
- Only 21-point hand landmarks used (frames discarded immediately)
- NeoPixel indicator when camera active
- Easy disable via button or web UI

---

## Storage strategy

**Single microSD card holds everything:** OS, application code, all AI models, ChromaDB, conversation history, user data, OpenClaw + skills.

**Card spec:** SanDisk Extreme Pro 256GB A2 (or equivalent). 200MB/s read, 90MB/s write, 4000 IOPS.

**Why microSD is sufficient (not a compromise):**
- LLM runs entirely from AI HAT+ 2's onboard 8GB RAM (never hits disk)
- Models load once at boot into Pi RAM
- ChromaDB queries are RAM-cached after warmup
- Writes are tiny (kilobytes per conversation + small audit log entries)

**Write protection: log2ram pre-installed.** Reduces SD card writes by ~95%.

**Backup strategy (V2):** Nightly automated backup of user data to user's chosen cloud or local PC folder. V1 keeps data local only.

---

## V2 roadmap

Features deferred from V1 to keep V1 shippable:

| Feature | Notes |
|---|---|
| Mechanical key switches (NeoKey 1x4 + Kailh Brown + keycaps) | Premium tactile inputs |
| Rotary encoder + knob | Volume + mute dial with NeoPixel ring |
| Cloud backup integration | Sync to user's Drive / Dropbox / iCloud |
| ElevenLabs premium voice option | Higher-quality TTS as paid upgrade |
| Cloud LLM fallback with intelligent routing | Lumi tries the local LLM first; if confidence/quality is low, escalates the same turn to a configured cloud provider. Admin console (V1) already collects provider (Anthropic / OpenAI / Gemini), API key, and model name; V2 wires the routing. Architecture: a new `RoutedBackend` wraps `OllamaBackend` (or `HailoBackend`) plus the cloud client and decides per turn. Decision signal candidates: local model self-evaluation, length/topicality heuristics, explicit user marker, or a small classifier. Each cloud call logged in audit log as `source=cloud:{provider}`. Only the current turn + recent history + system prompt are sent — never the memory store, audit log, clipboard, or voice embedding. |
| ~~**PII masking + pseudonymization before cloud calls**~~ **(SHIPPED 2026-05-21)** | `src/lumi/runtime/privacy.py:Pseudonymizer` masks emails, phones, SSN, ZIP, IPv4/IPv6, MAC, IBAN, US street addresses, DOB, credit cards (Luhn-checked), JWTs, AWS/GitHub/Google/Slack/Bearer tokens, and `extra_names` (owner name from onboarding). Optional Presidio NER for general person names. Wired via `runtime/session.py:build_cloud_bridge()` into the cloud subprocess argv, the audit log, and (defence in depth) memory retrievals. Per-session mapping; resets across sessions. **Still V2:** per-skill toggle so `gmail_read` can opt out of masking when it needs real values. |
| Cloud LLM as the OpenClaw operator (V2 unlock for community skills) | Proven the long way: we tested OpenClaw 2026.04.20 + qwen2.5:1.5b/qwen3:1.7b/llama-3.1:8b/qwen2.5:7b. We also verified that **SKILL.md manifests are NOT callable tools** — they're documentation text in the system prompt. To make a skill actually callable we wrote a proper OpenClaw JS plugin (`openclaw-service/plugins/lumi-weather/`: `package.json` + `openclaw.plugin.json` with `configSchema` + `index.js` calling `api.registerTool` from `openclaw/plugin-sdk/plugin-entry`), dropped it into `~/.openclaw/extensions/`, added it to `plugins.allow`, and confirmed via `npx openclaw agent` that the tool **does** appear in the model's tool list. Directly hitting `POST /tools/invoke {tool: "get_weather", args: {...}}` returns real OpenWeatherMap data, so the plugin execution path works. **But qwen2.5:7b still doesn't invoke the tool** — it sees it in the list, then hallucinates a fabricated result instead of emitting a tool_call. The root cause: OpenClaw's system prompt is ~13K tokens of bootstrap/persona/memory guidance; small models choose "roleplay" over "invoke" under that prompt weight. The viability test's 94% reliability was against a SHORT prompt with ONE tool, not OpenClaw's heavy agent loop. Conclusion: full OpenClaw runtime needs cloud LLM (Claude/GPT) or a 30B+ local model. Hailo's 8 GB VRAM can't fit 30B+ at acceptable latency. Architecture: `OpenClawBridge.runtime_mode = "ollama" \| "openclaw_cloud"`. Cloud mode proxies through `npx openclaw agent --agent main --message ...` with the cloud API key wired into OpenClaw's `models.providers.<provider>.apiKey`. V1 hybrid (Python execution via direct Ollama tool_calls) remains the right design for the local-only fallback. The plugin layer we built unlocks the moment cloud LLM is configured. |
| **Expanded OpenClaw skill set** | Write actions (email send, calendar create, music control), multi-step chained skills, Home Assistant control — needs cloud LLM |
| **MCP protocol integrations** | Connect directly to MCP servers (Google Drive, Slack, etc.) |
| Premium enclosure | Frosted translucent shell, underside glow, matte finish |
| Physical privacy shutter | Integrated slider over camera lens |
| Custom wake-word training | User picks any name |
| Multi-user voice profiles | Household members can be enrolled |
| Sound design | Startup chime, listening tone, confirmation chimes |
| Onboard fine-tuning | Adapt to user's writing style |
| Claude Code integration | Developer-focused features |
| **Send-to-Lumi tier 3 (right-click menu)** | macOS Services bundle (`NSServices` plist), Windows registry helper, Linux DE-specific menu entries. V1 ships tier 1+2 (global hotkey + simulated-copy selection capture) which covers the major UX; right-click is per-platform fiddly for marginal gain. |
| **Send-to-Lumi tier 4 (browser extension)** | Chrome/Firefox extension with right-click "Ask Lumi about this". Best UX inside the browser since it doesn't depend on Accessibility permissions. Half-a-day each browser; deferred to V2. |
| **Chat UI — optimistic send** | Today: hitting Enter waits until the model replies before showing your message in the chat. Should render your message *instantly* on submit, then stream the reply into a placeholder. ~2h with HTMX SSE or a small JS layer. |
| **Chat UI — streaming responses** | Today: full response posts once the LLM is done. With qwen2.5:7b that's 4-10 seconds of dead air. Pipe `ConversationManager.stream_chat()` through `text/event-stream` so tokens render as they arrive. ~3h. |
| **Skills marketplace search** | Native skill or LLM tool that runs `npx openclaw skills search <query>` and offers to install matches. Lets Lumi say "you don't have a Spotify skill — want me to install the openclaw spotify-player one?" mid-conversation. Requires `openclaw_skills_enabled` permission gate so it can't silently install code. ~half-day. |
| **Chat streaming endpoint hangs under sustained load** *(found 2026-05-23)* | Phase 4 soak (60 min, mock backend, 5-second cadence) ran cleanly for ~11 min then `/chat/stream` started timing out — 84 ReadTimeouts piled up over the next 49 min. Server process stayed alive, no 5xx, no FD/RSS leak, no exceptions in logs. Latency p95 drift 3.09× (gate threshold 2×). Real user cadence (1-3/min with idle stretches) wouldn't hit this. Likely a StreamingResponse + `loop.run_in_executor` interaction in `chat.py:chat_stream` under sustained concurrent open generators. Investigation plan: reproduce with a shorter, more aggressive soak; check for executor thread starvation; consider moving `next(gen)` off the default executor or making the chunk generator natively async. ~2-3h to root-cause + fix. |
| **Sprite-pack uploader** | `/settings/sprites` page: list existing sprite folders in `data/sprites/`, upload form (ZIP or PNG frames + manifest.json), delete button. Auto-populates the idle scene dropdown. Validates PNG-only, size caps, safe folder names. User-requested ("tamagotchi customization"). ~2-3h. |
| **Pixel face redesign** | The pink-heart-with-blush-and-smiley reads off. User to source inspiration; we redo when there's a clear direction. |
| **Bear face glyph coverage** | `ʕ ᴥ ʔ` work everywhere we tested, but some bundled fonts on Pi OS don't have `ᴥ` (IPA Letter Ain). Bundle a known-good TTF (DejaVu Sans Mono is on the Pi by default; might still need an explicit path) or swap the `ᴥ` mouth glyph for something more universal. |
| **Post-train a small model to emit tool_calls reliably under OpenClaw's agent prompt** *(research, ~weeks)* | The blocker that pushed full OpenClaw runtime to V2 is purely behavioural: qwen2.5:7b and friends *see* the tools in OpenClaw's ~13K-token system prompt but choose to roleplay an answer instead of emitting a `tool_call`. The capability is there (94% on our short-prompt viability test), the *habit* isn't. A focused fine-tune could plausibly fix this without needing a cloud LLM. Approach: (1) collect a few thousand (prompt → tool_call) pairs by running real cloud LLMs (Claude/GPT) against OpenClaw's heavy prompt with our plugin set and capturing their tool_call outputs; (2) SFT a 1.5B–8B base (qwen2.5 / llama-3.2) on those traces using LoRA on the JSON-emission turns only — keep the chat behaviour out of training; (3) optionally DPO with negative examples (the roleplay completions we see today) ranked below the matched tool_calls. Eval: re-run the OpenClaw viability harness against the heavy agent prompt at ≥80% to clear V1's bar. Hardware: a single H100 hour should cover a LoRA on 8B; everything else fits on Hailo at inference time. Why this matters: if it works, V1 hybrid stops being the floor and the full OpenClaw runtime + 100+ community plugins becomes the default on-device experience, no cloud required. Risk: even after fine-tune, a 1.5B may not generalize to *novel* tools added post-training — needs a continual-learning loop (auto-finetune on tool_call traces from user-installed skills). |

---

## Project structure

```
lumi/
├── CLAUDE.md                    # This file — cross-session AI context
├── README.md                    # Public-facing intro + portfolio piece
├── LICENSE
├── pyproject.toml               # Python deps + tooling
├── package.json                 # Node deps (for OpenClaw glue code)
│
├── docs/
│   ├── architecture.md
│   ├── openclaw-viability-report.md   # Phase 1 deliverable
│   ├── onboarding-flow.md
│   ├── voice-design.md
│   ├── privacy.md
│   ├── skills/
│   │   ├── native-skills.md
│   │   └── openclaw-skills.md
│   └── decisions/               # ADRs for major decisions
│
├── src/lumi/
│   ├── __init__.py
│   ├── main.py                  # Entrypoint
│   ├── runtime/
│   │   ├── state_machine.py
│   │   ├── conversation.py
│   │   ├── modes.py
│   │   └── memory.py            # ChromaDB integration
│   ├── audio/
│   │   ├── stt.py               # Whisper
│   │   ├── tts.py               # Piper
│   │   ├── wake_word.py
│   │   └── voice_id.py          # Speaker verification
│   ├── vision/
│   │   ├── camera.py
│   │   ├── gestures.py
│   │   └── presence.py
│   ├── llm/
│   │   ├── backend.py           # LLMBackend protocol
│   │   ├── ollama_backend.py    # Dev backend
│   │   ├── hailo_backend.py     # Production backend
│   │   └── prompts.py
│   ├── skills/
│   │   ├── router.py            # Skill routing logic
│   │   ├── native/              # Fast Python skills
│   │   │   ├── timer.py
│   │   │   ├── mode_switch.py
│   │   │   └── ...
│   │   └── openclaw_bridge.py   # HTTP client to OpenClaw service
│   ├── ui/
│   │   ├── face/                # Sprite-pack metadata (idle_scenes.py
│   │   │                        # owns the bundled+user-dir resolution).
│   │   │                        # The pygame face renderers (pixel.py,
│   │   │                        # vector.py, terminal.py, chrome.py,
│   │   │                        # engine.py) are slated for removal —
│   │   │                        # React device display owns rendering now.
│   │   ├── web/                 # FastAPI + Jinja/HTMX dashboard
│   │   │   ├── routes/          # Each dashboard area as a router
│   │   │   ├── device_bus.py    # In-process SSE broadcaster
│   │   │   ├── csrf.py          # SameSite=Strict middleware
│   │   │   └── persistence.py   # user_settings.json (atomic writes)
│   │   └── device_display/      # React/Vite/Tailwind app — the Lumi
│   │                            # screen. Built into ../web/static/
│   │                            # device-display/, served at /device-
│   │                            # display/. Chromium kiosk renders it
│   │                            # on the Pi.
│   ├── hardware/
│   │   ├── audio_io.py          # ReSpeaker (with mock)
│   │   ├── camera_io.py         # CSI camera (with mock)
│   │   ├── gpio.py              # GPIO (with mock)
│   │   └── usb_gadget.py        # USB composite (with mock)
│   └── host_helper/
│       ├── hid_inject.py
│       ├── clipboard.py
│       └── active_window.py
│
├── openclaw-service/            # Node.js OpenClaw configuration
│   ├── package.json
│   ├── lumi-llm-provider.js     # Custom LLM provider (Ollama dev, Hailo prod)
│   ├── enabled-skills/          # Curated skill manifests
│   └── README.md
│
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── openclaw/                # OpenClaw viability tests
│   └── hardware/                # Run only on real Pi
│
├── os-image/                    # pi-gen recipe
│   ├── stage-lumi/
│   ├── build.sh
│   └── README.md
│
└── scripts/
    ├── dev-setup.sh
    ├── flash-image.sh
    └── openclaw-viability-test.sh
```

---

## Decision log

Key decisions made during design, with reasoning. Future sessions: do not re-litigate without strong cause.

| Decision | Reasoning |
|---|---|
| **Pi 5 16GB** (vs 4GB/8GB) | Comfortable RAM headroom for Whisper + Piper + ChromaDB + OpenClaw + future. |
| **AI HAT+ 2** (vs original AI HAT+) | 40 TOPS + 8GB dedicated RAM = LLM-capable. Vision still excellent. |
| **microSD only** (no NVMe, no external SSD) | AI HAT+ 2 takes PCIe lane. External SSD kills portability. Workload doesn't need NVMe. |
| **microSD + log2ram** | Mitigates write wear. Standard pattern in Pi production projects. |
| **Pure onboard LLM** (V1) | No cloud dependency for inference. Simpler architecture. Stronger brand. |
| **OpenClaw included in V1** | Industry standard agent framework. Memory separation makes it feasible (LLM on HAT, OpenClaw on Pi RAM). Gives users a rich skill ecosystem out of the box. |
| **Curated skill set for V1** | Small LLM (1.5B) can't reliably orchestrate complex multi-step skills. Limit to simple single-step, read-only skills for safety and reliability. |
| **Dedicated accounts for all external integrations** | Never use the user's primary email/calendar. Dedicated accounts mean a compromised skill can only access a limited, purpose-built inbox/calendar. |
| **`sandbox/` directory for file access** | `file_search` is confined to `sandbox/` (gitignored, local-only). User drops files there manually. No open filesystem access. |
| **macOS Calendar/Contacts access denied at OS level** | CalDAV skill hits a remote endpoint (dedicated Google account); it has no legitimate reason to touch the local macOS Calendar app. Deny at System Privacy. |
| **No third-party ClawHub skills** | Documented security incidents (ClawHavoc, ~20% malicious plugins per Cisco). Only Lumi-vetted skills shipped. |
| **Custom LLM provider for OpenClaw** | Lets OpenClaw use our Hailo NPU (production) or Ollama (dev). Same interface, swappable backend. |
| **Qwen2.5 1.5B** (not Qwen2 1.5B) | `qwen2:1.5b` does not support Ollama's tools API. `qwen2.5:1.5b` does (94% tool-call accuracy in Phase 1 gate test). |
| **Tool-calling tested via Ollama directly** | OpenClaw gateway does not forward external tool definitions — it routes through its own skills system. Model-level tool calling is tested via Ollama's native API (`/api/chat`). |
| **Hailo protocol bridge runs in-process, not as a separate adapter** (2026-05-23) | Considered `pip install tishyk/hailo-ollama-openclaw-adapter@2026.04.20` as a runtime dep but rejected on three counts: (a) Lumi V1 is the only thing on the Pi talking to Hailo (OpenClaw in V2 cloud mode points at a cloud provider, not Hailo), so the adapter would be a redundant network hop; (b) tracking a third-party pin in our critical path adds maintenance risk if upstream goes quiet; (c) the four extra rules we needed beyond what we already had (deep-sanitize, ASCII-encoded JSON, empty-message filter, user-first-turn) total ~30 lines of Python. tishyk's repo remains the **source of the quirk list** for future Hailo SDK releases — port new quirks into `hailo_backend.py` directly. |
| **wikipedia_lookup needs explicit phrasing** | Model answers general knowledge questions directly (correct). Skill activates on "look up X on Wikipedia" style prompts, not bare factual questions. |
| **Skill router (native first, OpenClaw fallback)** | Native skills are fast and reliable for simple commands. OpenClaw extends reach but with more overhead. |
| **ReSpeaker 2-Mics HAT** | Single board replaces three components. Better integration. |
| **No mechanical buttons in V1** | Pushed to V2. V1 leans into voice + gesture as the differentiator. |
| **Camera Module 3 Wide** (vs AI Camera IMX500) | AI HAT+ 2 is more capable; AI Camera redundant. Wide FOV needed for desk gestures. |
| **Curated wake-word palette** (vs custom training) | Pre-trained = reliable. Custom training has poor accuracy. |
| **Lumi OS image distribution** | Same pattern as Home Assistant OS, OctoPrint. Professional, consistent. |
| **No cloud backup in V1** | V1 is local-only. Backup is V2 feature with user's own cloud accounts. |
| **3.5" Waveshare SPI display** | Best balance of size, drivers, cost. Square-ish form factor works for face. |
| **Pi OS Lite 64-bit** | Headless, minimal, fast boot. We build our own UI. |
| **Piper TTS** (vs ElevenLabs in V1) | Local, free, good quality. ElevenLabs is V2 premium tier. |

---

## Open questions (TBD)

Surface to user when relevant.

- **OpenClaw viability with Qwen2.5 1.5B** — ✅ RESOLVED: 94% (47/50). OpenClaw stays in V1.
- **Specific LLM model choice for V1** — Qwen2.5 1.5B confirmed for dev. Test `.hef` quantization on Hailo in Phase 5; fallback to Llama 3.2 1B if needed.
- **Wake word palette** — Initial candidates: Lumi, Aria, Nova, Sage, Atlas, Iris, Juno, Hugo, Echo, Pip. Need to test which pre-trained models work cleanly.
- **Piper voice selection** — Listen through candidates and pick 3-4 matching the warm/calm brand.
- **Face style designs** — Need actual designs for pixel / vector / terminal.
- **Onboarding system prompts** — Per work mode (Developer / Writer / Student / General).
- **CSI ribbon cable** — Pi 5 uses smaller CSI connector than Camera Module 3 ships with. Verify adapter needed.
- **3D-printed manual privacy cap** — V1 trust signal — needs design.
- **OpenClaw service startup time** — Adds to Pi boot time. Acceptable threshold?
- **Skill timeout default** — How long before a stuck skill is killed? (Default 10s, configurable per skill)

---

## Working with Claude on this project

This file is the source of truth for project context across AI sessions. When working with Claude (in Claude Code, claude.ai, or elsewhere) on Lumi:

**Update this file when:**
- A major architecture decision is made
- A V1 vs V2 scope change happens
- An open question gets resolved
- A new constraint or learning emerges
- A phase gate criterion result comes in

**Don't add to this file:**
- Implementation details that belong in code comments
- Temporary debug notes
- Credentials, API keys, or secrets

**Tone for AI sessions:**
- Push back on suggestions that compromise V1 simplicity
- Question additions that don't fit the warm/calm/private brand
- Verify hardware claims against current 2026 reality
- Don't re-litigate decisions in the Decision Log without strong new information
- Respect the phase gate criteria — they exist to prevent scope creep

**Pre-hardware work focus:** Build the laptop version of Lumi first. Mock all hardware interfaces cleanly so the swap to real hardware is a driver replacement, not a rewrite. The OpenClaw viability check in Phase 1 is the most important early decision — let it determine V1 scope honestly.
