# Lumi

> Your AI companion. Always on. Always yours.

Lumi is a portable physical AI desk companion that plugs into any computer via USB-C. It runs an LLM locally on dedicated AI hardware, listens through onboard microphones, speaks back through an onboard speaker, watches for gestures through an onboard camera, and shows a friendly animated face on a small display. The whole experience is meant to feel warm, calm, and deeply personal — an AI that lives on your desk, knows you, and never sends your data anywhere it doesn't have to.

---

## Project status

Currently in **pre-hardware design phase**. All major architecture decisions are locked in. Hardware is being ordered. Software development begins on a laptop using mocked hardware interfaces and will migrate to the Raspberry Pi 5 + AI HAT+ 2 stack when components arrive.

---

## Product identity

**Tagline:** Your AI companion. Always on. Always yours.

**Primary role:** Personal AI desk companion — ambient presence, proactive intelligence, physical ritual, knows YOU.

**Secondary role:** Developer copilot add-on (Claude Code integration in V2).

**Brand voice:** Warm, calm, deeply personal, privacy-first, premium. Not snarky, not corporate, not robotic.

**What makes Lumi different from ChatGPT or Claude.ai:**
- Physical presence on your desk
- Truly local AI (V1 has zero cloud dependency for inference)
- Ambient awareness via camera and microphones
- Owns its data — your conversations, embeddings, and preferences live on the device

---

## Architecture overview

Lumi is a **purely onboard AI** for V1 — no cloud LLM fallback, no external API calls during inference. This is a deliberate choice that simplifies the architecture, removes failure modes, and makes the brand promise literal.

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
│  │  Display    │◀── │              │ ──▶│    Speaker      │    │
│  │  (SPI bus)  │    │              │    │  (analog)       │    │
│  └─────────────┘    └──────┬───────┘    └─────────────────┘    │
│                            │                                     │
│                     ┌──────▼───────┐                            │
│                     │   Pi 5 16GB  │ ──── USB-C ──▶ Host PC     │
│                     │  (orchestr.) │                            │
│                     └──────────────┘                            │
└────────────────────────────────────────────────────────────────┘
```

**Compute split:**
- **AI HAT+ 2 (40 TOPS, 8GB RAM)**: LLM inference, MediaPipe gesture recognition, vision models
- **Pi 5 CPU**: OS, application orchestration, Whisper STT, Piper TTS, web server, USB gadget service, ChromaDB, face rendering

**Data flow (typical voice query):**
```
Mic → Whisper Tiny (CPU) → text
    → LLM via AI HAT+ 2 → response text
    → Piper TTS (CPU) → audio → speaker
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
| **Core compute** | Raspberry Pi 5 (16GB) | Main computer, runs Lumi OS |
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

**V1 hardware total: ~$700-750** (no enclosure, no mechanical buttons, no rotary encoder)

**PCIe lane usage:** Single PCIe lane on Pi 5 is dedicated to AI HAT+ 2. NVMe storage is intentionally not used — onboard storage is microSD only.

---

## V1 software stack

```
Layer                     Component                  Notes
─────────────────────────────────────────────────────────────────────────
Operating system          Raspberry Pi OS Lite       64-bit, headless
                          (Bookworm or Trixie)

Runtime                   Python 3.11+

Speech-to-text            Whisper Tiny               ~150MB, runs on Pi CPU
                                                      ~0.5s for short clips

Text-to-speech            Piper TTS                  ~100MB, runs on Pi CPU
                                                      Warm voice personality

Wake word                 OpenWakeWord or Porcupine  Local detection
                          (curated name palette)      "Hey Lumi" + alternatives

Local LLM                 Qwen2 1.5B / DeepSeek      Runs on AI HAT+ 2
                          R1-Distill / Llama 3.2 1B   Quantized for Hailo

Vision                    MediaPipe Hand Landmarks   Runs on AI HAT+ 2
                          + custom gesture classifier 30 fps

Vector database           ChromaDB (embedded)        Local personal data
                                                      Up to ~1GB

Embedding model           all-MiniLM-L6              Generated during ingestion
                                                      Stored in ChromaDB

Web server                FastAPI                    Serves lumi.local
                                                      Onboarding, dashboard

USB gadget                libcomposite               HID + Mass Storage + CDC
                                                      Native Pi 5 support

Audio I/O                 ALSA + ReSpeaker drivers   Mic capture + playback

System utility            log2ram                    Reduces SD card writes ~95%

Process supervisor        systemd                    All Lumi services
```

