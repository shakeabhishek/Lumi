# pi-config — the files actually deployed on the dev Pi right now

This mirrors real files on the Raspberry Pi (`/home/lumi/lumi`) during
hardware bring-up. It is **not** the same thing as `os-image/`, which is the
aspirational, hardened `pi-gen` recipe for the eventual shipping OS image
(dedicated `lumi` system user, `/opt/lumi`, `ProtectSystem=strict`, etc. —
none of that exists yet).

This directory exists because `kiosk.sh` and the `systemd` unit files were
originally created ad-hoc directly on the Pi over SSH, outside git entirely.
That caused a real regression: `lumi-web.service` was changed from port 8080
to port 80, but `kiosk.sh` (untracked, invisible to anyone editing the repo)
still pointed Chromium at the old port, breaking the kiosk with a "site can't
be reached" error. Tracking these files here — and treating them as part of
the normal edit → rsync → restart deploy loop (see `AGENTS.md`) — closes that
gap.

**When you change a port, URL, or path referenced by more than one of these
files, grep this whole directory for the old value before considering the
change done.** `lumi-web.service`'s `--port` and `kiosk.sh`'s
`--app=http://localhost/...` are the pair that broke; they must always
agree.

## Files → deployed path on the Pi

| Repo path | Deployed to |
|---|---|
| `etc/systemd/system/*.service` | `/etc/systemd/system/` |
| `usr/local/bin/goodix-touch-rebind.sh` | `/usr/local/bin/goodix-touch-rebind.sh` |
| `home/lumi/kiosk.sh` | `/home/lumi/kiosk.sh` |

Deploy a change to any of these the same way as everything else in
`AGENTS.md`: `rsync` the specific file to its target path, then
`sudo systemctl daemon-reload` (only needed for `.service` file edits) and
restart the affected service.
