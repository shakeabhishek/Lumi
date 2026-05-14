<p align="center">

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)
![Raspberry Pi 5](https://img.shields.io/badge/Raspberry%20Pi%205-A22846?style=flat-square&logo=raspberrypi&logoColor=white)
![Hailo](https://img.shields.io/badge/Hailo--10H%20NPU-40%20TOPS-FF6B35?style=flat-square)
![OpenClaw](https://img.shields.io/badge/OpenClaw-Skills%20Ecosystem-D14B2F?style=flat-square)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white)
![Linux](https://img.shields.io/badge/Linux-FCC624?style=flat-square&logo=linux&logoColor=black)
![Status](https://img.shields.io/badge/Status-Pre--launch-yellow?style=flat-square)

</p>

<p align="center">
  <img src="docs/assets/pixel-heart.svg" alt="Lumi" width="220">
</p>

<h1 align="center">Lumi</h1>

<p align="center">
  <em>Your AI companion. Always on. Always yours.</em>
</p>

**A portable physical AI desk companion that runs a local LLM on dedicated AI hardware — no cloud, no subscription, no data leaving the device by default. Plug it into any computer via USB-C and Lumi becomes part of your day.**

> *Personal project exploring local AI hardware design, edge ML, agent frameworks, and product engineering end-to-end — from hardware specification to OS image build.*

---

## 🎥 Demo

> Coming soon. V1 hardware is in build. Software demo (laptop mode) coming during pre-hardware development phase.

---

## What makes Lumi different

Most AI assistants live in a browser tab. Lumi lives on your desk.

- **Local-first AI** — The language model runs on dedicated hardware inside Lumi
- **Ambient awareness** — Lumi sees when you're at your desk and hears when you speak
- **Truly yours** — Your conversations, memories, and preferences live on the device
- **Extensible by design** — Built on OpenClaw's skill ecosystem with privacy-vetted integrations for email, calendar, files, and more
- **Plug-and-play** — One USB-C cable. No software install. No account.
- **Owns the experience** — Custom OS, custom hardware, custom voice

---

## How it works

A typical Lumi interaction:

```
You say "Hey Lumi, what's on my plate today?"
   ↓
Onboard microphones capture your voice
   ↓
Whisper transcribes it on-device
   ↓
Lumi routes to a native skill or an OpenClaw skill
   ↓
A local LLM thinks on the AI accelerator
   ↓
The response is spoken back through Piper TTS
   ↓
The whole thing took ~2 seconds. Nothing left the device unless a skill needed it.
```

Lumi also watches for gestures (wave to wake, thumbs up to accept, palm-up to pause) and shows a friendly animated face on a small display.

---

## What Lumi can do

Out of the box, with privacy-vetted skills enabled:

```
"Check my email"                 →  Read-only inbox summary
"What's on my calendar"          →  Today's events read out
"What's the weather"             →  Local forecast
"Set a timer for 10 minutes"     →  Local timer, no network
"Find my notes on the Lumi BOM"  →  Searches your indexed files
"Switch to focus mode"           →  Adjusts personality and response style
"Show me what you know about me" →  Browse Lumi's memory of you
```

All skills are enabled per-user with granular permissions. Every skill invocation is logged in an audit trail you can review anytime. Destructive actions (send email, delete file, create calendar event) are deliberately deferred to V2 — V1 is read-only by design.

---

## What's inside

For transparency, here's what's in every Lumi:

| Component | Role |
|---|---|
| Raspberry Pi 5 (16GB) | Main computer |
| Raspberry Pi AI HAT+ 2 | LLM + vision inference (40 TOPS, 8GB dedicated AI RAM) |
| ReSpeaker 2-Mics HAT | Audio I/O, RGB indicator LEDs |
| Pi Camera Module 3 Wide | Gestures + presence (with active-indicator LED) |
| Waveshare 3.5" IPS display | Lumi's animated face |
| 256GB high-endurance microSD | All storage |
| Custom Lumi OS | Everything tuned to work together |

You don't need to know any of this to use Lumi. It's all pre-assembled, pre-configured, and ready to go.

---

## Getting started

When your Lumi arrives:

1. Plug it into your computer with the included USB-C cable
2. A Lumi helper appears in your file browser (no install required)
3. Open it — your browser opens to `lumi.local`
4. Follow the 9-step onboarding: name your Lumi, enroll your voice, pick a voice and face style, set permissions
5. Say hi

About 10 minutes from unboxing to your first real conversation.

---

## Engineering highlights

Things I'm proud of building into this:

- **Hybrid compute split** — Architected workload distribution between Pi 5 CPU (orchestration, Whisper STT, Piper TTS, web server) and the Hailo-10H NPU (LLM inference + MediaPipe vision), allowing concurrent voice and gesture pipelines without contention
- **OpenClaw integration with custom LLM provider** — Integrated the most-starred open-source AI agent framework on GitHub (350K+ stars) by writing a custom LLM provider that bridges OpenClaw to the local Hailo NPU, unlocking an extensible skill ecosystem with zero cloud dependency
- **Dual-layer skill system** — Native Python skills (fast, deterministic, hardware-near) layered with OpenClaw skills (extensible, network-capable), routed intelligently based on user intent
- **Phased reliability gates** — Built validation criteria into every phase (e.g., 80% tool-calling reliability before committing OpenClaw to V1), preventing scope creep and over-commitment
- **Plug-and-play USB-C interface** — Linux USB gadget mode composite device (HID + Mass Storage + CDC Serial), enabling zero-install setup across macOS, Windows, and Linux hosts
- **Local-only AI architecture** — Designed V1 with zero cloud LLM dependency. RAG over personal data via ChromaDB stays fully on-device
- **Speaker verification** — On-device voice biometrics so Lumi only responds to its owner, with embeddings stored as math vectors (never raw audio)
- **Custom Pi OS image** — `pi-gen`-built distribution with all drivers, models, Node.js, OpenClaw, and services pre-configured, including `log2ram` for SD card longevity
- **Hardware specification with documented tradeoff analysis** — BOM evolved across multiple iterations with explicit reasoning for each choice (Pi 5 RAM tier, AI HAT version, storage strategy, audio path)
- **9-step onboarding flow** — Cross-device experience between Lumi's display and a companion web UI, including voice enrollment, permission gates, skill curation, and personality customization
- **Privacy-first product design** — Camera frames discarded immediately after inference, active-indicator LEDs, granular per-skill permissions, full audit log, one-button data export, one-button factory reset

Full architectural decision log and phase-by-phase development plan in [CLAUDE.md](CLAUDE.md).

---

## Privacy

This matters enough to call out clearly:

- **No cloud LLM in V1** — All AI inference happens on your Lumi
- **No telemetry** — Nothing is reported back to us
- **Camera frames are never stored** — Only gesture landmarks used, frames discarded immediately
- **Skills are opt-in and audited** — Every OpenClaw skill is curated, vetted, and individually enableable. Every invocation is logged
- **You can export everything** — One button gets you all your data
- **You can wipe everything** — One button factory resets

Lumi has WiFi (used only by skills you explicitly enable), but the LLM never calls home. The camera has an active-indicator LED whenever it's running. V2 includes a physical privacy shutter.

---

## Roadmap

### V1 (current)
- Local LLM, speech-to-text, text-to-speech
- Voice + gesture + presence detection
- OpenClaw integration with vetted read-only skill set
- Native skills (timer, mode switching, memory browser, etc.)
- 9-step onboarding with naming, voice enrollment, permissions
- Skill management dashboard at `lumi.local`

### V2 (next)
- Mechanical key switches and rotary volume dial
- Cloud LLM fallback (Claude API) for complex multi-step skills
- Expanded OpenClaw skills — write actions (email send, calendar create), browser automation
- MCP protocol integrations (Google Drive, Slack, GitHub, etc.)
- Cloud backup to your own Drive / Dropbox / iCloud
- ElevenLabs premium voice option
- Premium enclosure with physical privacy shutter
- Multi-user voice profiles
- Custom wake-word training
- Claude Code integration

---

## For developers and contributors

This repository holds the Lumi software. The runtime, web UI, face engine, OpenClaw integration glue, and OS image build pipeline live here. Software contributions are welcome — most of Lumi can be developed and tested on a regular laptop using mocked hardware interfaces.

### Prerequisites

- Python 3.11+
- Node.js 20+
- Working microphone and speakers
- (Optional) Webcam for vision testing
- (Optional) A real Lumi or Pi 5 + AI HAT+ 2 setup for hardware integration

### Setup

```bash
git clone https://github.com/[your-org]/lumi.git
cd lumi
./scripts/dev-setup.sh
```

This installs Whisper, Piper TTS, MediaPipe, Ollama (for dev LLM), OpenClaw with custom LLM provider, and the mock hardware layer that lets the runtime work without a real device.

### Run the dev server

The fastest way is the one-shot orchestrator, which starts Ollama (if not already up), the OpenClaw skill gateway, and the FastAPI web UI together. Ctrl-C stops everything cleanly.

```bash
bash scripts/lumi-up.sh
```

Visit `http://localhost:8080` for the web UI. To run individual pieces by hand:

```bash
uv run lumi web        # web dashboard only
uv run lumi            # voice loop (mock backend) only
```

### Contributing

Before opening a PR:

1. Read [CLAUDE.md](CLAUDE.md) for project context, design decisions, and the phased development plan with gate criteria
2. Check [open issues](#) for things that need help
3. Discuss bigger changes in [discussions](#) first

The project leans into a specific aesthetic and feel — warm, calm, private. PRs that fit this tend to move faster than ones that don't.

Areas where contributions are especially welcome:
- Native skills (Python, simple integrations)
- OpenClaw skill curation and safety review
- Face animations (pixel / vector / terminal styles)
- Gesture vocabulary and classifier improvements
- Web UI refinements (especially skill management UX)
- Voice and TTS personality tuning
- Lumi OS image build improvements
- Documentation

---

## Skills demonstrated

**Hardware & embedded systems**
Single-board computers (Raspberry Pi 5) · AI accelerators (Hailo-10H NPU, 40 TOPS) · I2C, SPI, CSI, USB protocols · Linux GPIO and device tree configuration · Hardware specification and BOM management

**Edge AI & machine learning**
On-device LLM inference · Agent frameworks (OpenClaw integration) · Custom LLM provider development · Speech recognition (Whisper) · Text-to-speech (Piper) · Computer vision and gesture recognition (MediaPipe) · Speaker verification and voice biometrics · Vector databases (ChromaDB) and RAG · Model quantization for edge deployment

**Software engineering**
Python application development · Node.js service integration · FastAPI web services · HTMX server-driven UIs · systemd service management · Linux USB gadget mode (libcomposite) · State machine design · Hardware abstraction layers · Custom Pi OS image building (`pi-gen`)

**Product & design**
End-to-end product architecture · Privacy-first design · Onboarding UX flow design · Brand voice and product identity · Technical writing and documentation · Architectural decision records · Phased development with gate criteria · Cross-iteration tradeoff analysis

---

## Acknowledgments

Lumi stands on the shoulders of:

- **Raspberry Pi Foundation** for the Pi 5 and AI HAT+ 2
- **Hailo** for the Hailo-10H NPU
- **OpenClaw Foundation** for the open-source agent framework
- **OpenAI** for Whisper
- **Rhasspy** for Piper TTS
- **Google** for MediaPipe
- **Seeed Studio** for the ReSpeaker HAT
- **Anthropic** for Claude (used in the development workflow)

---

## License

License TBD.

---

> Built slowly, built well.
