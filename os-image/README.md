# Lumi OS image — systemd units

Files under `etc/systemd/system/` are the production service definitions
that get baked into the Lumi OS image during Phase 6's `pi-gen` build.
They're staged here so they can be reviewed and tested against the dev
laptop before the image build picks them up.

| Unit | Owns |
|---|---|
| `lumi-web.service` | FastAPI dashboard on :8080 — the runtime the React app talks to over SSE |
| `lumi-display.service` | Chromium kiosk → `http://127.0.0.1:8080/device-display/` (Pi 5, Wayland via `cage`) |

## Pi 5 host requirements for `lumi-display.service`

Pi OS Lite 64-bit has no desktop env, so we drive Chromium directly
under a one-window Wayland compositor. The image build needs to
`apt install`:

```
chromium                  # Chromium browser (Pi OS provides ARM64 build)
cage                      # Wayland kiosk compositor (~2 MB)
libwayland-client0
fonts-noto-color-emoji    # Emoji rendering for the kawaii bear face
```

And needs the `lumi` user (UID 1000) created in the image, with
`/var/lib/lumi/chromium` writable as its Chromium profile dir.

## Installation (dev / Pi)

```
sudo cp os-image/etc/systemd/system/lumi-web.service /etc/systemd/system/
sudo cp os-image/etc/systemd/system/lumi-display.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now lumi-web.service
sudo systemctl enable --now lumi-display.service
```

`lumi-display` declares `Requires=lumi-web.service`, so starting the
kiosk also brings the dashboard up. Stopping `lumi-web` will stop the
kiosk too (it's pointless without the React bundle being served).

The image build needs `lumi` as a system user with home
`/var/lib/lumi`, and Lumi installed at `/opt/lumi` with the entrypoint
on `/usr/local/bin/lumi`. The pi-gen recipe in `stage-lumi/` will
own creating those.

## Why a kiosk over a desktop session

Earlier draft of Phase 2 had us rendering Lumi's face with pygame
directly to the framebuffer. The pivot to React (2026-05-24) made
Chromium-in-kiosk the right move: we get a browser engine, hardware-
accelerated CSS animations, and the full React/Vite ecosystem on a
device that has 16 GB of RAM and was always going to ship Chromium
anyway. The trade-off (Chromium cold-start time) is fine — the kiosk
boots once and stays up for the device's life.
