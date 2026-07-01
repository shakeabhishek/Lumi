# Lumi V1 — Bill of Materials

> Living document. Refined as we order, assemble, and learn.
> Status legend: 🟢 on order · ⚪ to order · 🟡 needs verification before ordering · ❌ dropped/deferred from V1

---

## Ordering waves

**Wave 1 — ✅ ORDERED 2026-06-20** (see *Orders placed* below for line items + totals). Everything whose spec is settled and doesn't depend on
inspecting a board/box first:
- **Raspberry Pi 5 16GB** (see Core compute note) · Active cooler · SanDisk Extreme 256GB A2 ·
  **Raspberry Pi Touch Display 2** (7", ships with Pi 5 DSI cable) · **SmartiPi Touch Pro 3
  – Large** (Adafruit 6361, the enclosure) · **ReSpeaker 2-Mics HAT V2.0** (confirm V2.0,
  not V1) · Seeed Mono Enclosed Speaker 4R 5W · Camera Module 3 Wide (body) · 27 W PSU · USB-C cable ·
  *(30 mm case fan = optional/thermal-gated — the active cooler + rear grills likely suffice
  without the AI HAT; add only if a sustained-load test runs hot. M2.5 standoffs only if the
  SmartiPi + Touch Display 2 don't already include enough — verify in hand. Acrylic kit =
  optional bench aid; rubber feet dropped — SmartiPi has its own weighted base.)*
- *(**AI HAT+ 2 deferred — do NOT order with Wave 1.** Now optional/vision-only, pending the
  Pi-CPU vision benchmark — see Open questions. Not ordered; nothing to cancel.)*
- **Add if you don't own one:** a microSD card reader for flashing the OS image — not
  otherwise in this BOM.

**Wave 2 — order after the camera arrives** (and the AI HAT+ 2, *only if* the vision benchmark says it's needed — each depends on what's in the box):
- **Booster header for the ReSpeaker** — with the AI HAT+ 2 deferred, the ReSpeaker mounts on
  the Pi 40-pin header and only needs to clear the **active cooler**: a short **~11 mm booster**
  is the likely fit (not the tall 12–15 mm one). Verify clearance in hand. *(Only revert to the
  taller 12–15 mm header if the vision benchmark later adds the AI HAT+ 2 and the ReSpeaker has
  to stack on top of it.)*
- **CSI camera cable (15→22-pin)** — some Camera Module 3 SKUs now include the Pi 5 cable;
  check the box first to avoid a duplicate.

*(Assembly, not ordering — **only if the HAT is bought**: the AI HAT+ 2 includes its Hailo heatsink in the box — install it.)*

**Optional / low-risk:**
- **DSI 300 mm cable** — orderable any time; only needed for the final easel routing
  (the bundled 12 cm cable covers bench testing). Confirm the panel side is 15-pin.
- **USB-C power/data splitter** — bench-only, USB-gadget testing. Skip if starting on WiFi.

---

## Orders placed (2026-06-20 — 06-21)

Core V1 prototype ordered across three vendors. **Grand total: $578.92, all paid by credit card.**
See `lumi-expense-report.pdf` for the documented business purpose of each line.

| Vendor · Order # | Item | Price |
|---|---|---|
| **CanaKit** · #W062016505074 | Raspberry Pi 5 16GB | $305.00 |
| | Raspberry Pi 5 Active Cooler | $11.95 |
| | CanaKit 5A USB-C PD Power Supply | $14.95 |
| | Raspberry Pi Touch Display 2 (7″) | $87.95 |
| | Camera Module 3 – Wide | $37.95 |
| | Pi 5 Camera Cable 200 mm (`CBL-CAM-MINI-200`) | $1.00 |
| | Shipping | $37.95 |
| | **CanaKit subtotal** | **$496.75** |
| **Adafruit** · #3699727 | SmartiPi Touch Pro 3 – Large (PID 6361) | $39.99 |
| | 2×20 Extra-Tall Stacking Header (PID 1979) | $2.95 |
| | Shipping ($8.72) + Tax ($4.58) | $13.30 |
| | **Adafruit subtotal** | **$56.24** |
| **Seeed Studio** · #4000544326 | ReSpeaker 2-Mics Pi HAT V2.0 | $13.99 |
| | Mono Enclosed Speaker – 4R 5W | $2.00 |
| | Shipping | $9.94 |
| | **Seeed subtotal** | **$25.93** |
| | **GRAND TOTAL** | **$578.92** |

**Substitutions vs. plan:** power = **CanaKit 5A USB-C PD** supply (not the official 27 W brick — equivalent 5 V/5 A PD, fine for the Pi 5); header = **Adafruit 1979 2×20 extra-tall** (not a short ~11 mm booster — works, just more clearance; confirm it still fits the SmartiPi cavity).

**⚠️ Still outstanding (NOT in these three orders):**
- **microSD card** (SanDisk Extreme 256GB A2) — **ordered separately on Amazon** (not in these 3 invoices); reimbursement to be filed later.
- **SmartiPi Display Power Kit – Large** (Amazon B0F74DMCXR) — **to order.** Required to power the Touch Display 2 over **USB-C** instead of the GPIO header, so the **ReSpeaker** (no pass-through) can have the GPIO pins. See the "Touch Display 2 power" open question.
- USB-C ↔ USB-C data cable — optional (host-gadget testing only).
- AI HAT+ 2 — intentionally deferred (vision benchmark).
- Case fan / M2.5 standoffs — optional / check what the case + display include.

---

## Core compute

| Item | Qty | Status | Notes |
|---|---|---|---|
| [Raspberry Pi 5 (16GB)](https://www.raspberrypi.com/products/raspberry-pi-5/) | 1 | 🟢 *(ordered — CanaKit, $305)* | **16GB (re-revised 2026-06-20, reversing the 06-15 8GB call).** The 8GB call assumed the LLM lived *off* Pi system RAM (Hailo or cloud). New plan: **cloud-primary + a small local LLM on the Pi 5 CPU** as the offline/private floor, with the **AI HAT+ 2 now optional** — so local inference adds ~1 GB to *system* RAM and the HAT's 8 GB can't be assumed present. 16GB keeps comfortable headroom (~12–13 GB free at idle) for Chromium + OpenClaw + ChromaDB + a CPU-resident model. Accepts the 2026 DRAM-shortage price/availability premium for that margin. **Fallback:** if 16GB is unavailable or too costly, 8GB still works (~3 GB free) but tight. Verify real RSS with `psutil` in Phase 5. |
| [Raspberry Pi AI HAT+ 2](https://www.raspberrypi.com/products/ai-hat/) | 0–1 | 🟡 **deferred** | **Optional, vision-only, pending benchmark (2026-06-20).** No longer runs the LLM — that's cloud + Pi CPU now (the Hailo is memory-bandwidth-bound and no faster than the Pi CPU on 1–1.5B models). Its only remaining job is offloading **continuous MediaPipe vision** off the CPU, needed **only if** the Pi 5 CPU can't sustain vision + a live turn (Phase-5 benchmark). If bought: 40 TOPS + 8GB, takes the single PCIe lane, needs HEF-converted vision models, ships with 16mm stacking header + spacers + screws. (Not ordered — the earlier 🟢 status was never acted on.) |
| [Active cooler for Pi 5](https://www.raspberrypi.com/products/active-cooler/) | 1 | 🟢 *(ordered — CanaKit, $11.95)* | **Required**, not optional. Cools the Pi SoC. Sits under the AI HAT+ via its stacking header. |
| Hailo heatsink (**included** with AI HAT+ 2) | — | ⏸ *(only if HAT bought)* | **No separate purchase — it's in the AI HAT+ 2 box.** A passive heatsink with pre-fitted thermal pads (aligned to the Hailo NPU, SDRAM, and power regulator) + push-pins. Labeled "optional" but **highly recommended — install it**: the Hailo-10H has no metal heatspreader and throttles under LLM load without it. Peel the pad films, push-pin mount (firm but careful not to crush components). The Pi's active cooler handles the SoC; this handles the NPU. |

---

## Storage

| Item | Qty | Status | Notes |
|---|---|---|---|
| [SanDisk Extreme 256GB A2 V30 microSD (`SDSQXAV-256G-GN6MA`)](https://www.amazon.com/SanDisk-Extreme-microSDXC-Memory-Adapter/dp/B09X7CRKRZ) | 1 | 🟢 *(ordered separately on Amazon — reimbursement filed later, not in the 3 invoices)* | **SanDisk Extreme 256GB A2 V30 (chosen 2026-06-20; was Extreme Pro 512GB → Samsung Pro Plus → brand-agnostic → this).** OS, models, ChromaDB, user data (+ V2 voices/plugins/MCP/memory/backup staging); 256GB leaves comfortable headroom (working set fits in well under half). **Picked on the two specs that matter — A2 class + 256GB — from a reputable brand, deliberately the plain "Extreme" not "Extreme Pro."** The A2 random IOPS (~5000/2000) are usable on the Pi 5 via SD command queueing and are what the OS/ChromaDB workload leans on; the ~190 MB/s sequential rating is **irrelevant** — the slot is UHS-I/SDR104 (~90 MB/s real) — but you're not paying an Extreme-Pro premium for it. SanDisk's endurance/reliability rep is the tiebreaker for a 24/7 appliance (over cheaper PNY/etc.). No NVMe by design (PCIe lane reserved for the AI HAT+ if fitted; freed if skipped — storage stays microSD regardless). |

---

## Display

> **Decision (2026-06-20): switched 4.3" Waveshare DSI → official Raspberry Pi Touch
> Display 2 (7", 720×1280) in a SmartiPi Touch Pro 3 enclosure.** Rationale: a
> **finished, professional-looking product now** for Lang Center demos + customer-discovery
> interviews — a weighted tilting stand with clean port access and a front camera mount
> reads as "a product," vs. exposed acrylic boards. Deliberate **form-factor change** (small
> ambient face → 7" touch-tablet companion); supersedes the 06-14 4.3" decision below.
> Display **~$87 (CanaKit)** + case $40 + fan ≈ **$135 all-in. Downstream / now-open:**
> (1) **audio placement** — Pi+ReSpeaker live in the case cavity; mics/speaker must still
> hear/face the user (route out the back cover or mount externally) — *biggest open risk*;
> (2) **cavity clearance** — verify Pi 5 + active cooler + ReSpeaker fit the 45 mm "Large"
> cavity, and note this likely **precludes also fitting the optional AI HAT+ 2** (two HATs
> won't fit) — the case and HAT decisions now interact; (3) **camera** — Cam 3 Wide should
> fit the v3 mount, verify the wide lens clears the front plate; (4) **UI re-canvas** — run
> the panel **landscape at 1280×720** (rotate native 720×1280) and rescale the React
> `device_display` app to it (higher res, same landscape orientation — a rescale, not a rebuild).
>
> *(Superseded — kept for history.)* **Decision (2026-06-14): 3.5" SPI → 4.3" rectangular
> DSI.** The SPI panel drove an fbtft framebuffer at ~10–15 fps — too choppy for the Chromium
> animated face; the 4.3" DSI ran at 60 Hz on a single ribbon and freed the SPI bus. Right
> call then; now itself superseded by the 7" Touch Display 2 for product-finish reasons.

| Item | Qty | Status | Notes |
|---|---|---|---|
| [Raspberry Pi Touch Display 2 (7", 720×1280)](https://www.raspberrypi.com/products/touch-display-2/) | 1 | 🟢 *(ordered — CanaKit, $87.95)* | **⚠️ Must be the 7″ version** — the 5″ Touch Display 2 shares the same 720×1280 spec but is physically smaller and **will NOT fit the SmartiPi Touch Pro 3** (case is 7″-only). Official 7" IPS, 5-point capacitive touch, DSI. Lumi's face, run **landscape (1280×720)**. **~$87 (CanaKit;** confirm the listing says 7″ — resolution alone won't distinguish it from the 5″). Cheaper than Adafruit's ~$154 (Adafruit 6079 = same 7″ panel). Ships with the Pi 5 DSI cable + power connection. Replaces the Waveshare 4.3". Touch unused in V1 but enables a future touch UI. |
| [SmartiPi Touch Pro 3 – Large (Adafruit 6361)](https://www.adafruit.com/product/6361) | 1 | 🟢 *(ordered — Adafruit, $39.99)* | **The enclosure** ($39.99) — weighted tilting stand, VESA 75 mm, side power button (Pi 5), microSD extender, front camera mount (Cam v2/v3), 45 mm "Large" back cover for a HAT-depth cavity. Built specifically for the Touch Display 2. **Fan not included.** |
| 30 mm case fan (SmartiPi Pro 3) | 0–1 | ⚪ *(optional — thermal-gated)* | **Likely not needed for V1.** With the AI HAT+ 2 deferred (it was the big heat source), the Pi 5 **active cooler** + the case's **rear grill vents** should handle the lighter load. Treat a 30 mm case fan as a **fallback**: run a sustained-load test (Chromium + CPU LLM, ~24/7) and add it only if cavity/CPU temps creep up. |

---

## Audio

| Item | Qty | Status | Notes |
|---|---|---|---|
| [ReSpeaker 2-Mics Pi HAT V2.0](https://www.seeedstudio.com/ReSpeaker-2-Mics-Pi-HAT.html) | 1 | 🟢 *(ordered — Seeed, $13.99)* | Mics + speaker out + 3 RGB LEDs + 1 button. **Compact Pi-HAT footprint** (chosen over the bigger XVF3800 array for size). Sits on top of the AI HAT+ — but **only with a taller stacking header** (see below). Pins: GPIO17 (button), SPI0 (APA102 LEDs), I2S (TLV320AIC3104 codec), I2C-1. None clash with the AI HAT+ (PCIe FPC + power only); display is DSI so SPI0 is free for the LEDs. Order **V2.0** (not V1 — V2.0 adds Pi 5 support). |
| [GPIO booster/stacking header for the ReSpeaker (~11 mm)](https://www.adafruit.com/product/1979) | 1 | 🟢 *(ordered — Adafruit 1979, $2.95; **extra-tall**, not a short booster — fine, just confirm SmartiPi cavity fit)* | **Purpose: raise the ReSpeaker just enough to clear the Pi 5 active cooler.** With the AI HAT+ 2 deferred, the ReSpeaker mounts **directly on the Pi's 40-pin header** — so the *extra-tall* 12–15 mm header (which existed only to stack on top of the AI HAT+) is **no longer needed.** A HAT on the *standard* header tends to foul the active cooler, so a **short ~11 mm booster is the usual fix**; the 2-Mics HAT is mostly top-side so a standard header *might* clear — **verify with the cooler + ReSpeaker in hand** before buying. (If the vision benchmark later adds the AI HAT+ 2, revert to the taller 12–15 mm header to stack on top of it.) Shorter stack also fits the SmartiPi cavity more easily. |
| [Seeed Mono Enclosed Speaker – 4R 5W (`p-5931`)](https://www.seeedstudio.com/Mono-Enclosed-Speaker-4R-5W-p-5931.html) | 1 | 🟢 *(ordered — Seeed, $2.00)* | **$2, Seeed's own ReSpeaker-line speaker.** 4Ω matches the 2-Mics HAT amp; **enclosed** (resonance chamber → fuller voice than a bare cone, and it still carries when firing out a SmartiPi rear vent). Listed as a companion on the 2-Mics HAT page, spec'd for the ReSpeaker family, single-vendor with the HAT. **Verify it ships with the JST PH 2.0 mm 2-pin connector** that plugs straight into the HAT's speaker socket — the ReSpeaker line uses JST PH2.0, almost certainly yes, but the listing text didn't print it explicitly. (Bare CQRobot 4Ω JST speaker is the fallback if the connector differs.) |

**AEC note:** the 2-Mics HAT has **no hardware echo cancellation**, so Lumi hears its own
voice over the mics — barge-in/interrupt-while-speaking is hard. Mitigations: physically
**aim the speaker away from the mics** (the JST speaker is detached and positionable), and
plan software **WebRTC AEC** on the Pi 5 CPU. Reliable barge-in is a stretch goal, not a
V1 gate — wake-word + button + "open-palm/stop" gesture cover the common cases. *(This is
the tradeoff for the compact HAT over the XVF3800's hardware AEC — accepted for size.)*
**Driver note:** install via Seeed's *new* Pi 5 wiki guide (the old v1 script can corrupt
the desktop); V2.0's TLV320AIC3104 codec is the version that adds Pi 5 support.

---

## Camera

| Item | Qty | Status | Notes |
|---|---|---|---|
| [Pi Camera Module 3 Wide](https://www.pishop.us/product/raspberry-pi-camera-module-3-wide/) | 1 | 🟢 *(ordered — CanaKit, $37.95)* | 102° FOV, autofocus. Gestures + presence. Uses the Pi 5's **second** MIPI port (display takes the first — both coexist, no multiplexer). |
| Pi 5 Camera Cable 200 mm (`CBL-CAM-MINI-200`) | 1 | 🟢 *(ordered — CanaKit, $1.00)* | The Pi 5 22-pin → Camera Module 3 15-pin CSI cable. **Verify at assembly:** the camera end is 15-pin (Cam 3, not 22↔22), and 200 mm reaches the SmartiPi front mount (short run — almost certainly fine). |

---

## Power & connectivity

> **Power/connectivity (2026-06-15):** **Power always comes from the external 27 W PSU**
> (USB-C from the wall) — never from the host PC. That settles power cleanly and removes
> the brownout risk. For **host-PC connectivity we're keeping both paths to evaluate:**
> WiFi/network (Pi 5 onboard, always available) **and** USB peripheral/gadget mode.
>
> **Key caveat — single USB-C port contention:** the Pi 5 has one USB-C port. With the
> 27 W PSU plugged in for power, that same port can't *also* carry USB-gadget data in the
> assembled unit. Combining power + gadget data on one connector needs the splitter
> (capped at **15 W → brownout** under Hailo load) or GPIO-pin power (bypasses OVP + our
> header is occupied). So in practice: **WiFi is the reliable always-on transport; USB
> gadget is an experimental path** best validated on the bench (bare Pi / light NPU load)
> rather than alongside 27 W power. We try both and see which UX wins.

| Item | Qty | Status | Notes |
|---|---|---|---|
| CanaKit 5A USB-C PD Power Supply (`DCAR-CANAKIT-PD-5A`) | 1 | 🟢 *(ordered — CanaKit, $14.95)* | **Sole power source** (external, from wall). **Substituted for the official 27 W brick** — the CanaKit 5 V/5 A PD supply is the equivalent spec for the Pi 5 and delivers the same headroom. |
| WiFi (onboard Pi 5) | — | ✅ | Primary host transport. No hardware to order — built into the Pi 5. |
| [USB-C to USB-C cable (1m, braided)](https://www.amazon.com/s?k=usb-c+to+usb-c+cable+1m+braided) | 1 | ⚪ | For evaluating the USB-gadget host-data path. See port-contention caveat above. *Link is a search — any data-rated cable works.* |
| [USB-C Power/Data Splitter (bench testing only)](https://thepihut.com/products/usb-c-data-power-splitter) | 1 | 🟡 | **Only** if testing gadget data + power on one port; caps at 15 W, so keep NPU load light during those tests. Not for the final powered build. |

---

## Structure / enclosure

> **The SmartiPi Touch Pro 3 is the enclosure** (see Display section) — it replaced the
> earlier "no commercial case fits → open-frame acrylic base" plan once the design became a
> 7" Touch Display 2 + a single HAT (ReSpeaker), with the AI HAT+ 2 optional. **Most mounting
> hardware is included:** the SmartiPi ships its case/Pi screws, and the Touch Display 2 ships
> 8× M2.5 screws + ribbon cables. **Caveat:** the cavity fits ~Pi 5 + cooler + one HAT; if the
> vision benchmark later forces the AI HAT+ 2 in, two HATs likely won't fit and the enclosure
> gets revisited.

| Item | Qty | Status | Notes |
|---|---|---|---|
| A few M2.5 standoffs/screws | as needed | 🟡 *(verify in hand)* | Likely needed to secure the ReSpeaker above the cooler inside the cavity. **First check what the SmartiPi + Touch Display 2 already include** — may be a no-buy. |
| [Open-frame acrylic kit](https://www.amazon.com/Stackable-Compatible-Raspberry-Open-Frame-Heatsinks/dp/B0GXTHHV71) | 0–1 | ⚪ *(optional bench aid)* | Only if you want a tidy dev rig before the SmartiPi arrives — **not part of the shipping build.** Skip if you're fine bench-testing on loose boards. |

*(Dropped from the BOM: rubber feet — the SmartiPi has its own weighted base. The earlier
"front easel" arrangement is superseded by the SmartiPi tablet form: Pi + cooler + ReSpeaker
sit in the case cavity, the camera mounts on the SmartiPi front plate above the screen as
"eyes," and the speaker/mics vent out the rear grills.)*

---

## Open questions / verify before ordering

- **AI HAT+ 2 — buy or skip?** 🟡 *(biggest open spend, 2026-06-20)* — gated on a **Pi-CPU vision benchmark**: can the Pi 5 CPU run continuous MediaPipe vision (presence + gesture) while a live turn fires (CPU tiny-LLM + Whisper + Piper + Chromium)? **Pass → ship the 16GB Pi, no HAT** (PCIe lane frees up). **Fail → buy the AI HAT+ 2 for vision offload only** (HEF-convert the vision models). Run before committing the HAT spend. Downstream: this also decides the ReSpeaker stacking-header height and whether the Hailo heatsink/cooling notes apply.
- **Audio in the closed case** 🟠 *(biggest new risk, 2026-06-20; plan forming)* — the SmartiPi seals the Pi + ReSpeaker behind the display. **Plan: use the case's rear grill vents.** **Speaker = easy** — detachable JST unit, mount it firing out a rear vent (rear-firing is fine for voice). **Mics = harder** — the 2-Mics HAT mics are **soldered to the board**, so they can't be routed on a cable like the speaker; they hear from wherever the HAT sits, so orient the HAT's mic ports toward a vent. **Two caveats:** (a) rear vents face *away* from the user (who's at the front) → weaker pickup, OK for near-field with wake-word + button; (b) **do not vent mics + speaker out the same grill** — inches apart with no hardware AEC maximizes echo and kills barge-in. **Separate them** (mics one vent, speaker another, as far apart as the cavity allows) + plan software WebRTC AEC. **Validate pickup early; fallback** = a small front-mounted USB mic if rear pickup is too weak (fixes direction + echo separation, and revisits the 2-Mics-vs-array call for the tablet form).
- **SmartiPi cavity clearance** 🟡 — verify Pi 5 + active cooler + ReSpeaker HAT fit the 45 mm "Large" back-cover cavity. Note: this likely **rules out also fitting the optional AI HAT+ 2** (two HATs) — if the vision benchmark demands the HAT, revisit the enclosure.
- **Camera lens clearance** 🟡 — the SmartiPi front mount lists Cam v2/v3; the **Cam 3 Wide** is the v3 board with a wider lens — verify it seats and the lens clears the front-plate aperture.
- **Touch Display 2 power** ✅ *(CONFIRMED AT BENCH 2026-06-30)* — the Display 2 **requires the GPIO power cable IN ADDITION to the DSI ribbon — on the Pi 5 too.** The DSI ribbon carries video + touch (low power) only; the **backlight + panel electronics need 5V from the GPIO lead** (red → **pin 2 / 5V**, black → **pin 6 / GND**). Symptom without it: panel *detects*, touch works, mode sets — but screen stays **black** (this exact thing happened today). *(Corrects the earlier "Pi 5 powers it through the ribbon" assumption — that was wrong.)* **⚠️ Conflict (caught 2026-06-30):** the **ReSpeaker 2-Mics HAT has no GPIO pass-through**, so it and the display contend for the same 5V/GND header pins. **Solution (to order):** **SmartiPi Display Power Kit – Large** (Amazon B0F74DMCXR) — powers the display + Pi from **USB-C** via a panel-mount cable + splitter, freeing the GPIO header for the ReSpeaker. Bench-verified today with the direct GPIO cable (ReSpeaker not yet mounted). **Display rotation:** console runs **landscape via `fbcon=rotate:3`** in `/boot/firmware/cmdline.txt` (verified; the `video=…,rotate=` plane-rotation method did NOT work on the rp1-dsi console driver). The future Chromium kiosk will need a matching **compositor transform**.
- **Camera cable** 🟡 — ordered **`CBL-CAM-MINI-200`** (200 mm Pi 5 "mini"/22-pin camera cable). **Verify:** (a) the camera end is **15-pin** for the Camera Module 3 (i.e. a 22↔15 adapter, not 22↔22); (b) 200 mm reaches the SmartiPi front mount — almost certainly fine (Pi sits right behind the display, short run), confirm routing at assembly; a 300 mm is only a cheap backup if it's tight. (The display DSI cable ships with the Touch Display 2.)
- **GPIO pin usage** ✅ *(largely resolved — AI HAT deferred)* — with no second HAT, the ReSpeaker 2-Mics (GPIO17 button / SPI0 LEDs / I2S / I2C-1) has the 40-pin header to itself; display is DSI and camera is CSI, so nothing competes for those pins. Re-check only if the vision benchmark later adds the AI HAT+ 2.
- **Stack clearance** 🟡 — eyeball active-cooler height against the ReSpeaker stacking header inside the SmartiPi cavity (see "SmartiPi cavity clearance" above).
- **device_display rescale** 🟡 (software) — React app currently 480×320 landscape; rescale to **1280×720** to match the Touch Display 2 run **landscape** (rotate its native 720×1280). Higher res, same landscape orientation — a rescale, not a re-layout.
- **Hailo NPU cooling** ✅ resolved *(only matters if the HAT is bought)* — the AI HAT+ 2 ships with a passive heatsink + thermal pads in the box. Nothing to order; just install it (highly recommended) to avoid throttling.
- **Power/data architecture** 🟡 — V1 = 27 W PSU + host comms over network (splitter dropped). Decide if/when to pursue the "USB-C to any host" product vision (needs a real 5 A-PD + data solution). See `bom_risk_analysis.md`.
- **SD write-hardening** 🟡 (software, Phase 5/6) — disable swap, `tmpfs` for `/tmp` + `/var/log`, batch ChromaDB writes. Mostly already covered by planned log2ram. *(With 16GB and swap disabled there's ample cushion; still watch Chromium growth over very long uptime.)*
- **Pre-bake onnx embedding model** 🟡 (software, Phase 6) — ChromaDB's default ONNX `all-MiniLM-L6-v2` downloads (~80 MB) on first use. Bake it into the OS image so onboarding doesn't wait on a network fetch.
- **ReSpeaker driver** 🟡 — install via Seeed's new Pi 5 wiki guide, not the old v1 script; validate `aplay`/`arecord`.
- **Software AEC** 🟡 (software) — the 2-Mics HAT has no hardware echo cancellation; plan a WebRTC AEC pass and aim the speaker away from the mics. Barge-in is a stretch goal, not a V1 gate.

---

## Explicitly deferred to V2 (not ordered)

Mechanical key switches (NeoKey 1x4 + Kailh Brown + keycaps), rotary encoder + knob,
premium frosted enclosure, integrated camera privacy shutter. Out of scope to ship V1 faster.

---

## Sources (research, 2026-06-14–15)

- [Waveshare 4.3inch DSI LCD — 800×480, 60 Hz, rectangular](https://www.waveshare.com/4.3inch-dsi-lcd.htm)
- [Waveshare Pi 5 DSI FPC cable — 200/300/500 mm, 22→15-pin](https://www.waveshare.com/pi5-display-cable.htm)
- [Pi 5 dual MIPI: camera + display simultaneously — The Pi Hut](https://support.thepihut.com/hc/en-us/articles/13853926990493-Can-I-use-my-existing-Camera-Display-CSI-DSI-cable-with-Raspberry-Pi-5)
- [Buy a Raspberry Pi AI HAT+ — Raspberry Pi](https://www.raspberrypi.com/products/ai-hat/)
- [AI HATs — Raspberry Pi Documentation](https://www.raspberrypi.com/documentation/accessories/ai-hat-plus.html)
- [KKSB Case for Pi 5 with Space for HATs](https://kksb-cases.com/products/kksb-raspberry-pi-5-case-with-space-for-hats-addon-boards-and-cooler)
- [EDATEC Metal Case for Pi 5 + HAT](https://www.pishop.us/product/metal-case-for-raspberry-pi-5-hat/)
- [Stacking multiple official HATs — Raspberry Pi Forums](https://forums.raspberrypi.com/viewtopic.php?t=372508)
- [Raspberry Pi Touch Display 2 (7", 720×1280) — Raspberry Pi](https://www.raspberrypi.com/products/touch-display-2/)
- [SmartiPi Touch Pro 3 for Touch Display 2 — Large (Adafruit 6361)](https://www.adafruit.com/product/6361)
