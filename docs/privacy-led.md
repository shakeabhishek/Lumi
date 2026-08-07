# The camera privacy light

**Resolved 2026-08-06: the on-screen indicator is V1's privacy signal. The
ReSpeaker HAT's LEDs cannot serve this purpose, and the roadmap item asking
for them is closed as not-applicable rather than not-done.**

## Why the HAT LEDs are the wrong answer

ROADMAP Tier 3 #8 asked for a "camera-active **privacy light** (red when
camera on)", and CLAUDE.md's privacy-by-design section described a NeoPixel on
the ReSpeaker HAT as the intended mechanism, with the on-screen icon as a
stand-in until it was wired.

The blocker isn't software. **The HAT is sealed inside the SmartiPi Touch Pro 3
enclosure** (confirmed with the user, 2026-08-06). A privacy indicator that
nobody can see is not an indicator. Even a perfectly working APA102 driver
would have produced light trapped inside the case — which is worse than no
light, because the code and the docs would both claim the feature shipped.

This is a hardware-topology conclusion, not a bug: the enclosure decision
(2026-06-20, chosen for product finish) and the HAT-LED plan are simply
incompatible, and nothing noticed because the two were recorded in different
places.

## What was investigated, so nobody repeats it

- SPI was **off** on the device. The HAT's RGB LEDs are APA102 parts driven
  over SPI0, so nothing could ever have worked without enabling it.
- `dtparam=spi=on` was added, the Pi rebooted cleanly (all services active,
  `goodix-touch-rebind` oneshot `success`, touch intact), and
  `/dev/spidev0.{0,1}` appeared.
- `scripts/led_probe.py` wrote red/green/blue/off frames to 3 APA102 LEDs on
  SPI0 without error — proving the bus and the write path, but never that a
  physical LED lit.
- **The SPI line has since been reverted** (`/boot/firmware/config.txt`), since
  it exists only for this dead end. Backup of the pre-change file:
  `/boot/firmware/config.txt.bak-pre-spi-2026-08-05`. SPI stays live until the
  next reboot, then goes away.
- It also remains unconfirmed whether the **v2.0** board has the LEDs at all.
  Its overlay (`respeaker-2mic-v2_0`) declares only the TLV320AIC3104 codec,
  I2S and a fixed clock — no LED node. The v1.0/WM8960 board is the one
  documented as carrying 3 APA102s. Moot now, but worth knowing.

`scripts/led_probe.py` is kept because it's the fastest way to answer the
"does this HAT have LEDs" question if the enclosure ever opens up.

## What V1 actually ships

The on-screen camera indicator in `App.tsx` — a pulsing rose camera glyph,
driven by `cameraActive`, which `device_samplers.py`'s `vision_liveness_sampler`
derives from the vision worker's presence heartbeat. It goes dark within ~12s
of the worker actually stopping (`camera_enabled` off, or the process down),
so it reflects real capture state rather than a local flag.

Its one honest weakness: it's rendered by the same app the camera feeds, on
the same screen. A physical light is a stronger trust signal because it can't
be faked by the software being watched.

## If a physical light is wanted

It has to be **outside the case**, routed the way the speaker and the USB mic
already are (both external as of 2026-08-06 — see CLAUDE.md's resolved
enclosure-audio question). Options, cheapest first:

1. A discrete LED on a spare GPIO, mounted through the case shell. No SPI, no
   APA102 protocol — `gpiozero.LED` next to `hardware/button.py`, driven from
   the vision worker's capture session start/stop. Needs one BOM line and a
   hole in the enclosure.
2. A single external NeoPixel/APA102 on a short lead. More colour control than
   is needed for "red means recording", and re-adds the SPI dependency.

Either way, wire it off the **same** source as `cameraActive` rather than a
parallel code path, so the physical light and the on-screen icon can never
disagree — a privacy signal that contradicts itself is worse than one signal.

Treat this as a V2 item alongside the physical camera shutter, which has the
same "needs to be reachable from outside the shell" constraint.