**Service architecture (systemd units):**
- `lumi.service` — main app runtime
- `lumi-web.service` — FastAPI dashboard
- `lumi-gadget.service` — USB composite device setup
- `lumi-audio.service` — audio pipeline
- `lumi-camera.service` — vision pipeline

---

## The Lumi OS image

V1 ships as a **custom Pi OS image** (`.img` file), built with `pi-gen`. Users flash one file with Raspberry Pi Imager and Lumi just works. Same pattern as Home Assistant OS, OctoPrint, RetroPie, etc.

**Contents baked in:**
- Pi OS Lite 64-bit base
- Python runtime + all dependencies
- Pre-downloaded models (Whisper, Piper, MediaPipe, LLM)
- ReSpeaker HAT drivers configured
- Camera Module 3 configured
- AI HAT+ 2 Hailo runtime + LLM models
- USB gadget mode pre-configured in `/boot/config.txt`
- log2ram installed and enabled
- mDNS for `lumi.local`
- All Lumi services + Python app
- First-boot onboarding flow

**Release versioning:**
```
lumi-os-1.0.0.img        First release
lumi-os-1.0.1.img        Patch (bug fixes)
lumi-os-1.1.0.img        Feature update
lumi-os-2.0.0.img        Major (V2 hardware support)
```

Each release ships with a SHA-256 hash for verification.

**Build pipeline (TBD):** GitHub Actions running `pi-gen` on each tagged release, output uploaded to a release CDN.

---

## V1 input model

```
Voice                Primary input — wake word, commands, dictation
Camera gestures      Acknowledgments + presence detection
ReSpeaker button     One physical button — wake / cancel / push-to-talk
Web UI (lumi.local)  Settings, system prompt, voice enrollment, modes
```

**Why no mechanical buttons or rotary encoder in V1:** Pushed to V2. V1 is intentionally minimalist to ship faster and lean into the ambient voice+vision differentiator.

**Volume control:** voice commands + web UI slider (no physical dial in V1).

**Yes/No confirmation:** voice ("yes"/"no") + gestures (thumbs up/down).

**Mode switching:** voice ("switch to focus mode") + web UI dropdown.

---

## Onboarding flow

First-run experience runs across **Lumi's device display + a companion web UI** at `lumi.local` on the host PC. Total time ~10 minutes.

```
Step 1  First plug-in           USB mass storage trick mounts a helper
                                 Welcome animation plays on device

Step 2  WiFi setup               Web UI captures credentials via helper
                                 (For mDNS + V2 features later)

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
                                 - Calendar (V2)
                                 - Email (V2)
                                 - Files (pointed-to only)
                                 - Camera (gestures + presence)

Step 8  Work mode                Developer / Writer / Student / General
                                 Pre-configures system prompt + defaults

Step 9  First conversation       Lumi greets user by name
                                 Asks "What are you working on?"
                                 No tutorial — just talking
```

**Voice enrollment details:** Uses Resemblyzer or SpeechBrain ECAPA-TDNN for speaker verification. Embedding stays on device. Multi-user mode (V2) allows adding household members.

**Wake word approach:** Curated palette of 10-15 pre-trained names. User picks one. Avoids the accuracy problems of custom wake-word training while preserving personalization.

---

## Web UI structure

Served at `lumi.local` via mDNS. FastAPI backend + HTMX frontend.

```
/                       Dashboard — Lumi's current state, recent conversations
/onboarding             First-run flow (Step 1-9 above)
/settings/personality   System prompt editor, voice picker
/settings/memory        Memory browser — what Lumi knows about you
/settings/data          Permission toggles per data source
/settings/face          Face theme picker
/settings/voice         Voice enrollment management
/settings/modes         General / Code / Focus / Dictation
/dev                    Developer mode — logs, debug, hardware status
```

**Design tone:** Warm cream/amber palette, generous whitespace, slow gentle animations. Lumi's face mirrored live in a corner of the UI. Feels conversational, not configurable.

