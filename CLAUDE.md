# Lumi

> Your AI companion. Always on. Always yours.

Lumi is a portable physical AI desk companion that plugs into any computer via USB-C. It runs an LLM locally on dedicated AI hardware, listens through onboard microphones, speaks back through an onboard speaker, watches for gestures through an onboard camera, and shows a friendly animated face on a small display. The whole experience is meant to feel warm, calm, and deeply personal — an AI that lives on your desk, knows you, and never sends your data anywhere it doesn't have to.

---

## Project status

Currently in **pre-hardware design phase**. All major architecture decisions are locked in. Hardware is being ordered. Software development begins on a laptop using mocked hardware interfaces and will migrate to the Raspberry Pi 5 + AI HAT+ 2 stack when components arrive.

**Phase 1 complete.** Voice loop (19/19 tests passing) and OpenClaw viability gate both cleared. Moving into Phase 2.

V1 now includes **OpenClaw integration** for the skills/agent layer. OpenClaw is the most-starred open-source AI agent framework as of 2026 and provides a mature skills ecosystem. Lumi uses OpenClaw as a service for extensible integrations while keeping its core architecture (voice + face + gesture + local LLM) independent.

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
- **Pi 5 (16GB system RAM)**: OS, Lumi Python app, Whisper, Piper, ChromaDB, FastAPI, **OpenClaw service (Node.js)**, audio pipeline, display rendering. Plenty of headroom (~13GB free with everything running).

**Why memory separation works:** AI HAT+ 2 handles the heavy LLM workload in its own 8GB. Pi RAM is never used for LLM inference, so OpenClaw + everything else gets full 16GB to share. Confirmed memory headroom ~13GB free at idle.

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
- Face engine rendering to laptop window (3 face style options)
- **Mock hardware abstraction layer**:
  - `MockGPIO`, `MockI2C`, `MockSPIDisplay`, `MockUSBGadget`, `MockCameraIO`
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

**Tasks**
- Flash base Pi OS Lite 64-bit, set up Pi dev environment
- Install Node.js 20+ on Pi (for OpenClaw)
- Configure ALSA with ReSpeaker 2-Mics HAT
- Install Hailo runtime, load LLM models in `.hef` format
- **Migrate OpenClaw LLM provider** from Ollama to Hailo runtime
  - Same provider interface, different backend
  - Validate tool-calling reliability still ≥80% on Hailo
- Configure USB gadget composite mode in `/boot/config.txt`
- Configure SPI display driver (Waveshare 3.5")
- Configure Camera Module 3 Wide via libcamera
- Configure I2C bus (for future modular sensor expansion)
- **Replace each mocked hardware driver with real implementation**:
  - `MockGPIO` → real GPIO
  - `MockI2C` → real I2C  
  - `MockSPIDisplay` → real Waveshare driver
  - `MockUSBGadget` → real libcomposite
  - `MockCameraIO` → real libcamera
  - `OllamaBackend` → `HailoBackend`
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
| Cloud LLM fallback (Claude API) | For complex queries beyond local LLM capability |
| **Expanded OpenClaw skill set** | Write actions (email send, calendar create, music control), multi-step chained skills, Home Assistant control — needs cloud LLM |
| **MCP protocol integrations** | Connect directly to MCP servers (Google Drive, Slack, etc.) |
| Premium enclosure | Frosted translucent shell, underside glow, matte finish |
| Physical privacy shutter | Integrated slider over camera lens |
| Custom wake-word training | User picks any name |
| Multi-user voice profiles | Household members can be enrolled |
| Sound design | Startup chime, listening tone, confirmation chimes |
| Onboard fine-tuning | Adapt to user's writing style |
| Claude Code integration | Developer-focused features |

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
│   │   ├── face/                # Face animations
│   │   └── web/                 # FastAPI + HTMX
│   ├── hardware/
│   │   ├── display.py           # SPI display driver (with mock)
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
