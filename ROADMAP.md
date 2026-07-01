# Lumi — Build Roadmap

Where we are: full software stack runs on the Pi as systemd services
(`ollama` + `qwen2.5:1.5b` brain, `lumi-web` dashboard, `lumi-display`
Chromium face, `lumi-openclaw` skills gateway — all auto-start on boot).
Text chat works end-to-end with the face reacting; the device screen shows
the live face + CPU/RAM/temp metrics. Audio and vision are not yet wired.

Dependencies are flagged so we pick by what's unblocked.

## 🎙️ Tier 1 — Core capabilities (what makes Lumi *Lumi*)

1. **Voice loop (audio I/O)** — the headline gap; Lumi is voice-first by design but text-only today.
   - *Depends on:* the SmartiPi **Display Power Kit** arriving (frees the GPIO for the ReSpeaker).
   - *Scope:* ReSpeaker driver + ALSA → wake word ("Hey Lumi") → Whisper STT → LLM → Piper TTS → speaker.
2. **Vision (camera → presence + gestures)** — the ambient-awareness differentiator; camera already captures fine.
   - *Depends on:* **MediaPipe on ARM** (trickiest install in the stack — budget real time).
   - *Scope:* presence (wake on sit-down / sleep on leave), gesture vocab (wave / thumbs up-down / open palm / fist), face reacts to you.
   - *Bundles with:* the **Pi-CPU vision benchmark** — the pending AI-HAT buy/skip decision.
3. **Cloud LLM ceiling** — smart hard-turn handling; plumbing is ready (secrets file backend done).
   - *Depends on:* an **API key** (add at `/settings/cloud` → 0600 file).
   - *Scope:* pick provider (Gemini ships; Anthropic/OpenAI via OpenClaw), test cloud escalation via `RoutedBackend`, verify PII masking on the cloud path. **Fastest Tier-1 win.**

## 🧩 Tier 2 — Make it usable & real

4. **On-device onboarding** — the 9-step first-run flow exists; test end-to-end on the Pi, hand it to someone cold.
5. **Activate skills** — OpenWeatherMap key (weather), dedicated read-only email/calendar accounts, exercise the skill router + audit log.
6. **Memory on the Pi** — verify ChromaDB on-device; pre-bake the ONNX embedding model so first-run doesn't stall on a download.

## 🎨 Tier 3 — Polish & delight (the Tamagotchi soul)

7. **Face customization** — pixel/vector/terminal/sprite styles, sprite-pack upload, the pixel-face redesign (currently "reads off").
8. **Display extras** — listening/thinking indicators, network status, camera-active **privacy light** (red when camera on).
9. **Clean URL** — move the dashboard to `http://lumi.local` (port 80, no `:8080`).

## 🔧 Tier 4 — Hardening & productize

10. **Enclosure assembly** — once audio + vision pass on the bench, mount into the SmartiPi case; run the sealed-case **audio-vent + thermal test** (top open risk).
11. **SD-card hardening** — log2ram, disable swap (24/7 appliance longevity).
12. **Protobuf re-lock** — replace the chromadb/protobuf env-var workaround with a proper lockfile fix (Mac-side).
13. **OS image (pi-gen)** — bake it all into a flashable `.img` (Phase 6).

---

**Suggested start (by what's unblocked):**
- Power Kit arrived → **Voice (#1)** — biggest capability jump.
- Not yet → **Cloud (#3, ~30 min with a key)**, then **Vision + benchmark (#2)** since MediaPipe eats time.
