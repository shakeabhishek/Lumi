#!/bin/bash
# Lumi kiosk: rotate DSI to landscape, then Chromium fullscreen on the device-display.
export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}
# 270 = 90deg CCW, matches the console's fbcon=rotate:3. Flip to 90 if it comes up upside-down.
wlr-randr --output DSI-2 --transform 90 >/tmp/kiosk-randr.log 2>&1 || true
exec chromium \
  --kiosk --app=http://localhost/device-display/ \
  --ozone-platform=wayland --enable-features=UseOzonePlatform \
  --no-first-run --noerrdialogs --disable-infobars \
  --disable-session-crashed-bubble --disable-features=Translate \
  --check-for-update-interval=31536000 \
  --user-data-dir=/home/lumi/.config/lumi-kiosk