---

## Privacy & data handling

**V1 commitment: local-only.** No telemetry, no remote API calls during normal operation, no cloud LLM, no cloud backup.

**Where data lives:**
```
User conversations          → ChromaDB on microSD
Speaker voice embedding     → Single file on microSD
User preferences            → JSON on microSD
LLM context cache           → AI HAT+ 2 RAM (volatile)
Camera frames               → Never stored, never persisted
                              Only landmarks used, frames discarded after inference
```

**Camera-active indicator:** When camera is in use, a NeoPixel on the ReSpeaker HAT lights red. Optional 3D-printed manual privacy cap for V1; integrated slider shutter for V2.

**Data export:** User can export everything (conversations, embeddings, preferences) as a single archive via web UI. Important for trust.

**Data deletion:** "Forget everything" option in settings wipes all user-specific data and resets to first-boot state without reflashing.

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

**Single microSD card holds everything:** OS, application code, all AI models, ChromaDB, conversation history, user data.

**Card spec:** SanDisk Extreme Pro 256GB A2 (or equivalent). 200MB/s read, 90MB/s write, 4000 IOPS.

**Why microSD is sufficient (not a compromise):**
- LLM runs entirely from AI HAT+ 2's onboard 8GB RAM (never hits disk)
- Models load once at boot into Pi RAM
- ChromaDB queries are RAM-cached after warmup
- Writes are tiny (kilobytes per conversation)

**Write protection: log2ram pre-installed.** OS journaling and system logs are written to a RAM tmpfs and synced to disk hourly. Reduces SD card writes by ~95%.

**Backup strategy (V2):** Nightly automated backup of user data (not OS) to user's chosen cloud (Drive/Dropbox/iCloud) or local PC folder. V1 keeps data local only.

**Recovery:** SD card failure → flash a new card with `lumi-os-X.Y.Z.img` (10 min) → restore user data from backup (V2 only for now) → back to working state in <15 min.

---

## V2 roadmap

Features deferred from V1 to keep V1 shippable:

| Feature | Notes |
|---|---|
| Mechanical key switches (NeoKey 1x4 + Kailh Brown + keycaps) | Premium tactile inputs |
| Rotary encoder + knob | Volume + mute dial with NeoPixel ring |
| Cloud backup integration | Sync to user's Drive/Dropbox/iCloud |
| ElevenLabs premium voice tier | Higher-quality TTS as paid upgrade |
| Cloud LLM fallback (Claude API) | For complex queries beyond local LLM capability |
| Premium enclosure | Frosted translucent shell, underside glow, matte finish |
| Physical privacy shutter | Integrated slider over camera lens |
| Custom wake word training | User picks any name |
| Multi-user voice profiles | Household members can be enrolled |
| Sound design | Startup chime, listening tone, confirmation chimes |
| Onboard fine-tuning | Adapt to user's writing style |
| Claude Code integration | Developer-focused features |

---

## Pre-hardware development plan

The first 4 weeks of work happen on a developer laptop. The hardware-specific code is ~20% of the project; everything else can be built and tested without a Pi.

**Week 1 — Foundation**
- Set up GitHub repo + project structure
- Dev environment: Python 3.11, Whisper, Piper, Ollama (for local LLM testing)
- Verify basic voice pipeline: laptop mic → Whisper → LLM → Piper → laptop speaker
- Get a "hello, I can hear you" round-trip working

**Week 2 — Lumi runtime**
- State machine: idle → wake → listen → think → speak → idle
- Mode system (general / code / focus / dictation)
- Conversation manager + ChromaDB integration
- Face engine rendering to a laptop window (will swap to SPI display later)
- Mock GPIO/I2C/USB layer (clean abstractions so hardware swap is easy)

**Week 3 — Web UI**
- FastAPI scaffold + mDNS
- Onboarding flow (all 9 steps)
- Dashboard + settings
- Voice enrollment UX with laptop mic

**Week 4 — Host PC helper + polish**
- USB HID injection (test against another laptop/VM for now)
- Clipboard + active window detection
- End-to-end testing on laptop

