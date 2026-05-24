# Lumi device display — React + Vite

The screen that runs on the Pi 5's Waveshare SPI display (V1 hardware)
and shows in your browser at `http://localhost:8080/device-display`
(V1 laptop).

## Why React, not pygame?

The pygame renderers couldn't match the Figma spec at the visual
fidelity Lumi's "warm premium desk companion" brand needs, and the Pi 5
has 16 GB of RAM — plenty for a Chromium kiosk. The face renderers in
`src/lumi/ui/face/*.py` are kept for now as test fixtures + an offline
preview path, but the **device display** is this React app.

## Run

Dev (hot reload):
```
cd src/lumi/ui/device_display
npm install
npm run dev          # http://localhost:5173 — talks to FastAPI on :8080
```

Production build (FastAPI then serves it at `/device-display`):
```
npm run build
```

The build output lands at `../web/static/device-display/`. FastAPI maps
it via `src/lumi/ui/web/routes/device_display.py`.

## State flow

Backend → frontend goes through `/device-display/events` (Server-Sent
Events). Phase A is poll-based (one snapshot per second). Phase B will
swap to push-on-StateMachine-transition.

The hook is `src/state.ts:useDeviceState()` — it reconnects on its own
and falls back to a local demo cycle when the backend isn't reachable
(makes the dev experience nice).

## Sprite packs

`SpriteSceneFace` fetches frames at
`/device-display/sprite/<pack>/frame_NNN.png` and `manifest.json`. The
backend resolves packs the same way the pygame loader did:
`data_dir/sprites/<pack>/` (user-uploaded — wins) → bundled
`src/lumi/ui/face/assets/sprites/<bundled-dir>/`.

The `/settings/sprites` upload UI we shipped earlier writes into the
user dir — so uploading a pack via the dashboard immediately reflects
in the device display.

## Pi 5 deployment (Phase 5)

A systemd unit autostarts Chromium in kiosk mode pointing at
`http://localhost:8080/device-display`. Chromium handles the actual
SPI-display rendering via the X server bound to that framebuffer.
