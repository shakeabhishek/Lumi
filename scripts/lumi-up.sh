#!/usr/bin/env bash
# Lumi dev orchestrator — starts every background service Lumi needs so you can
# exercise the whole stack with one command.
#
#   ollama  →  local LLM inference (Qwen2.5 1.5B)
#   openclaw → skill gateway (Wikipedia, weather, unit converter, …)
#   web      → FastAPI dashboard at http://localhost:8080
#
# Usage:    bash scripts/lumi-up.sh [--no-openclaw] [--no-web] [--web-port 8080]
#           Ctrl-C cleanly stops everything it started.

set -euo pipefail

LUMI_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$LUMI_ROOT"

# ── flags ────────────────────────────────────────────────────────────────────
START_OPENCLAW=1
START_WEB=1
START_HOTKEY=0
WEB_PORT=8080
while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-openclaw) START_OPENCLAW=0; shift ;;
    --no-web)      START_WEB=0;      shift ;;
    --hotkey)      START_HOTKEY=1;   shift ;;
    --web-port)    WEB_PORT="$2";    shift 2 ;;
    -h|--help)
      sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "unknown flag: $1" >&2; exit 1 ;;
  esac
done

# ── ANSI helpers ─────────────────────────────────────────────────────────────
c_reset=$'\033[0m'
c_pink=$'\033[38;5;205m'
c_dim=$'\033[2m'
c_ok=$'\033[38;5;42m'
c_warn=$'\033[38;5;220m'
c_err=$'\033[38;5;203m'

say()   { printf "%s\n" "$1"; }
ok()    { printf "  %s✓%s %s\n" "$c_ok"   "$c_reset" "$1"; }
warn()  { printf "  %s!%s %s\n" "$c_warn" "$c_reset" "$1"; }
fail()  { printf "  %s✗%s %s\n" "$c_err"  "$c_reset" "$1"; }
step()  { printf "\n%s── %s ──%s\n" "$c_pink" "$1" "$c_reset"; }

# ── cleanup on exit ──────────────────────────────────────────────────────────
PIDS=()
cleanup() {
  echo
  step "Shutting down"
  if [[ $START_OPENCLAW -eq 1 ]] && [[ "${OPENCLAW_STARTED:-0}" -eq 1 ]]; then
    npx openclaw gateway stop >/dev/null 2>&1 && ok "openclaw gateway stopped" || warn "openclaw stop failed"
  fi
  for pid in "${PIDS[@]:-}"; do
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      wait "$pid" 2>/dev/null || true
      ok "pid $pid stopped"
    fi
  done
  printf "\n%sbye 💖%s\n" "$c_pink" "$c_reset"
}
trap cleanup EXIT INT TERM

# ── banner ───────────────────────────────────────────────────────────────────
cat <<BANNER

${c_pink}        ██  ██   ██   ██
       ████████ ████████
       ████████ ████████
       ████████████████
        ██████████████
         ████████████
           ████████
            ██████
             ████
              ██${c_reset}

      ${c_pink}lumi${c_reset} · ${c_dim}your ai companion${c_reset}

BANNER

# ── 1. ollama ────────────────────────────────────────────────────────────────
step "1/3  ollama (local LLM)"
if ! command -v ollama >/dev/null; then
  fail "ollama not found. install from https://ollama.com"
  exit 1
fi
if curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
  ok "already running on :11434"
else
  warn "ollama not running — starting it in the background"
  ollama serve >"$LUMI_ROOT/.ollama.log" 2>&1 &
  PIDS+=("$!")
  for _ in {1..30}; do
    if curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
      ok "started (pid $!)"
      break
    fi
    sleep 0.5
  done
  if ! curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
    fail "ollama did not come up in 15s; see .ollama.log"
    exit 1
  fi
fi
if ollama list 2>/dev/null | awk 'NR>1 {print $1}' | grep -q "^qwen2.5:7b"; then
  ok "model qwen2.5:7b present"
else
  warn "model qwen2.5:7b missing — pulling (~4.7GB)"
  ollama pull qwen2.5:7b
  ok "pulled"
fi

# ── 2. openclaw ──────────────────────────────────────────────────────────────
if [[ $START_OPENCLAW -eq 1 ]]; then
  step "2/3  openclaw (skill gateway)"
  # Export plugin API keys from the OS keychain into the gateway's environment.
  # The launchd-managed gateway inherits whatever's set here when we restart it.
  if command -v uv >/dev/null; then
    for key_name in openweathermap_api_key; do
      env_name=$(echo "$key_name" | tr '[:lower:]' '[:upper:]')
      value=$(uv run --extra dev --extra web --extra memory --extra secrets python \
        -c "from lumi.runtime import secrets; print(secrets.get_secret('$key_name'))" 2>/dev/null | tail -1)
      if [[ -n "$value" ]]; then
        export "$env_name=$value"
        ok "exported $env_name from keychain (${#value} chars)"
      fi
    done
  fi
  if [[ ! -d "$HOME/.openclaw" ]]; then
    warn "openclaw not set up. run:  bash openclaw-service/setup.sh"
    warn "skipping openclaw; continuing without skills"
    START_OPENCLAW=0
  else
    if npx openclaw gateway status 2>/dev/null | grep -q "running"; then
      ok "gateway already running"
    else
      warn "gateway not running — starting"
      if npx openclaw gateway start >"$LUMI_ROOT/.openclaw.log" 2>&1; then
        OPENCLAW_STARTED=1
        ok "gateway started (see .openclaw.log)"
      else
        fail "openclaw failed to start; see .openclaw.log"
        START_OPENCLAW=0
      fi
    fi
  fi
else
  step "2/3  openclaw  ${c_dim}(skipped)${c_reset}"
fi

# ── 3. send-to-Lumi hotkey daemon (optional) ────────────────────────────────
if [[ $START_HOTKEY -eq 1 ]]; then
  step "3a  send-to-Lumi hotkey"
  uv run --extra dev --extra web --extra host --extra memory lumi hotkey \
    >"$LUMI_ROOT/.hotkey.log" 2>&1 &
  PIDS+=("$!")
  ok "hotkey daemon started (pid $!, log .hotkey.log). press Cmd/Ctrl+Shift+L to send"
fi

# ── 3. web UI ────────────────────────────────────────────────────────────────
if [[ $START_WEB -eq 1 ]]; then
  step "3/3  web UI"
  # If anything is already on the port, refuse rather than collide
  if lsof -i ":$WEB_PORT" -sTCP:LISTEN -t >/dev/null 2>&1; then
    fail "port $WEB_PORT already in use"
    exit 1
  fi
  ok "starting at http://localhost:$WEB_PORT  (Ctrl-C to stop everything)"
  echo
  exec uv run --extra dev --extra web --extra memory lumi web --host 127.0.0.1 --port "$WEB_PORT"
fi

# If web is disabled, just hold open until the user hits Ctrl-C
step "ready"
ok "press Ctrl-C to stop"
wait
