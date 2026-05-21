<p align="center">
  <img src="docs/assets/pixel-heart.svg" alt="Lumi" width="220">
</p>

<h1 align="center">Lumi</h1>

<p align="center">
  <em>Your AI companion. Always on. Always yours.</em>
</p>

<p align="center">

Built with love and:

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)
![Raspberry Pi 5](https://img.shields.io/badge/Raspberry%20Pi%205-A22846?style=flat-square&logo=raspberrypi&logoColor=white)
![Hailo](https://img.shields.io/badge/Hailo--10H%20NPU-40%20TOPS-FF6B35?style=flat-square)
![OpenClaw](https://img.shields.io/badge/OpenClaw-Skills%20Ecosystem-D14B2F?style=flat-square)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white)
![Linux](https://img.shields.io/badge/Linux-FCC624?style=flat-square&logo=linux&logoColor=black)
![Status](https://img.shields.io/badge/Status-Pre--launch-yellow?style=flat-square)

</p>

**A portable physical AI desk companion that runs a local LLM on dedicated AI hardware — no cloud, no subscription, no data leaving the device by default. Plug it into any computer via USB-C and Lumi becomes part of your day.**

> *Personal project exploring local AI hardware design, edge ML, agent frameworks, and product engineering end-to-end — from hardware specification to OS image build.*

---

## 🎥 Demo

> Coming soon. V1 hardware is in build. Software demo (laptop mode) coming during pre-hardware development phase.

---

## What makes Lumi different

Most AI assistants live in a browser tab. Lumi lives on your desk.

- **Local-first AI** — The language model runs on dedicated hardware inside Lumi. V1 ships fully offline-capable.
- **Optional cloud LLM** — Plug in a Claude/OpenAI/Gemini key in settings and Lumi can route specific turns to a smarter brain when the local one isn't enough. Your call, per-key, anytime.
- **Ambient awareness** — Lumi sees when you're at your desk and hears when you speak
- **Truly yours** — Your conversations, memories, and preferences live on the device. API keys go to the OS keychain, never plaintext.
- **Extensible by design** — When the cloud LLM is configured, the full [OpenClaw](https://openclaw.ai) plugin ecosystem becomes available
- **Plug-and-play** — One USB-C cable. No software install. No account.
- **Owns the experience** — Custom OS, custom hardware, custom voice

---

## How it works

Lumi has two runtime paths and picks the right one per query:

**V1 hybrid (default, no cloud key)** — everything local:
```
You speak  →  Whisper STT (Pi CPU)  →  SkillRouter
   ↓
Native Python skill (timer, pomodoro, notes, …)
  OR Ollama with our tool defs → Python tool handler (weather, wiki, …)
  OR conversation LLM (Qwen2.5 7B on the NPU)
   ↓
Piper TTS  →  speaker
```

**V2 cloud (when you've set an Anthropic/OpenAI/Gemini key)** — same router, smarter brain:
```
You speak  →  Whisper STT  →  SkillRouter
   ↓
Native Python skill (still local)
  OR OpenClaw agent with cloud LLM as operator → JS plugin handlers
     → unlocks the entire OpenClaw plugin ecosystem (Gmail, Calendar, Spotify, …)
  OR conversation LLM (cloud, when intent calls for it)
   ↓
Piper TTS  →  speaker
```

Lumi also watches for gestures (wave to wake, thumbs up to accept, palm-up to pause) and shows a friendly animated face on a small display — with optional ambient idle scenes (rainfall, snowfall, a sleeping pixel-art cat).

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

- **Hybrid compute split** — Pi 5 CPU handles orchestration / Whisper STT / Piper TTS / web UI; Hailo-10H NPU does LLM inference + MediaPipe vision. Independent memory pools, no contention.
- **Two-path skill runtime** — Same router, two operating modes. **V1 hybrid** routes through `OpenClawBridge(runtime_mode="ollama")` with our hand-written Python tool implementations and direct Ollama `tool_calls` (94% reliability proven in Phase-1 viability test). **V2 cloud** routes the same skills through `npx openclaw agent` so a cloud LLM drives the full OpenClaw agent loop — unlocking the entire community plugin ecosystem. Auto-selected per query based on whether a cloud key is configured.
- **Dual-layer skill priority** — Always-local native Python skills (timer, pomodoro, reminder, notes, volume, system stats, mode switch, clipboard) take precedence. Network-y skills (weather, wikipedia, currency, news) fall through to the bridge. Conversational fallback to the LLM is last.
- **OpenClaw JS plugin authoring** — `openclaw-service/plugins/<name>/` is a real OpenClaw extension (package.json + openclaw.plugin.json + index.js using `api.registerTool`). Deploys via `setup.sh` into `~/.openclaw/extensions/` with `plugins.allow` auto-wired. The plugin is invoked by the cloud LLM in V2 mode; it's also visible to community OpenClaw users as a standard plugin.
- **OS-keychain secret storage** — All API keys (cloud LLM, OpenWeatherMap) live in macOS Keychain / Linux Secret Service / Windows Credential Manager via `keyring`. Never written to disk in plaintext. Legacy plaintext keys auto-migrated on first read.
- **Phased reliability gates** — Validation criteria for every phase before committing scope. Phase-1 OpenClaw viability passed at 94%. Phase-4 stability gate pending.
- **Plug-and-play USB-C interface** — Linux USB gadget mode composite device (HID + Mass Storage + CDC Serial). Zero-install setup across macOS, Windows, Linux hosts.
- **Send-to-Lumi global hotkey** — `Cmd+Alt+L` / `Ctrl+Alt+L` from any app: captures selected text (via simulated copy), queues it as context for Lumi's next turn, surfaces a macOS notification + a 📎 row in the chat UI.
- **ChromaDB long-term memory** — Conversations embedded and recalled across sessions via `all-MiniLM-L6-v2`. Browser in the web UI.
- **Speaker verification** — On-device voice biometrics (Resemblyzer) so Lumi only responds to its owner. Embeddings stored as math vectors, never raw audio.
- **Web chat as voice loop's twin** — Same SkillRouter, ConversationManager, and audit log path as the voice loop. Lets you exercise the entire stack from the browser without speaking. Shows handler badges (`native` / `tool` / `openclaw` / `llm`) and per-turn latency.
- **Custom Pi OS image** — `pi-gen`-built distribution with all drivers, models, Node.js, OpenClaw 2026.04.20 (pinned), and services pre-configured. `log2ram` for SD card longevity.
- **9-step onboarding flow** — Cross-device experience: voice enrollment, permission gates (with inline disclosures), skill curation, hotkey + weather-location config, face style with Twemoji cycling preview.
- **Privacy-first design** — Camera frames discarded immediately, active-indicator LEDs, granular per-skill permissions, full audit log, one-button data export, one-button factory reset.
- **Tamagotchi-style idle scenes** — When Lumi is idle, swap the face for an ambient scene (rain, snow, sleeping cat) instead of a static expression. Pluggable framework for community sprite packs.

Full architectural decision log and phase-by-phase development plan in [CLAUDE.md](CLAUDE.md).

---

## Privacy

This matters enough to call out clearly:

- **Local-first by default** — V1 hybrid mode runs every LLM call on-device. No cloud usage unless you explicitly add an API key in Settings → Cloud LLM.
- **API keys in the OS keychain** — Cloud LLM keys and OpenWeatherMap keys go to macOS Keychain / Linux Secret Service / Windows Credential Manager via `keyring`. Never written to disk in plaintext. The settings UI shows masked indicators (`sk-a…1234`); the full key is never sent back to the browser.
- **PII masking before cloud calls (V2)** — When the cloud LLM is active, transcripts are scanned for names, emails, phones, addresses, credit cards, and API keys, and replaced with stable pseudonyms (`<PERSON_1>`, `<EMAIL_1>`) before any HTTP request leaves the device. The cloud reply is unmasked locally before you see it. The audit log stores the masked version too — even our own logs don't keep raw PII.
- **No telemetry** — Nothing is reported back to us
- **Camera frames are never stored** — Only gesture landmarks used, frames discarded immediately
- **Skills are opt-in and audited** — Every skill (native + OpenClaw plugin) is individually enableable. Every invocation is logged in the audit trail with source, skill name, masked input, and result.
- **You can export everything** — One button bundles every user file on disk into a ZIP
- **You can wipe everything** — One button factory resets to first-boot state

Lumi has WiFi (used only by skills you explicitly enable). The camera has an active-indicator LED whenever it's running. V2 hardware includes a physical privacy shutter.

---

## Roadmap

### V1 (working today, pre-hardware)
- Local LLM (qwen2.5:7b on Ollama), Whisper STT, Piper TTS
- Voice loop with state machine (idle → listen → think → speak) + chrome'd face (clock, weather, status band, optional idle scenes)
- 8 native Python skills (timer, pomodoro, reminder, notes, volume, system stats, mode switch, clipboard)
- 4 external-API skills via direct Ollama tool_calls (weather, wikipedia, currency, news) — 94% reliability proven in Phase-1 viability test
- ChromaDB long-term memory (semantic recall across sessions)
- Web dashboard at `localhost:8080`: chat UI, journal (LLM-summarized daily entries), settings, dev panel with skill test panel, skill audit log
- 9-step onboarding flow with voice enrollment, granular permissions, hotkey + weather location config, face style picker
- Send-to-Lumi global hotkey (`Cmd+Alt+L` / `Ctrl+Alt+L`) with macOS notification on capture
- OS-keychain secret storage, data export, factory reset
- HailoBackend stub ready for Pi 5 deployment (Hailo 5.3+ protocol quirks pre-baked)

### V2 (next)
- **Cloud LLM as OpenClaw operator** — Claude / GPT / Gemini drives OpenClaw's agent loop, unlocking the entire community plugin ecosystem (Gmail, Calendar, Spotify, GitHub, Things, …). Auto-routes per query based on whether a key is set in Settings.
- **PII masking + pseudonymization** ships with V2 cloud — transcripts are scrubbed of names, emails, phones, addresses, credit cards, API keys before any HTTP call leaves the device. Replies are unmasked locally.
- **Optimistic + streaming chat UI** — your message renders on Enter (not after the model replies), responses stream token-by-token
- **Skills marketplace search** — Lumi can search and offer to install OpenClaw skills mid-conversation
- **Sprite-pack uploader** — upload custom idle-scene PNG packs from `/settings/sprites`
- **Gmail + Calendar JS plugins** — read-only via dedicated app passwords (V1 security policy stays)
- **Cost + latency guardrails** for cloud mode — per-request token budget, fall-through to V1 hybrid on cloud failure, audit log shows $$ per turn
- **Send-to-Lumi tier 3 + 4** — right-click "Send to Lumi" macOS Services bundle; Chrome/Firefox browser extension
- **MCP protocol integrations** — Google Drive, Slack, GitHub via standard MCP servers (scaffolding already laid in `src/lumi/skills/mcp_bridge.py`)
- **Mechanical key switches + rotary volume dial** (hardware)
- **ElevenLabs premium voice option** — higher-quality TTS as paid upgrade
- **Cloud backup** to your own Drive / Dropbox / iCloud
- **Premium enclosure with physical privacy shutter**
- **Multi-user voice profiles** — household members can each enroll
- **Custom wake-word training** — pick any name beyond the curated palette
- **Claude Code integration** — developer copilot add-on

### Send selected text to Lumi (V1, available now)

Lumi has a host-side helper that grabs the text you're looking at and queues it as context for your next conversation. Two ways in:

- **Global hotkey**: `Cmd+Shift+L` (macOS) / `Ctrl+Shift+L` (Linux/Windows) from any app. Simulates `Cmd+C`, reads the clipboard, queues the result. If nothing is selected, falls back to whatever's already on the clipboard. Run with: `uv run lumi hotkey`
- **HTTP endpoint**: `POST /api/context` with `text=...` (for scripts, browser extensions, or future right-click integrations)

Permission gated on `clipboard_enabled`. The voice loop picks up queued context at the top of its next turn and injects it into the LLM's system prompt; the file is deleted after consumption. Audit log records the source + length, never the body.

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
uv run lumi web                       # web dashboard only
uv run lumi run --backend ollama      # voice loop with local Ollama
uv run lumi run --backend mock        # voice loop with mock LLM (no Ollama needed)
uv run lumi hotkey                    # send-to-Lumi global hotkey daemon
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
