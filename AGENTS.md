# Agent instructions — editing Lumi and deploying to the Pi

Paste this into a fresh agent session working on Lumi so it knows how the
Mac↔Pi deployment loop works, without re-discovering it the hard way.

## Architecture: Mac = source of truth, Pi = deploy target (NOT git)

- **Source repo**: `/Users/shakeitabhishek/Documents/Projects/Lumi` on the Mac.
  This is the git repo (`origin` = `git@github.com:shakeabhishek/Lumi.git`,
  branch `main`). All edits happen here.
- **Pi copy**: `/home/lumi/lumi` on the Raspberry Pi. This is a **plain file
  copy**, not a git clone — there is no `.git` tracking on the Pi. Deploying
  means `rsync`-ing changed files over, then restarting the affected
  `systemd` service. The Pi never pulls from GitHub directly.
- **Never edit files directly on the Pi.** Always edit on the Mac, then sync
  down. Otherwise the Mac and Pi silently diverge.
- **System-level files** (systemd units, the kiosk launch script) live
  **outside** `/home/lumi/lumi` at OS paths like `/etc/systemd/system/` and
  `/home/lumi/kiosk.sh`. These are tracked in the repo under **`pi-config/`**
  (mirroring their deployed path — see `pi-config/README.md`). **Do not
  create or edit these ad-hoc directly on the Pi over SSH** — that's exactly
  how a real regression happened: `lumi-web.service`'s port was changed from
  8080→80 without noticing `kiosk.sh` (then untracked, invisible to any
  repo search) still pointed Chromium at the old port, breaking the kiosk.
  Edit the copy in `pi-config/` first, then deploy it, same as any other file.
  (`pi-config/` is distinct from `os-image/`, which is the aspirational
  hardened `pi-gen` recipe for the eventual shipping image — not what's
  currently running.)

## Connecting to the Pi

