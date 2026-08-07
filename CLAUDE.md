# Lumi

> Your AI companion. Always on. Always yours.

Lumi is a portable physical AI desk companion that plugs into any computer via USB-C. It runs an LLM locally on dedicated AI hardware, listens through onboard microphones, speaks back through an onboard speaker, watches for gestures through an onboard camera, and shows a friendly animated face on a small display. The whole experience is meant to feel warm, calm, and deeply personal — an AI that lives on your desk, knows you, and never sends your data anywhere it doesn't have to.

---

## Project status

**Pre-hardware design phase.** Core architecture is settled; the **AI HAT+ 2
is the one open hardware decision** (optional, pending a Pi-CPU vision
benchmark — see Open questions). Plan (2026-06-20): order the **16GB Pi 5**
now; the LLM is **cloud-primary with a small Pi-CPU local model** as the
offline/private floor. Software runs on a laptop; the
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
- Local-first AI (a private on-device model floor runs on the Pi CPU; the cloud LLM is opt-in, not required)
- Ambient awareness via camera and microphones
- Owns its data — your conversations, embeddings, and preferences live on the device
- Extensible via OpenClaw's skill ecosystem (curated for safety in V1)

---

## Architecture overview

Lumi runs **cloud-primary** for V1's smart replies, with a **small local LLM on the Pi 5 CPU** as the private/offline floor + router. WiFi carries cloud-LLM turns and OpenClaw skills that need network access (email, calendar, weather, etc.); the CPU floor keeps Lumi working with no network and no cloud key. *(The diagram below shows the maximal config with the optional AI HAT+ 2 installed; in the current baseline the LLM is cloud + Pi-CPU — not the HAT — and the HAT itself is pending the vision benchmark.)*

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
│  │  (DSI bus)  │    │              │    │  (analog)       │    │
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
- **Pi 5 (16GB system RAM)**: OS, Lumi Python app, Whisper, Piper, ChromaDB, FastAPI, **OpenClaw service (Node.js)**, audio pipeline, MediaPipe vision (CPU), the **CPU tiny-LLM floor** (~1 GB resident), and the **Chromium kiosk** rendering the device display from `localhost:8080/device-display/`. ~12–13 GB free at idle; Chromium adds ~500-800 MB and the local model ~1 GB — still comfortable margin.
- **AI HAT+ 2 (8GB dedicated RAM) — optional**: if added (pending the vision benchmark), it offloads MediaPipe vision off the CPU. Isolated memory pool that is **not** addable to Pi system RAM, and **not** the LLM host in the current plan (cloud + Pi CPU handle inference). HEF conversion required for any model run on it.

**Why 16GB:** with the LLM back on the Pi CPU and the HAT no longer assumed present, the 16 GB system pool carries everything — OpenClaw, FastAPI, Chromium, ChromaDB, and a ~1 GB CPU-resident model — with comfortable headroom (~12–13 GB free at idle; a V2-heavy peak with full OpenClaw + MCP + grown ChromaDB still leaves multiple GB). The HAT's isolated 8 GB can't be borrowed for these general-compute workloads, which is why **system RAM (not the HAT) is the binding resource** — and why the 06-15 downgrade to 8GB was reversed once the LLM moved off the HAT.

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

**Data flow (gesture):** see the full "Camera & vision" section below for
the actual three-process pipeline (capture shim → shared memory →
MediaPipe worker) and the exact wake-vs-display-only split per gesture.

---

## V1 hardware

