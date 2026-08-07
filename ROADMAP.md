# Lumi — Build Roadmap

Where we are: full software stack runs on the Pi as systemd services
(`ollama` + `qwen2.5:1.5b` brain, `lumi-web` dashboard, `lumi-display`
Chromium face, `lumi-voice` voice loop, `lumi-vision` + `lumi-vision-
capture` gesture/presence pipeline — all auto-start on boot). Text chat,
voice, and camera gestures all work end-to-end with the face reacting;
the device screen shows the live face + CPU/RAM/temp metrics.

**Tier 1 is complete.** The open work is now Tier 2 (make it usable by
someone other than us) and one genuine capability gap: Lumi still answers
to "Hey Jarvis", not "Hey Lumi" — see #1 below.

Dependencies are flagged so we pick by what's unblocked.

## 🔴 The honest gap

1. **Lumi doesn't respond to her own name.** openwakeword ships only
   pre-trained models and there is no `hey_lumi`, so `wake_word_model`
   defaults to `hey_jarvis` as a stand-in — that's what's running on the
   device today. It's a product-identity problem, not a config detail:
   the tagline promises "Hey Lumi" and onboarding invites the user to
   pick from ten names, none of which she answers to.
   - *Done:* custom-model loading path (`OpenWakeWordWake(model_path=…)`,
     drop an ONNX at `models/wake/<name>.onnx`), plus a loud
     `wake.model_missing` error — a name with no matching model used to
     make her silently, permanently deaf with nothing in the logs.
   - *Blocked on:* a GPU. Training is openwakeword's synthetic-data
     Colab notebook, ~1 hour. Full recipe + the on-device validation
     that actually decides whether it ships (false positives over an
     hour of desk conversation; whether she wakes herself through her
     own speaker) in **`docs/wake-word-training.md`**.

## ✅ Tier 1 — Core capabilities (done)

2. **Voice loop (audio I/O)** ✅ — wake word → STT → LLM → Piper TTS →
   speaker, live on `lumi-voice.service`.
   - Capture is now an **external USB mic** (2026-08-06), which resolves
     the enclosure-audio risk by sidestepping it. It doesn't support
     16 kHz while openwakeword and Whisper both require exactly that, so
     `audio/resample.py` does anti-aliased 48→16 kHz conversion, with
     carried filter state on the continuous wake stream.
3. **Vision (camera → presence + gestures)** ✅ **built + deployed
   2026-07-06** — `lumi-vision.service` (MediaPipe, own Python 3.12 venv)
   + `lumi-vision-capture.service` (Picamera2 under the Pi's system
   Python, bridged via shared memory). Wave wakes Lumi; presence drives a
   display-only sleep treatment.
   - Presence **flicker fixed 2026-08-05**: the detector answered "was
     there motion between the last two frames?" with no hysteresis, so it
     oscillated frame-to-frame — 110 `POST /api/presence` per minute, and
     the face blinked between awake and asleep with the user sitting
     right there. Now latched (instant to wake, 20s of continuous
     stillness to sleep): 12/min, i.e. the heartbeat alone.
   - Remaining: tune gesture classification thresholds against a real
     hand, and a full soak.
4. **Cloud LLM ceiling** ✅ — Gemini via `RoutedBackend`, flipped
   cloud-first 2026-07-05.
5. **Interruptibility** ✅ **2026-08-05** — until then *nothing* could
   stop Lumi mid-reply: the wake source is stopped for the duration of a
   turn, the button was never wired, and open palm / thumbs up-down were
   classified, badged, and dropped. Now `speak_streaming(cancel=…)` cuts
   audio mid-utterance and drops queued-but-unplayed sentences, driven by
   two surfaces:
   - **open palm** (vision worker → `.barge_in.json` file drop)
   - **the ReSpeaker button** (GPIO17, real `gpiozero` — one button,
     context-dependent: barge-in while speaking, wake otherwise)

## 🧩 Tier 2 — Make it usable & real

6. **On-device onboarding** — the 9-step first-run flow exists; test
   end-to-end on the Pi, hand it to someone cold. **Never done.**
7. **Activate skills** — OpenWeatherMap key (weather), dedicated
   read-only email/calendar accounts, exercise the skill router + audit
   log.
8. **Memory on the Pi** — verify ChromaDB on-device; pre-bake the ONNX
   embedding model so first-run doesn't stall on a download.
9. **Soak test** — 30–60 min concurrent voice + vision + web. Also the
   best shot at the never-root-caused `/chat/stream` hang under sustained
   load (found 2026-05-23, still open in CLAUDE.md's V2 table).

## 🎨 Tier 3 — Polish & delight (the Tamagotchi soul)

10. **Face customization** — pixel/vector/terminal/sprite styles,
    sprite-pack upload, the pixel-face redesign (currently "reads off").
11. **Display extras** — listening/thinking indicators, network status.
    ~~camera-active privacy light~~ → **closed as not-applicable
    2026-08-06**: the on-screen indicator ships and is V1's privacy
    signal. The planned NeoPixel lived on the ReSpeaker HAT, which is
    sealed inside the enclosure — a light nobody can see isn't a signal.
    A physical light means an *externally* mounted LED, which is V2
    alongside the shutter. See `docs/privacy-led.md`.
12. **Thumbs up / thumbs down** — classified and badged, still wired to
    nothing. The original framing ("yes/no confirmation") has no caller:
    nothing in Lumi asks a yes/no question today, so the answering half
    would be built to a spec with no consumer. Better first step is
    thumbs-down as a second barge-in surface (natural semantics, no
    invention) and recording both as feedback on the last reply.

## 🔧 Tier 4 — Hardening & productize

13. **Enclosure assembly** — largely done; the Pi + HAT are in the
    SmartiPi case with the speaker and mic mounted externally. Remaining:
    the sealed-case **thermal test** (audio vents are no longer a
    concern now that both transducers are outside).
14. **SD-card hardening** — log2ram is installed. Do **not** disable
    zram (it's RAM-backed; see AGENTS.md).
15. **OS image (pi-gen)** — bake it all into a flashable `.img`
    (Phase 6). Include the trained wake-word ONNX once #1 lands.

## Recently closed

- ~~**Clean URL**~~ ✅ — dashboard on port 80 at `http://lumi.local/`
  (`f98fc2a`).
- ~~**Protobuf re-lock**~~ ✅ 2026-07-02 — fixed by bumping the whole
  `opentelemetry-*` family together; the env-var workaround is gone,
  don't re-add it.
- ~~**Red test suite**~~ ✅ 2026-08-05 — 8 integration tests had been
  failing since the CSRF middleware landed on 2026-05-21, so the suite
  had stopped being a signal for two and a half months.
- ~~**Mic mute did nothing**~~ ✅ 2026-08-05 — it targeted the
  ReSpeaker's `PGA` control, which no longer exists on that card, and
  reported success anyway.

---

**Suggested next:** #1 (the name — needs a GPU hour, and it's the most
visible gap), then #6/#9 together, since handing onboarding to a cold
user and soaking the stack are the two things that turn "it works when we
drive it" into "it works."
