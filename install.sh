#!/usr/bin/env bash
# claude-2x-statusline — interactive installer
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INSTALL_DIR="$HOME/.claude/cc-2x-statusline"
SETTINGS="$HOME/.claude/settings.json"
CONFIG="$HOME/.claude/statusline-config.json"

echo ""
echo "  ╭──────────────────────────────────────────╮"
echo "  │     claude-2x-statusline installer       │"
echo "  │     github.com/Nadav-Fux                 │"
echo "  ╰──────────────────────────────────────────╯"
echo ""

# ── Step 1: Choose tier ──
echo "  Choose your tier:"
echo ""
echo "    1) Minimal   — time + 2x promo + git"
echo "       22:44 ▸ ⚡ 2x  5h left ▸ main ~3"
echo ""
echo "    2) Standard  — + model + context + cost + duration"
echo "       22:44 ▸ ⚡ 2x  5h left ▸ Opus 4.6 ▸ 40% ▸ \$0.42 ▸ 23m ▸ main ~3"
echo ""
echo "    3) Full      — + rate limits + timeline dashboard"
echo "       22:44 ▸ ⚡ 2x  5h left ▸ Opus 4.6 ▸ ▰▰▰▰▱▱▱▱▱▱ 40% ▸ main ~3"
echo "       │ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━●━━━━━━━━━━━━━━━━━━ │"
echo "       │ ▸ current ▰▰▱▱▱▱▱▱▱▱ 15% · weekly ▰▰▰▱▱▱▱▱▱▱ 31% ❄ │"
echo ""

read -rp "  Pick a tier [1/2/3] (default: 2): " tier_choice
case "$tier_choice" in
    1) TIER="minimal"; MODE="minimal" ;;
    3) TIER="full"; MODE="full" ;;
    *) TIER="standard"; MODE="minimal" ;;
esac

echo ""
echo "  ✓ Selected: $TIER"
echo ""

# ── Step 2: Copy files ──
echo "  Installing files..."
mkdir -p "$INSTALL_DIR/engines" "$INSTALL_DIR/commands" "$INSTALL_DIR/skills" "$INSTALL_DIR/.claude-plugin"
cp "$SCRIPT_DIR/statusline.sh" "$INSTALL_DIR/"
cp "$SCRIPT_DIR/statusline.ps1" "$INSTALL_DIR/" 2>/dev/null || true
cp "$SCRIPT_DIR/engines/"* "$INSTALL_DIR/engines/"
cp "$SCRIPT_DIR/plugin.json" "$INSTALL_DIR/"
cp "$SCRIPT_DIR/.claude-plugin/plugin.json" "$INSTALL_DIR/.claude-plugin/"
cp -r "$SCRIPT_DIR/commands/"* "$INSTALL_DIR/commands/" 2>/dev/null || true
cp -r "$SCRIPT_DIR/skills/"* "$INSTALL_DIR/skills/" 2>/dev/null || true
chmod +x "$INSTALL_DIR/statusline.sh"
echo "  ✓ Copied to $INSTALL_DIR"

# ── Step 3: Write config ──
cat > "$CONFIG" << CONF
{
  "tier": "$TIER",
  "mode": "$MODE",
  "promo_start": 20260313,
  "promo_end": 20260327
}
CONF
echo "  ✓ Config saved to $CONFIG"

# ── Step 4: Update settings.json ──
PY=$(command -v python3 2>/dev/null || command -v python 2>/dev/null)
STATUSLINE_CMD="bash $INSTALL_DIR/statusline.sh"

if [ -f "$SETTINGS" ] && [ -n "$PY" ]; then
    "$PY" -c "
import json, sys
with open(sys.argv[1]) as f:
    s = json.load(f)
s['statusLine'] = {'type': 'command', 'command': sys.argv[2]}
with open(sys.argv[1], 'w') as f:
    json.dump(s, f, indent=2)
" "$SETTINGS" "$STATUSLINE_CMD"
    echo "  ✓ Updated settings.json"
elif [ -f "$SETTINGS" ]; then
    echo "  ⚠ Could not auto-update settings.json (no python)"
    echo "    Add manually:"
    echo "    \"statusLine\": { \"type\": \"command\", \"command\": \"$STATUSLINE_CMD\" }"
else
    mkdir -p "$(dirname "$SETTINGS")"
    echo "{ \"statusLine\": { \"type\": \"command\", \"command\": \"$STATUSLINE_CMD\" } }" > "$SETTINGS"
    echo "  ✓ Created settings.json"
fi

# ── Step 5: Register as plugin (enables /minimal, /standard, /full commands) ──
PLUGINS_JSON="$HOME/.claude/plugins/installed_plugins.json"
if [ -n "$PY" ]; then
    "$PY" -c "
import json, os, sys
from datetime import datetime
path = sys.argv[1]
install_dir = sys.argv[2]
settings_path = sys.argv[3]
if not os.path.exists(path):
    data = {'version': 2, 'plugins': {}}
else:
    with open(path) as f:
        data = json.load(f)
data['plugins']['claude-2x-statusline@local'] = [{'scope':'user','installPath':install_dir,'version':'2.0.0','installedAt':datetime.utcnow().isoformat()+'Z','lastUpdated':datetime.utcnow().isoformat()+'Z'}]
os.makedirs(os.path.dirname(path), exist_ok=True)
with open(path,'w') as f:
    json.dump(data, f, indent=2)
with open(settings_path) as f:
    s = json.load(f)
s.setdefault('enabledPlugins',{})['claude-2x-statusline@local'] = True
with open(settings_path,'w') as f:
    json.dump(s, f, indent=2)
" "$PLUGINS_JSON" "$INSTALL_DIR" "$SETTINGS"
    echo "  ✓ Plugin registered (/minimal /standard /full enabled)"
else
    echo "  ⚠ No python — slash commands unavailable"
    echo "    Register manually after installing python"
fi

# ── Done ──
echo ""
echo "  ╭──────────────────────────────────────────╮"
echo "  │  ✓ Installed! Restart Claude Code.       │"
echo "  │                                          │"
echo "  │  To change tier:                         │"
echo "  │    /statusline-tier minimal              │"
echo "  │                                          │"
echo "  │  Or re-run: bash install.sh              │"
echo "  ╰──────────────────────────────────────────╯"
echo ""