| Category | Component | Purpose |
|---|---|---|
| **Core compute** | Raspberry Pi 5 (16GB) | Main computer, runs Lumi OS + OpenClaw + the CPU tiny-LLM floor |
| | Raspberry Pi AI HAT+ 2 *(optional — pending vision benchmark)* | Vision offload **only if** the Pi CPU can't keep up (40 TOPS, 8GB onboard RAM); LLM is cloud + Pi CPU, not the HAT |
| | Active cooler for Pi 5 | Thermal management (required) |
| **Storage** | SanDisk Extreme 256GB A2 V30 microSD (`SDSQXAV-256G-GN6MA`) | OS, models, ChromaDB, user data |
| **Display** | Raspberry Pi Touch Display 2 (7", run landscape 1280×720) in a SmartiPi Touch Pro 3 enclosure | Lumi's animated face + the finished product shell |
| **Audio** | ReSpeaker 2-Mics Pi HAT V2.0 | **Speaker output + the physical button (GPIO17)**. Its onboard mics are NOT used (capture moved to an external USB mic, 2026-08-06) and its 3 RGB LEDs are unusable — the HAT is sealed inside the case, so nothing on it is visible or audible. |
| | External USB mic (`Generalplus`, ALSA card id `Device`) | **Voice input.** Mounted outside the enclosure. 44.1/48 kHz only — no 16 kHz, hence `audio/resample.py`. |
| | 3-5W 4Ω speaker with JST connector | Voice output — mounted **outside** the case, not firing through a rear vent |
| **Camera** | Pi Camera Module 3 Wide | Gestures + presence detection (102° FOV, autofocus) |
| | CSI ribbon cable (Pi 5 15→22-pin, CAM variant) | Camera on the Pi 5's 2nd MIPI port |
| | DSI ribbon cable (Pi 5 22-pin) | Display on the Pi 5's 1st MIPI port |
| **Power & wiring** | USB-C to USB-C cable (1m, braided) | Connection to host PC |
| | Pi 5 official 27W USB-C power supply | Power during dev / when not host-powered |
| | Premium jumper wire kit | General prototyping |
| **Structure** | M2.5 standoffs + screws kit | HAT stacking |
| | Acrylic mounting plate | Bare-bones V1 base |
| | Self-adhesive rubber feet | Non-slip base |

**PCIe lane usage:** The single PCIe lane is reserved for the AI HAT+ 2 *if* it's fitted (pending the vision benchmark); if the HAT is skipped the lane is free. Either way NVMe is intentionally not used — onboard storage is microSD only.

---

## V1 software stack

```
Layer                     Component                  Notes
─────────────────────────────────────────────────────────────────────────
Operating system          Raspberry Pi OS Lite       64-bit, headless
                          (Bookworm or Trixie)

Runtime                   Python 3.11+               Lumi core
                          Node.js 22.14+                OpenClaw service

Speech-to-text            Whisper Tiny               ~150MB, runs on Pi CPU
                                                      ~0.5s for short clips

Text-to-speech            Piper TTS                  ~100MB, runs on Pi CPU
                                                      Warm voice personality

Wake word                 OpenWakeWord or Porcupine  Local detection
                          (curated name palette)      "Hey Lumi" + alternatives

Local LLM (floor)         Qwen2.5 1.5B /             Runs on the Pi 5 CPU
                          Llama 3.2 1B               (~7-15 tok/s). Private/
                                                      offline floor; cloud LLM
                                                      is the opt-in ceiling.
                                                      (qwen2:1.5b lacks tool support)
Cloud LLM (ceiling)       Anthropic / OpenAI /       Opt-in API key; handles hard
                          Gemini                     turns via RoutedBackend

Vision                    MediaPipe Hand Landmarks   Runs on Pi 5 CPU
                          + custom gesture classifier ~5-15 fps (enough for
                                                      held poses; HAT/HEF
                                                      offload optional later)

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

**Service architecture (systemd units, as actually deployed on the Pi):**
- `lumi-web.service` — FastAPI dashboard + device display (`:80`)
- `lumi-voice.service` — voice loop (wake word → STT → LLM → TTS)
- `lumi-display.service` — Chromium kiosk rendering `/device-display/`
- `lumi-vision.service` — vision worker (MediaPipe hand-landmark
  gestures + presence), separate Python 3.12 venv (protobuf 4.x, can't
  share `lumi-web`'s chromadb-driven protobuf 7.x)
- `lumi-vision-capture.service` — camera capture shim, runs under the
  Pi's *system* Python (3.13) where `picamera2`/`libcamera`'s compiled
  bindings live; mediapipe has no wheel for that Python version on any
  platform, so capture and inference are split into two processes
  bridged by POSIX shared memory (see `vision-worker/capture_shim/`)

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
- Set up dev environment: Python 3.11+, Node.js 22.14+, Whisper, Piper, Ollama
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
- Install Node.js 22.14+ on Pi (for OpenClaw)
- **Install OpenClaw 2026.04.20** specifically (not latest):
  `pnpm add -g openclaw@2026.04.20`
- Configure ALSA with the ReSpeaker 2-Mics HAT
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
- Configure the **Raspberry Pi Touch Display 2** (7", run **landscape
  1280×720** — rotate native 720×1280) via its DSI/KMS overlay so the
  Chromium kiosk renders to it. One of the Pi 5's two MIPI ports is the
  display (DSI), the other is the camera (CSI) — both active
  simultaneously. Mount it in the **SmartiPi Touch Pro 3** enclosure.
- Configure Camera Module 3 Wide via libcamera
- Configure I2C bus (for future modular sensor expansion)
- **Replace each mocked hardware driver with real implementation**:
  - `MockGPIO` → real GPIO
  - `MockI2C` → real I2C
  - `MockUSBGadget` → real libcomposite
  - `MockCameraIO` → real libcamera
  - `OllamaBackend` → `HailoBackend`
- **Install the Chromium kiosk autostart unit** (see `os-image/etc/systemd/system/lumi-display.service`). Pointed at `http://localhost:8080/device-display/`, kiosk-mode chrome, autorestart on crash.
- Set up MediaPipe gesture recognition on the Pi CPU (~5-15 fps is enough for
  held poses; optionally HEF-convert + offload to the Hailo later for 30 fps)
- Performance and stress testing with all subsystems active

**Deliverables**
- All laptop features running on real hardware
- Performance benchmarks comparing laptop vs hardware
- Memory headroom validation (Pi 5 RAM usage with OpenClaw + everything)
- Stress test results: 30 min concurrent voice + gesture + skills

**🚦 Gate criterion:** Real Lumi hardware matches laptop Lumi behavior with ≤2x latency penalty on voice query loop. RAM usage stays under 6GB on Pi (within the 8GB budget).

---

### Phase 6 (Week 7-8) — Lumi OS image build

Package the whole thing into a flashable .img file users can install.

**Tasks**
- Set up `pi-gen` recipe in `os-image/stage-lumi/`
- Bake in:
  - Pi OS Lite 64-bit base
  - Python runtime + all dependencies
  - Node.js 22.14+ + OpenClaw + curated skills
  - All AI models pre-downloaded (Whisper, Piper, MediaPipe, Qwen2.5 .hef)
  - ReSpeaker 2-Mics HAT drivers configured
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

**Camera-active indicator:** an **on-screen** pulsing red camera glyph (`App.tsx`, driven by `cameraActive` off the vision worker's presence heartbeat — dark within ~12s of capture actually stopping). The originally-planned NeoPixel on the ReSpeaker HAT is **abandoned as not-applicable**: the HAT is sealed inside the SmartiPi enclosure, so a light on it is invisible and would be a privacy signal nobody can see (resolved 2026-08-06, see `docs/privacy-led.md`). A physical light would have to be an externally-mounted LED, like the now-external speaker and USB mic — V2, alongside the shutter. Manual 3D-printed privacy cap for V1; integrated slider shutter for V2.

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

**Status: built and deployed (2026-07-06).** Gesture recognition,
presence detection, and their display/wake integration are live on the
Pi under `lumi-vision.service` + `lumi-vision-capture.service`. See
`vision-worker/README.md` and `vision-worker/capture_shim/README.md` for
the implementation detail; this section covers the architecture and
behavior that matters for future sessions.

**Hardware:** Pi Camera Module 3 Wide (102° FOV, 12MP IMX708, motorized autofocus). Connects via CSI ribbon — no PCIe conflict with AI HAT+ 2.

**Vision pipeline — three processes, not one, for two independent version
conflicts:**
```
[system Python 3.13] Picamera2/libcamera capture (capture_shim.py)
       → POSIX shared memory (raw RGB frames)
       → [Python 3.12, vision-worker's own venv] MediaPipe Hand Landmarks
       → 21 hand keypoints per frame (~16-22 fps measured on-Pi)
       → custom gesture classifier (classify.py/wave.py, pure Python)
       → gesture/presence event → HTTP push to lumi-web (/api/gesture,
         /api/presence) for the display, or a file-drop wake trigger
         consumed by the voice loop's FileTriggerWake
```
Two separate ABI/version walls forced this three-process shape:
1. MediaPipe needs protobuf 4.x; `lumi-web`'s chromadb needs protobuf
   7.x — can't share a venv with the main app (this was anticipated).
2. `picamera2`/`libcamera`'s Python bindings are apt-installed and
   compiled specifically against the Pi OS's **system** Python (3.13) —
   but MediaPipe has never published a `cp313` wheel on any platform,
   and its newest aarch64 Linux wheel at all is `0.10.18`, capped at
   `cp312` (confirmed against PyPI's full release history, 2026-07-06).
   Discovered only during real hardware deployment, not anticipated in
   the original design. Solved by splitting camera capture into its own
   tiny process (`vision-worker/capture_shim/capture_shim.py`, runs
   under system Python) that hands frames to the mediapipe process over
   shared memory — sub-millisecond overhead, negligible against
   MediaPipe's own ~45-60ms/frame inference budget.

**V1 gesture vocabulary:**
- 👋 Wave — **wakes Lumi** (the only gesture that does), plus a smile +
  little dance reaction on the pixel face
- ✋ Open palm — display badge only in this build, not yet wired to
  interrupt TTS (needs its own design pass — see the vision-worker
  plan's scope note)
- 👍 Thumbs up / 👎 Thumbs down — display badge only, not yet wired to a
  yes/no confirmation flow
- ✊ Closed fist — display badge only
- Presence detection — **display-only**, per explicit user decision
  (2026-07-06): sitting down/leaving does **not** wake or sleep Lumi
  mechanically. It only drives the on-screen ambient dim + closed-
  eyes/"Zzz" sleep treatment (gated to IDLE, so it never visually
  interrupts an active turn). The only ways to wake Lumi are a wave
  gesture or the voice wake word.

**Privacy by design:**
- Frames never written to disk anywhere in the pipeline (verified: the
  shared-memory buffer is overwritten every frame at a fixed address,
  never persisted; MediaPipe's own frame reference is dropped after
  landmark extraction)
- Only 21-point hand landmarks retained past a single loop iteration
- On-screen camera-active indicator (small icon, `App.tsx`) shipped as
  the privacy signal for V1, and now permanently rather than "for now":
  the ReSpeaker HAT sits sealed inside the enclosure, so an LED on it
  can't be seen by anyone (resolved 2026-08-06 — see
  `docs/privacy-led.md` for what was investigated and why a physical
  light now means an *externally* mounted LED, which is V2)
- `camera_enabled` in `/settings/data` actually gates capture — when
  off, `capture_shim.py` releases the camera and idles in a settings-
  poll loop rather than just ignoring detections (verified via CPU usage
  dropping to idle within ~2s of toggling off)

---

## Storage strategy

**Single microSD card holds everything:** OS, application code, all AI models, ChromaDB, conversation history, user data, OpenClaw + skills.

**Card spec:** SanDisk Extreme 256GB A2 V30 (`SDSQXAV-256G-GN6MA`) — a reputable A2 card, deliberately the plain "Extreme" not "Extreme Pro." The Pi 5 SD slot is UHS-I/SDR104 (~90 MB/s real sequential — the card's ~190 MB/s rating is unreachable here, so it's not worth a premium), but A2 random IOPS (~5000 read / 2000 write) *are* usable on the Pi 5 thanks to its SD command-queue support — and random I/O is what the OS/ChromaDB workload leans on. (Any reputable 256GB A2 card is equivalent on the Pi; SanDisk picked for endurance reputation on a 24/7 device.)

**Why microSD is sufficient (not a compromise):**
- The smart LLM is cloud (no local weights to load); the small CPU floor model (~1 GB) loads once at boot and stays resident
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
| ~~Cloud LLM fallback with intelligent routing~~ **(SHIPPED 2026-05-24, FLIPPED TO CLOUD-FIRST 2026-07-05)** | `RoutedBackend` (in `src/lumi/llm/routed_backend.py`) wraps the local backend with a Gemini cloud client. Toggle in `/settings/cloud` → "Enable cloud routing". **Flipped 2026-07-05** from local-first-with-escalation (local always ran to completion first; cloud was only tried if the reply looked evasive) to **cloud-first-with-local-fallback**: cloud is tried FIRST for every conversational turn; local only answers if cloud is unavailable or empty. Reasoning: the old design meant an escalated turn paid local generation time PLUS cloud generation time — the worst-case latency, not the best — and the user explicitly wanted responsiveness prioritized, with the local model reserved for skills/background work rather than live conversation. The old low-confidence heuristics (`_trips_low_confidence`, boilerplate regex, `_MIN_REPLY_CHARS`) are gone — no longer meaningful once cloud isn't conditional on local's reply quality. Cloud now streams too (`GeminiClient.complete_streaming()` via Gemini's SSE endpoint) rather than returning one blob — non-streaming was fine for an occasional fallback but would have undercut the entire point of the flip. A cloud stream that fails partway (after some chunks already reached the caller) just stops rather than splicing in a full local reply, since un-yielding already-shown text isn't possible. Memory-prelude messages are still stripped before cloud send (detected by header text). Each turn lands in the audit log as `source=cloud:gemini` or `source=local`. Scope: conversational replies only — OpenClaw skill-invocation routing (`SkillRouter`/`_worth_trying_openclaw`) is untouched, still native-skill-first. **Still V2:** Anthropic + OpenAI adapters (Gemini is the only adapter today since that's what the user has wired); per-skill toggle to opt skills out of routing. |
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
| **Curated skill catalog UI** | Light-touch alternative to a full ClawHub marketplace: a /skills/catalog page that lists Lumi-vetted plugins (gmail / gcal / github / slack / spotify) pulled from a static JSON URL we control, with one-click install that drops the plugin into `~/.openclaw/extensions/`, adds it to `plugins.allow`, and records the install in the audit log. Preserves the V1 decision-log commitment "no general ClawHub — only Lumi-vetted plugins shipped" while still giving users a place to discover new skills. Tracked as a backlog item after web-dashboard work. ~1 day. |
| **Chat streaming endpoint hangs under sustained load** *(found 2026-05-23)* | Phase 4 soak (60 min, mock backend, 5-second cadence) ran cleanly for ~11 min then `/chat/stream` started timing out — 84 ReadTimeouts piled up over the next 49 min. Server process stayed alive, no 5xx, no FD/RSS leak, no exceptions in logs. Latency p95 drift 3.09× (gate threshold 2×). Real user cadence (1-3/min with idle stretches) wouldn't hit this. Likely a StreamingResponse + `loop.run_in_executor` interaction in `chat.py:chat_stream` under sustained concurrent open generators. Investigation plan: reproduce with a shorter, more aggressive soak; check for executor thread starvation; consider moving `next(gen)` off the default executor or making the chunk generator natively async. ~2-3h to root-cause + fix. |
| **Sprite-pack uploader** | `/settings/sprites` page: list existing sprite folders in `data/sprites/`, upload form (ZIP or PNG frames + manifest.json), delete button. Auto-populates the idle scene dropdown. Validates PNG-only, size caps, safe folder names. User-requested ("tamagotchi customization"). ~2-3h. |
| **Pixel face redesign** | The pink-heart-with-blush-and-smiley reads off. User to source inspiration; we redo when there's a clear direction. |
| **Auto-detect location for weather, instead of manual entry** *(user-requested, 2026-07-06)* | Live weather already ships (`weather_sampler` in `device_samplers.py` + `RightPanel`/`WidgetBar` on the device display) but requires the user to type a city into `weather_location` at `/settings/data` (with typeahead via `/api/locations/search`). The Pi 5 has no GPS hardware in the V1 BOM, but it doesn't need one for city-level weather: IP-based geolocation (e.g. a free-tier lookup like ip-api.com/ipinfo.io — one outbound HTTP GET, no new hardware) resolves to city/region accuracy on a home WiFi connection, which is all OpenWeatherMap's endpoint needs anyway. Scope: on first boot (or a "detect automatically" button next to the manual field), fetch IP geolocation, prefill `weather_location`, let the user override it same as today. Worth flagging as a privacy consideration despite being low-stakes (an outbound call revealing rough location to a third-party geolocation service) — should be opt-in, not silent, consistent with the local-first brand. ~2-3h. |
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
| **Pi 5 16GB** *(re-revised 2026-06-20, reversing the 06-15 8GB call)* | The 06-15 downgrade to 8GB rested on "the LLM always runs off Pi system RAM — Hailo's own 8GB or the cloud." That premise changed: V1 is now **cloud-primary with a small local LLM on the Pi 5 CPU** as the private/offline floor (see "Cloud-primary LLM" entry), and the **AI HAT+ 2 is no longer a committed component** (see its entry). So local inference now consumes ~1 GB of *system* RAM and the HAT's isolated 8 GB can't be assumed present — headroom matters again. 16GB restores comfortable margin for Chromium + OpenClaw + ChromaDB + a CPU-resident model. Accepted the 2026 DRAM-shortage cost/availability premium for that headroom. *(If 16GB proves unavailable, 8GB still works — ~3 GB free — but tighter; the onnx-embedding swap that banked ~1 GB keeps 8GB viable as a fallback.)* |
| **AI HAT+ 2 — ❌ SKIPPED (vision benchmark PASSED 2026-07-01)** *(was optional/pending; revised 2026-06-20)* | **On-Pi benchmark: MediaPipe HandLandmarker (VIDEO mode) held 16.2 fps during a live `qwen2.5:1.5b` turn (17.2 fps idle) — barely dips because the LLM is memory-bandwidth-bound and leaves CPU headroom for XNNPACK vision. The Pi 5 CPU sustains continuous vision + a live turn, so the HAT is NOT needed; ship on the 16GB Pi, PCIe lane stays free.** No longer a locked V1 part. With the LLM on cloud + Pi CPU, the HAT's only remaining job is offloading **continuous MediaPipe vision** off the CPU; whether that's needed is gated on one Phase-5 benchmark (see Open questions). V1 ships on the 16GB Pi alone; the HAT is bought **only if** the Pi 5 CPU can't sustain continuous vision + a live turn. *(If kept, its 40 TOPS + 8GB still beats the original AI HAT+ as a vision accelerator and needs HEF-converted models; if dropped, the single PCIe lane frees up — storage stays microSD by design either way. Note: the Hailo is NOT a good LLM host — bandwidth-bound, no faster than the Pi CPU on 1–1.5B models.)* |
| **microSD only** (no NVMe, no external SSD) | AI HAT+ 2 takes PCIe lane. External SSD kills portability. Workload doesn't need NVMe. |
| **microSD + log2ram** | Mitigates write wear. Standard pattern in Pi production projects. |
| **Cloud-primary LLM + CPU tiny-LLM floor** *(revised 2026-06-20, was "Pure onboard LLM")* | V1's smart brain is the **cloud LLM** (opt-in key); a **small local model (Qwen2.5 1.5B / Llama 3.2 1B) runs on the Pi 5 CPU** as the privacy/offline floor + router — handling simple/sensitive turns and keeping Lumi working with no network and no key. The Hailo NPU is **not** the LLM host: it's memory-bandwidth-bound and runs these small models no faster than the Pi 5 CPU, so CPU inference is simpler and removes the HAT from the critical path. Preserves the "private/offline by default, cloud when you opt in" brand. *(`RoutedBackend` already ships this local-floor + cloud-ceiling design; the original "zero cloud dependency" framing is retired. Strategic note: the privacy wedge now rests on the local floor + on-device data, not on the LLM being fully local — keep that floor real.)* |
| **OpenClaw included in V1** | Industry standard agent framework. Memory separation makes it feasible (LLM on HAT, OpenClaw on Pi RAM). Gives users a rich skill ecosystem out of the box. |
| **Curated skill set for V1** | Small LLM (1.5B) can't reliably orchestrate complex multi-step skills. Limit to simple single-step, read-only skills for safety and reliability. |
| **Dedicated accounts for all external integrations** | Never use the user's primary email/calendar. Dedicated accounts mean a compromised skill can only access a limited, purpose-built inbox/calendar. |
| **`sandbox/` directory for file access** | `file_search` is confined to `sandbox/` (gitignored, local-only). User drops files there manually. No open filesystem access. |
| **macOS Calendar/Contacts access denied at OS level** | CalDAV skill hits a remote endpoint (dedicated Google account); it has no legitimate reason to touch the local macOS Calendar app. Deny at System Privacy. |
| **No third-party ClawHub skills** | Documented security incidents (ClawHavoc, ~20% malicious plugins per Cisco). Only Lumi-vetted skills shipped. |
| **Custom LLM provider for OpenClaw** | Lets OpenClaw use our Hailo NPU (production) or Ollama (dev). Same interface, swappable backend. |
| **Qwen2.5 1.5B — local floor (VALIDATED on-Pi 2026-07-01)** | `qwen2:1.5b` lacks Ollama's tools API; `qwen2.5:1.5b` has it (94% tool-call accuracy, Phase 1). **On-device benchmark — 6 models / 5 providers, Chromium face running, thinking off (real Lumi conditions):** qwen2.5:1.5b **7.4 tok/s / 1.4 GB** · qwen2.5:3b 4.0 / 2.4 GB · phi4-mini 3.1 · gemma3:4b 3.1 · qwen3.5:4b 2.4 · **gpt-oss:20b 1.85 tok/s, 159 s load, ~14 GB (touches swap, no room for the live-turn stack)**. **Bigger + MoE rejected on data:** the Pi 5's memory-bandwidth wall + a ~2× "face tax" (Chromium contention) make bigger dense models crawl; reasoning models (qwen3.5, gpt-oss) default to multi-minute chain-of-thought; the 20B MoE was the *slowest* AND RAM-starving. **Conclusion: quality comes from the cloud ceiling, not a big local floor — keep the floor small + fast.** Optional smarter floor = `qwen2.5:3b` (2.4 GB, ~4 tok/s) via one-line `LUMI_OLLAMA_MODEL` change. Do not re-litigate "run a bigger/MoE local model" without new hardware (e.g. the AI HAT+ 2 — see its separate LLM data point in bom.md). |
| **Tool-calling tested via Ollama directly** | OpenClaw gateway does not forward external tool definitions — it routes through its own skills system. Model-level tool calling is tested via Ollama's native API (`/api/chat`). |
| **Hailo protocol bridge runs in-process, not as a separate adapter** (2026-05-23) | Considered `pip install tishyk/hailo-ollama-openclaw-adapter@2026.04.20` as a runtime dep but rejected on three counts: (a) Lumi V1 is the only thing on the Pi talking to Hailo (OpenClaw in V2 cloud mode points at a cloud provider, not Hailo), so the adapter would be a redundant network hop; (b) tracking a third-party pin in our critical path adds maintenance risk if upstream goes quiet; (c) the four extra rules we needed beyond what we already had (deep-sanitize, ASCII-encoded JSON, empty-message filter, user-first-turn) total ~30 lines of Python. tishyk's repo remains the **source of the quirk list** for future Hailo SDK releases — port new quirks into `hailo_backend.py` directly. |
| **wikipedia_lookup needs explicit phrasing** | Model answers general knowledge questions directly (correct). Skill activates on "look up X on Wikipedia" style prompts, not bare factual questions. |
| **Skill router (native first, OpenClaw fallback)** | Native skills are fast and reliable for simple commands. OpenClaw extends reach but with more overhead. |
| **ReSpeaker 2-Mics HAT** | Compact single board (mics + speaker-out + 3 RGB LEDs + button) with good integration in a small footprint. Briefly evaluated the XVF3800 4-Mic USB array (hardware AEC + far-field) but its 99 mm circular board was too big for the compact desk form — reverted to the 2-Mics HAT and handle AEC in software. Stacks on the AI HAT+ via a taller stacking header. |
| **No mechanical buttons in V1** | Pushed to V2. V1 leans into voice + gesture as the differentiator. |
| **Camera Module 3 Wide** (vs AI Camera IMX500) | AI HAT+ 2 is more capable; AI Camera redundant. Wide FOV needed for desk gestures. |
| **Curated wake-word palette** (vs custom training) | Pre-trained = reliable. Custom training has poor accuracy. |
| **Lumi OS image distribution** | Same pattern as Home Assistant OS, OctoPrint. Professional, consistent. |
| **No cloud backup in V1** | V1 is local-only. Backup is V2 feature with user's own cloud accounts. |
| **Raspberry Pi Touch Display 2 (7", run landscape 1280×720) in a SmartiPi Touch Pro 3 enclosure** *(revised 2026-06-20, was 4.3" Waveshare DSI)* | Deliberate **form-factor change** for **product finish**: a 7" official touchscreen in a SmartiPi Touch Pro 3 (weighted tilting stand, VESA, side power button, microSD extender, front camera mount) reads as a finished product for Lang Center demos + customer-discovery interviews, vs. a 4.3" panel on exposed acrylic. Display ~$87 (CanaKit) + case $40 + fan ≈ $135. Trades the "small ambient creature" feel for a "7" touch-tablet companion" — an intentional brand call. **New risks this creates (see bom.md open questions):** (1) **audio** — Pi+ReSpeaker sealed in the case cavity vs. mics needing to hear the user → route mics/speaker out or mount externally (biggest risk); (2) **cavity** fits ~Pi 5 + cooler + one HAT, so it likely **can't also house the optional AI HAT+ 2** — the enclosure and HAT decisions now interact; (3) UI re-canvas to **1280×720 landscape** (rotate native 720×1280 — a rescale, not a rebuild). Supersedes the 06-14 4.3" DSI entry. |
| **Pi OS Lite 64-bit** | Headless, minimal, fast boot. We build our own UI. |
| **Piper TTS** (vs ElevenLabs in V1) | Local, free, good quality. ElevenLabs is V2 premium tier. |

---

## Open questions (TBD)

Surface to user when relevant.

- **OpenClaw viability with Qwen2.5 1.5B** — ✅ RESOLVED: 94% (47/50). OpenClaw stays in V1.
- **Specific LLM model choice for V1** — ✅ RESOLVED (on-Pi benchmark 2026-07-01): **qwen2.5:1.5b** is the local floor — fastest (7.4 tok/s) + smallest (1.4 GB) of 6 models across 5 providers with the face running. Bigger dense, MoE (gpt-oss:20b), and reasoning models (qwen3.5) all measured slower and were rejected on data (see decision log). `qwen2.5:3b` is the optional smarter/slower alt. *(Hailo `.hef` path only revisited if the AI HAT+ 2 is added.)*
- **Wake word palette** — Initial candidates: Lumi, Aria, Nova, Sage, Atlas, Iris, Juno, Hugo, Echo, Pip. Need to test which pre-trained models work cleanly.
- **Piper voice selection** — Listen through candidates and pick 3-4 matching the warm/calm brand.
- **Face style designs** — Need actual designs for pixel / vector / terminal.
- **Onboarding system prompts** — Per work mode (Developer / Writer / Student / General).
- **CSI ribbon cable** — Pi 5 uses smaller CSI connector than Camera Module 3 ships with. Verify adapter needed.
- **3D-printed manual privacy cap** — V1 trust signal — needs design.
- **Audio in the SmartiPi enclosure** ✅ **RESOLVED 2026-08-06 — the fallback won: both transducers are now OUTSIDE the case.** The 06-20 plan was to seal the Pi + ReSpeaker behind the screen and fire audio through the case's rear grill vents, with a front-mounted USB mic listed only as a fallback if rear-facing mics couldn't hear the user. In practice the build went straight to external hardware: **an external USB mic** (`Usb Audio Device`, card id `Device`) and **the speaker mounted outside the case**, with the ReSpeaker HAT retained inside purely as the playback codec. This dissolves the original risk rather than mitigating it — mic placement is now free (no vent orientation to get right), and mic/speaker separation for barge-in is a matter of where you physically put them, not of which vent they share. Software AEC is still worth having, but is no longer load-bearing.
  Three consequences already handled in code (2026-08-05/06): (1) the USB mic **does not support 16 kHz**, only 44.1/48 kHz, while openwakeword and Whisper both require exactly 16 kHz — see `audio/resample.py`; (2) **playback and capture are now different ALSA cards**, so `hardware/audio_mixer.py` discovers the capture card by probing rather than hardcoding, and mic-mute had silently stopped working before that; (3) a **sealed HAT can't host the privacy LED** — see `docs/privacy-led.md` and Tier 3 #8.
  Also note the ReSpeaker's own mics have been observed reporting `max_input_channels=0` on one boot and `2` on the next — unexplained, and no longer on the critical path now that capture is external, but don't rely on them.
- **SmartiPi cavity vs. optional AI HAT+ 2** 🟡 — the 45 mm cavity fits ~Pi 5 + cooler + one HAT (ReSpeaker); if the vision benchmark forces the AI HAT+ 2 in, two HATs likely won't fit and the enclosure must be revisited.
- **OpenClaw service startup time** — Adds to Pi boot time. Acceptable threshold?
- **Skill timeout default** — How long before a stuck skill is killed? (Default 10s, configurable per skill)
- **Pi-CPU vision headroom** ✅ RESOLVED 2026-07-01, integration shipped 2026-07-06 — **PASSED on the actual Pi 5:** MediaPipe HandLandmarker (VIDEO mode) ran **17.2 fps idle / 16.2 fps under a live `qwen2.5:1.5b` turn** (with the Chromium kiosk up) — well above the 10–15 fps target. So the Pi 5 CPU sustains continuous vision + a live turn → **SKIP the AI HAT+ 2, ship on the 16GB Pi.** Both integration caveats anticipated/discovered during the actual build are resolved: (1) protobuf 4.x-vs-7.x — `vision-worker/` runs as its own process/venv, confirmed on-Pi at ~22 fps camera+MediaPipe together; (2) a *second*, unanticipated conflict found only during real deployment — `picamera2`/`libcamera`'s Python bindings are compiled against the Pi's system Python (3.13), but MediaPipe has no wheel for that version on any platform — solved by splitting camera capture into its own process (`capture_shim.py`, system Python) bridged to the mediapipe worker via POSIX shared memory. See the "Camera & vision" section above for the full pipeline shape.

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
