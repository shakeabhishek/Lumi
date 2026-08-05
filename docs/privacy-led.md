# The physical camera privacy light

ROADMAP Tier 3 #8. Status: **SPI enabled and the write path proven; whether
the LEDs physically exist on this HAT revision is unverified.**

## Why it's still open

The on-screen camera indicator ships today (`App.tsx`, driven by the vision
worker's presence heartbeat via `vision_liveness_sampler`, dark within ~12s of
the worker stopping). CLAUDE.md's privacy-by-design section calls the physical
NeoPixel "still deferred (no LED-driving code exists in this repo yet)". A
light on the hardware is a stronger trust signal than a light in the UI the
camera feeds, so it's worth finishing.

## What's done

`dtparam=spi=on` is now in `/boot/firmware/config.txt` — SPI was off, and the
ReSpeaker's RGB LEDs are APA102 devices driven over SPI0, so nothing could
have worked before. `/dev/spidev0.0` and `/dev/spidev0.1` now exist.

Backup before the change: `/boot/firmware/config.txt.bak-pre-spi-2026-08-05`.
The Pi rebooted cleanly with it — all services active, `goodix-touch-rebind`
oneshot reported `success`, touch intact.

`scripts/led_probe.py` writes red → green → blue → off to 3 APA102 LEDs on
SPI0. It runs without error on the device, which proves the bus and the write
path. It does **not** prove an LED lit.

## What needs a person

Run it while looking at the HAT:

```bash
ssh lumi@192.168.0.45 'cd /home/lumi/lumi && .venv/bin/python /tmp/led_probe.py'
# (scp scripts/led_probe.py to /tmp first)
```

Three LEDs should cycle red, green, blue, then go dark, ~1.5s each.

**If they light:** wire a driver that turns them red whenever the vision
worker is capturing, mirroring `device_samplers.py`'s `cameraActive` logic so
the on-screen icon and the physical light can never disagree. The natural
owner is a small `hardware/leds.py` alongside `hardware/button.py`, called
from the vision worker's capture session start/stop.

**If they don't:** this HAT is the **v2.0** (TLV320AIC3104 codec — see
`dtoverlay=respeaker-2mic-v2_0`, whose decompiled overlay declares only the
codec, I2S and a fixed clock, with no LED node). The v1.0 board with the
WM8960 is the one documented as having 3 APA102s; the v2.0 may simply have
dropped them. In that case either revert the SPI line or leave it (harmless),
and either add a discrete LED on a spare GPIO or keep the on-screen indicator
as V1's privacy signal and move the NeoPixel to V2 alongside the physical
shutter.

Do not write the driver before someone confirms which of those it is — code
that drives nothing looks like code that works.