**Week 5+ (hardware arrives) — Hardware integration**
1. Flash base Pi OS, set up Pi dev environment
2. ALSA + ReSpeaker 2-Mics HAT
3. AI HAT+ 2 + Hailo runtime + LLM
4. USB gadget composite (HID + Mass Storage + CDC)
5. SPI display
6. Camera Module 3 Wide + MediaPipe
7. Replace mocked drivers with real ones, one subsystem at a time
8. `pi-gen` pipeline for Lumi OS image build

By the time hardware is in hand, "laptop Lumi" should be fully functional. Hardware phase becomes integration, not invention.

---

## Project structure (suggested)

```
lumi/
├── CLAUDE.md                    # This file
├── README.md                    # Public-facing intro
├── LICENSE
├── pyproject.toml               # Python deps + tooling
├── docs/
│   ├── architecture.md
│   ├── onboarding-flow.md
│   ├── voice-design.md
│   ├── privacy.md
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
│   │   ├── hailo_backend.py     # AI HAT+ 2 inference
│   │   └── prompts.py
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
├── tests/
│   ├── unit/
│   ├── integration/
│   └── hardware/                # Run only on real Pi
│
├── os-image/                    # pi-gen recipe
│   ├── stage-lumi/
│   ├── build.sh
│   └── README.md
│
└── scripts/
    ├── dev-setup.sh
    └── flash-image.sh
```

---

## Decision log

Key decisions made during design, with reasoning. Future sessions: do not re-litigate without strong cause.

| Decision | Reasoning |
|---|---|
| **Pi 5 16GB** (vs 4GB/8GB) | Comfortable RAM headroom for Whisper + Piper + ChromaDB + future. ~$55 well spent. |
| **AI HAT+ 2** (vs original AI HAT+) | 40 TOPS + 8GB dedicated RAM = LLM-capable. Vision still excellent. |
| **microSD only** (no NVMe, no external SSD) | AI HAT+ 2 takes PCIe lane. External SSD kills portability. Workload doesn't benefit from NVMe in practice. |
| **microSD + log2ram** | Mitigates write wear. Standard pattern in Pi production projects. |
| **Pure onboard LLM** (V1) | No cloud dependency. Simpler architecture. Stronger brand promise. |
| **ReSpeaker 2-Mics HAT** (vs USB mic array + separate amp) | Single board replaces three components. Better integration. |
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

Things not yet decided. Surface to user when relevant.

- **Specific LLM model choice for V1**: Qwen2 1.5B vs DeepSeek R1-Distill 1.5B vs Llama 3.2 1B — needs real-world testing on AI HAT+ 2.
- **Wake word options in the curated palette**: Need to test which pre-trained models work cleanly. Initial candidates: Lumi, Aria, Nova, Sage, Atlas, Iris, Juno, Hugo, Echo, Pip.
- **Piper voice selection**: Need to listen through candidate voices and pick 3-4 that match the warm/calm brand.
- **Face style options (pixel / vector / terminal)**: Need actual designs created.
- **Onboarding system prompts per work mode**: Need wording for Developer / Writer / Student / General defaults.
- **CSI ribbon cable**: Pi 5 uses a smaller CSI connector than Camera Module 3 ships with. Need to verify which adapter to order (likely Raspberry Pi camera cable for Pi 5).
- **3D-printed manual privacy cap design**: V1 trust signal — needs a simple sliding cover.

---

## Working with Claude on this project

This file is the source of truth for project context across AI sessions. When working with Claude (in Claude Code, claude.ai, or elsewhere) on Lumi:

**Update this file when:**
- A major architecture decision is made
- A V1 vs V2 scope change happens
- An open question gets resolved
- A new constraint or learning emerges

**Don't add to this file:**
- Implementation details that belong in code comments
- Temporary debug notes
- Credentials, API keys, or secrets

**Tone for AI sessions:**
- Push back on suggestions that compromise V1 simplicity
- Question additions that don't fit the warm/calm/private brand
- Verify hardware claims against current 2026 reality (Pi/Hailo/Arduino ecosystem moves fast)
- Don't re-litigate decisions in the Decision Log without strong new information

**Pre-hardware work focus:** Build the laptop version of Lumi first. Mock all hardware interfaces cleanly so the swap to real hardware is a driver replacement, not a rewrite.
