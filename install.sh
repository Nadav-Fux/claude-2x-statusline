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
echo "    1) Minimal   — peak status + model + git + rate limits"
echo "       OFF-PEAK ▸ Opus 4.6 ▸ CTX 40% ▸ main saved ▸ 15% 5H"
echo ""
echo "    2) Standard  — + cost + full context"
echo "       OFF-PEAK ▸ Opus 4.6 ▸ 400K/1.0M 40% ▸ main saved ▸ \$0.42 ▸ ▰▰▱▱▱▱▱▱▱▱ 15%"
echo ""
echo "    3) Full      — + multiline timeline + rate limit dashboard (recommended)"
echo "       OFF-PEAK ▸ Opus 4.6 ▸ 400K/1.0M 40% ▸ main saved ▸ \$0.42"
echo "       │ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━●━━━━━━━━━━━━━━━━━━ │"
echo "       │ ▸ 5h ▰▰▱▱▱▱▱▱▱▱  15% · weekly ▰▰▰▱▱▱▱▱▱▱  31% │"
echo ""

read -rp "  Pick a tier [1/2/3] (default: 3): " tier_choice
case "$tier_choice" in
    1) TIER="minimal"; MODE="minimal" ;;
    2) TIER="standard"; MODE="minimal" ;;
    *) TIER="full"; MODE="full" ;;
esac

echo ""
echo "  ✓ Selected: $TIER"
echo ""

# ── Step 2: Copy files ──
echo "  Installing files..."
mkdir -p "$INSTALL_DIR/engines" "$INSTALL_DIR/commands" "$INSTALL_DIR/skills" \
         "$INSTALL_DIR/.claude-plugin" "$INSTALL_DIR/lib" "$INSTALL_DIR/doctor"
cp "$SCRIPT_DIR/statusline.sh" "$INSTALL_DIR/"
cp "$SCRIPT_DIR/statusline.ps1" "$INSTALL_DIR/" 2>/dev/null || true
cp "$SCRIPT_DIR/engines/"* "$INSTALL_DIR/engines/"
cp "$SCRIPT_DIR/lib/"* "$INSTALL_DIR/lib/"
cp "$SCRIPT_DIR/doctor/"* "$INSTALL_DIR/doctor/"
cp "$SCRIPT_DIR/plugin.json" "$INSTALL_DIR/"
cp "$SCRIPT_DIR/.claude-plugin/plugin.json" "$INSTALL_DIR/.claude-plugin/" 2>/dev/null || true
cp -r "$SCRIPT_DIR/commands/"* "$INSTALL_DIR/commands/" 2>/dev/null || true
cp -r "$SCRIPT_DIR/skills/"* "$INSTALL_DIR/skills/" 2>/dev/null || true
chmod +x "$INSTALL_DIR/statusline.sh" "$INSTALL_DIR/doctor/doctor.sh" "$INSTALL_DIR/doctor/fixes.sh" 2>/dev/null || true
echo "  ✓ Copied to $INSTALL_DIR"