```
ssh lumi@192.168.0.45      # prefer the IP — lumi.local (mDNS) is flaky
ssh lumi@lumi.local        # fallback; sometimes drops mid-session
```
Passwordless key auth is already set up (Mac's `~/.ssh/id_ed25519` is in the
Pi's `authorized_keys`). If the Pi drops off the network, ping-sweep to find
it: `for i in $(seq 1 254); do ping -c1 -t1 192.168.0.$i >/dev/null 2>&1 & done; wait`
then `arp -a | grep -i 88:a2:9e` (the Pi's MAC prefix).

## The standard edit → deploy loop

1. Edit the file(s) on the Mac as normal.
2. `rsync -az <path> -e ssh lumi@192.168.0.45:/home/lumi/lumi/<same-path>`
   — sync **only the files you changed**, preserving the relative path under
   `/home/lumi/lumi/`.
3. Restart the **specific** service that owns that file (see table below) —
   syncing alone does nothing until the process restarts.
4. Verify: `systemctl is-active <service>`, `curl -s -o /dev/null -w '%{http_code}' http://localhost/`,
   or `journalctl -u <service> -n 20 --no-pager` for errors.

## Services on the Pi (all `systemd`, all enabled on boot)

| Service | Owns | Repo source | Restart after changing |
|---|---|---|---|
| `lumi-web` | `src/lumi/ui/web/**` (templates, static, routes), `src/lumi/runtime/**` | `src/lumi/...` + unit at `pi-config/etc/systemd/system/lumi-web.service` | Python/template/CSS edits under `ui/web` or `runtime` |
| `lumi-display` | The Chromium kiosk showing the face (`cage` + Chromium pointed at `/device-display/`) | `pi-config/home/lumi/kiosk.sh` + `pi-config/etc/systemd/system/lumi-display.service` | After rebuilding the React device-display app (see below), or editing `kiosk.sh` |
| `lumi-openclaw` | OpenClaw gateway (skills, `~/.openclaw/openclaw.json`) | `pi-config/etc/systemd/system/lumi-openclaw.service` | Skill/plugin config changes |
| `ollama` | The local LLM (`qwen2.5:1.5b`) | — | Rarely — only if the model or Ollama config changes |
| `log2ram` | SD-card write reduction (logs → tmpfs) | — | Never touch |
| `goodix-touch-rebind` | Oneshot boot-time fix for a touchscreen I2C race (see Gotchas) | `pi-config/usr/local/bin/goodix-touch-rebind.sh` + its unit | Never touch |

**`lumi-web` runs on port 80** (not 8080 — migrated for the clean
`http://lumi.local/` URL), via `AmbientCapabilities=CAP_NET_BIND_SERVICE`
in its unit file since it runs as user `lumi`, not root.
**`kiosk.sh`'s `--app=http://localhost/device-display/` and
`lumi-web.service`'s `--port` are a coupled pair — they must always agree.**

### General rule: coupled config

Before considering *any* change to a port, URL, hostname, or filesystem
path complete, **grep the whole repo (including `pi-config/`) for the old
value** — not just the file you think owns it. This exact class of bug
(change a port in one service, miss a hardcoded reference in another file)
already broke the kiosk once this session.

## Special cases

**Python dependency changes** (`pyproject.toml` / `uv.lock`):
```
rsync -az uv.lock pyproject.toml -e ssh lumi@192.168.0.45:/home/lumi/lumi/
ssh lumi@192.168.0.45 'cd /home/lumi/lumi && export PATH=$HOME/.local/bin:$PATH && \
  uv sync --extra memory --extra web --extra secrets --extra host'
```
Use exactly these four extras on the Pi. **Do not add `--extra voice`** —
it pulls in `torch`/`transformers` (~2 GB, not needed, and not what the
validated LLM setup uses). `--extra dev` is laptop-only (pytest/ruff/mypy).

**React device-display app** (`src/lumi/ui/device_display/src/**` — the
Lumi face UI): must be **built on the Mac** first, then the build output
synced — there's no Node toolchain expectation on the Pi for this step.
```
cd src/lumi/ui/device_display && npm run build   # outputs to ../web/static/device-display/
cd /Users/shakeitabhishek/Documents/Projects/Lumi
rsync -az --delete src/lumi/ui/web/static/device-display/ \
  -e ssh lumi@192.168.0.45:/home/lumi/lumi/src/lumi/ui/web/static/device-display/
ssh lumi@192.168.0.45 'sudo systemctl restart lumi-web && sudo systemctl restart lumi-display'
```
The `--delete` flag matters — Vite hashes filenames per build, so stale
old-hash assets need to be removed, not just added to.

**Boot config changes** (`/boot/firmware/config.txt`, `cmdline.txt`) — rare,
only for hardware bring-up (I2C/I2S/overlays/rotation). **Always back up
first**: `sudo cp /boot/firmware/config.txt /boot/firmware/config.txt.bak-<label>`.
A bad edit here can break boot or the display. Several `.bak-*` files
already exist on the Pi from past sessions — don't delete them, they're the
recovery path.

## Known gotchas (already solved — don't re-debug these)

- **chromadb + protobuf**: previously needed
  `PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python` as a workaround. **Fixed**
  (2026-07-02) by bumping the whole `opentelemetry-{api,sdk,proto,exporter-otlp-proto-grpc}`
  family to `1.43.0` together in `uv.lock` — do this as one atomic
  `uv lock --upgrade-package X --upgrade-package Y ...` for all four, not
  one at a time (chromadb's exporter dep exact-pins `opentelemetry-proto`
  to whatever `opentelemetry-exporter-otlp-proto-grpc` version is resolved).
  The env var is no longer set anywhere — don't re-add it.
- **MediaPipe vs chromadb**: MediaPipe needs `protobuf` 4.x; chromadb needs
  7.x. They **cannot share one venv**. The vision benchmark used an isolated
  venv (`/home/lumi/mpbench`, its own `uv venv --python 3.12` +
  `uv pip install mediapipe opencv-python-headless`). Production vision
  integration will need the vision worker in its own process/venv, talking
  to the main app over IPC/HTTP — not a shared import.
- **ReSpeaker HAT + Touch Display 2 coexistence**: needs the **SmartiPi
  Display Power Kit** (display powered over USB-C, frees the GPIO header
  for the HAT) **and** `force_eeprom_read=0` in `config.txt` (the HAT's ID
  EEPROM probe on GPIO0/1 shares that bus with the Goodix touch controller
  and clobbers it otherwise).
- **Touch controller boot race**: even with the fix above, the Goodix touch
  chip sometimes fails its kernel boot-time I2C probe (`-121`) because its
  power rail hasn't stabilized in the first ~3s of boot. Fixed by
  `goodix-touch-rebind.service` (`/usr/local/bin/goodix-touch-rebind.sh`),
  which retries the I2C driver bind for up to 20s after boot. Don't remove
  this service.
- **Touch registers taps, but no visible cursor movement is expected** —
  it's a touchscreen (absolute tap position), not a mouse (relative
  motion); tapping should register a click at that point, it won't show a
  cursor gliding across the screen. The kernel-level `mouse0` legacy handler
  on the Goodix device does NOT mean cage/Chromium visually warps a cursor
  to touch position — verify actual click-through into the app via
  Chromium's own input handling, not by looking for cursor movement.
- **`lumi.local` failing in Chrome but IP working**: Chrome auto-upgrades
  bare hostname navigation (no explicit port) to HTTPS first; `.local` has
  no TLS cert so it fails/hangs. Type `http://lumi.local/` explicitly, or
  disable "Use secure DNS" / enable "With your current service provider"
  in `chrome://settings/security`. This is a known issue affecting most
  self-hosted `.local` dashboards (Home Assistant, Pi-hole, etc.), not
  specific to Lumi.
- **SD-card wear**: `log2ram` is installed (logs → tmpfs) — the real fix.
  Do NOT disable `zram` swap thinking it helps SD wear — zram is
  RAM-backed compressed swap, not SD-backed; disabling it only removes a
  useful memory buffer for no benefit.

## Pushing to GitHub

Standing instruction: **push to GitHub periodically**, not just at the end
of a session. The repo has a repo-scoped SSH key override already set
(`git config core.sshCommand` → `~/.ssh/id_ed25519_ascend`, the key that
authenticates as `shakeabhishek` on GitHub) — pushes should just work
without further auth setup. Stage deliberately (`git add <specific files>`,
not blind `git add -A`) unless the user has explicitly said to sweep in
everything. Write commit messages that explain *why*, not just *what*.
