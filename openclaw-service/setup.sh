#!/usr/bin/env bash
# Sets up OpenClaw for Lumi dev. Run once per machine.
# Usage: bash openclaw-service/setup.sh [--openweathermap-key YOUR_KEY]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LUMI_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SANDBOX_PATH="$LUMI_ROOT/sandbox"
OPENCLAW_DIR="$HOME/.openclaw"
SKILLS_DIR="$OPENCLAW_DIR/workspace/skills"

OPENWEATHERMAP_KEY=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --openweathermap-key) OPENWEATHERMAP_KEY="$2"; shift 2 ;;
    *) echo "Unknown flag: $1"; exit 1 ;;
  esac
done

# ── 1. Node.js version check ─────────────────────────────────────────────────
NODE_VERSION=$(node --version 2>/dev/null | sed 's/v//')
NODE_MAJOR=$(echo "$NODE_VERSION" | cut -d. -f1)
NODE_MINOR=$(echo "$NODE_VERSION" | cut -d. -f2)
if [[ "$NODE_MAJOR" -lt 22 ]] || { [[ "$NODE_MAJOR" -eq 22 ]] && [[ "$NODE_MINOR" -lt 14 ]]; }; then
  echo "ERROR: Node.js >=22.14.0 required. Found: v$NODE_VERSION"
  exit 1
fi
echo "✓ Node.js v$NODE_VERSION"

# ── 2. npm install ────────────────────────────────────────────────────────────
echo "Installing Node dependencies..."
cd "$LUMI_ROOT"
npm install
echo "✓ openclaw $(node -e "require('openclaw/package.json').version" 2>/dev/null || npx openclaw --version 2>/dev/null | head -1)"

# ── 3. Create ~/.openclaw if needed ──────────────────────────────────────────
mkdir -p "$OPENCLAW_DIR" "$SKILLS_DIR"

# ── 4. Deploy config ──────────────────────────────────────────────────────────
CONFIG_SRC="$SCRIPT_DIR/config/openclaw.json"
CONFIG_DEST="$OPENCLAW_DIR/openclaw.json"

if [[ -f "$CONFIG_DEST" ]]; then
  read -r -p "~/.openclaw/openclaw.json already exists. Overwrite? [y/N] " answer
  [[ "$(echo "$answer" | tr '[:upper:]' '[:lower:]')" == "y" ]] || { echo "Skipping config deploy."; }
fi

# Substitute placeholder values
DEPLOYED_CONFIG=$(cat "$CONFIG_SRC")
DEPLOYED_CONFIG="${DEPLOYED_CONFIG//__SANDBOX_PATH__/$SANDBOX_PATH}"

if [[ -n "$OPENWEATHERMAP_KEY" ]]; then
  DEPLOYED_CONFIG="${DEPLOYED_CONFIG//__OPENWEATHERMAP_API_KEY__/$OPENWEATHERMAP_KEY}"
else
  echo "NOTE: No --openweathermap-key provided. Weather skill will not work until you add"
  echo "      OPENWEATHERMAP_API_KEY to ~/.openclaw/openclaw.json manually."
fi

echo "$DEPLOYED_CONFIG" > "$CONFIG_DEST"
echo "✓ Config deployed to $CONFIG_DEST"

# ── 5. Install workspace skills ───────────────────────────────────────────────
echo "Installing skills..."
for skill_dir in "$SCRIPT_DIR/skills"/*/; do
  skill_name=$(basename "$skill_dir")
  dest="$SKILLS_DIR/$skill_name"

  if [[ -d "$dest" ]]; then
    rm -rf "$dest"
  fi

  # Substitute sandbox path placeholder in SKILL.md if present
  mkdir -p "$dest"
  SKILL_MD=$(cat "$skill_dir/SKILL.md")
  SKILL_MD="${SKILL_MD//__SANDBOX_PATH__/$SANDBOX_PATH}"
  echo "$SKILL_MD" > "$dest/SKILL.md"

  echo "  ✓ $skill_name → $dest"
done

# ── 6. Verify install ─────────────────────────────────────────────────────────
echo ""
echo "Verifying..."
npx openclaw --version
npx openclaw skills list 2>/dev/null || echo "(openclaw daemon not running — start with: npm run openclaw:start)"

echo ""
echo "Setup complete. Next steps:"
echo "  1. Start Ollama:   ollama serve"
echo "  2. Start OpenClaw: npm run openclaw:start   (installs + starts as a background service)"
echo "  3. Run test:       npm run viability-test"