# ── Step 3: Write config ──
cat > "$CONFIG" << CONF
{
  "tier": "$TIER",
  "mode": "$MODE",
  "schedule_url": "https://raw.githubusercontent.com/Nadav-Fux/claude-2x-statusline/main/schedule.json",
  "schedule_cache_hours": 6
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

# ── Step 5: Install slash commands ──
mkdir -p "$HOME/.claude/commands"
cp "$SCRIPT_DIR/commands/"*.md "$HOME/.claude/commands/" 2>/dev/null && \
    echo "  ✓ Slash commands installed (/statusline-*, /explain)" || \
    echo "  ⚠ Could not install slash commands"

# ── Step 6: Fetch initial schedule ──
echo "  Fetching peak hours schedule..."
SCHEDULE_URL="https://raw.githubusercontent.com/Nadav-Fux/claude-2x-statusline/main/schedule.json"
SCHEDULE_CACHE="$HOME/.claude/statusline-schedule.json"
if command -v curl >/dev/null 2>&1; then
    curl -s --max-time 5 "$SCHEDULE_URL" -o "$SCHEDULE_CACHE" 2>/dev/null && \
        echo "  ✓ Schedule downloaded (auto-updates every 6 hours)" || \
        echo "  ⚠ Could not fetch schedule (will use defaults)"
elif command -v wget >/dev/null 2>&1; then
    wget -q --timeout=5 "$SCHEDULE_URL" -O "$SCHEDULE_CACHE" 2>/dev/null && \
        echo "  ✓ Schedule downloaded (auto-updates every 6 hours)" || \
        echo "  ⚠ Could not fetch schedule (will use defaults)"
else
    echo "  ⚠ No curl/wget — schedule will be fetched on first run"
fi

# ── Step 7: Editor extension (VS Code / Cursor / Windsurf / Antigravity) ──
EDITORS_FOUND=""
for editor_cmd in code cursor windsurf agy; do
    if command -v "$editor_cmd" >/dev/null 2>&1; then
        EDITORS_FOUND="$EDITORS_FOUND $editor_cmd"
    fi
done

if [ -n "$EDITORS_FOUND" ] && command -v npm >/dev/null 2>&1; then
    echo ""
    echo "  Detected editors:$EDITORS_FOUND"
    echo "  Building statusline extension..."
    VSCODE_DIR="$INSTALL_DIR/vscode"
    mkdir -p "$VSCODE_DIR"
    cp "$SCRIPT_DIR/vscode/extension.ts" "$VSCODE_DIR/"
    cp "$SCRIPT_DIR/vscode/package.json" "$VSCODE_DIR/"
    cp "$SCRIPT_DIR/vscode/package-lock.json" "$VSCODE_DIR/" 2>/dev/null || true
    cp "$SCRIPT_DIR/vscode/tsconfig.json" "$VSCODE_DIR/"
    cp "$SCRIPT_DIR/vscode/icon.png" "$VSCODE_DIR/"
    cp "$SCRIPT_DIR/vscode/LICENSE" "$VSCODE_DIR/"

    VSIX_BUILT=false
    (cd "$VSCODE_DIR" && npm install --silent 2>/dev/null && npm run compile --silent 2>/dev/null && \
        npx @vscode/vsce package --allow-missing-repository --out claude-statusline.vsix 2>/dev/null) && VSIX_BUILT=true

    if [ "$VSIX_BUILT" = true ]; then
        for editor_cmd in $EDITORS_FOUND; do
            case "$editor_cmd" in
                code)       name="VS Code" ;;
                cursor)     name="Cursor" ;;
                windsurf)   name="Windsurf" ;;
                agy)        name="Antigravity" ;;
                *)          name="$editor_cmd" ;;
            esac
            if "$editor_cmd" --install-extension "$VSCODE_DIR/claude-statusline.vsix" --force 2>/dev/null; then
                echo "  ✓ Installed in $name!"
            else
                echo "  ⚠ Could not install in $name (install manually via VSIX)."
            fi
        done
    else
        echo "  ⚠ Extension build failed (optional). Install manually from vscode/ folder."
    fi
else
    echo ""
    echo "  No supported editors detected (VS Code, Cursor, Windsurf, Antigravity)."
    echo "  To install later: build from the vscode/ folder."
fi

# ── Done ──
echo ""
echo "  ╭──────────────────────────────────────────╮"
echo "  │  ✓ Installed! Restart Claude Code.       │"
echo "  │                                          │"
echo "  │  Peak hours schedule updates             │"
echo "  │  automatically from GitHub.              │"
echo "  │                                          │"
echo "  │  To change tier:                         │"
echo "  │    /statusline-minimal                   │"
echo "  │    /statusline-standard                  │"
echo "  │    /statusline-full                      │"
echo "  │                                          │"
echo "  │  VS Code: extension auto-installed       │"
echo "  │  if VS Code + npm were detected.         │"
echo "  │                                          │"
echo "  │  Or re-run: bash install.sh              │"
echo "  ╰──────────────────────────────────────────╯"
echo ""

# ── Telemetry: anonymous install ping ──
_uid=$(echo -n "$(hostname):$(whoami)" | sha256sum 2>/dev/null | cut -c1-16)
if [ -n "$_uid" ]; then
    curl -s -o /dev/null --max-time 3 -X POST -H 'Content-Type: application/json' \
        -d "{\"id\":\"$_uid\",\"v\":\"2.1\",\"engine\":\"installer\",\"tier\":\"$TIER\",\"os\":\"$(uname -s | tr A-Z a-z)\",\"event\":\"install\"}" \
        "https://statusline-telemetry.nadavf.workers.dev/ping" &
fi
