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
         "$INSTALL_DIR/.claude-plugin" "$INSTALL_DIR/lib" "$INSTALL_DIR/doctor" \
         "$INSTALL_DIR/hooks" "$INSTALL_DIR/narrator"
cp "$SCRIPT_DIR/statusline.sh" "$INSTALL_DIR/"
cp "$SCRIPT_DIR/statusline.ps1" "$INSTALL_DIR/" 2>/dev/null || true
cp "$SCRIPT_DIR/engines/"* "$INSTALL_DIR/engines/"
cp "$SCRIPT_DIR/lib/"* "$INSTALL_DIR/lib/"
cp "$SCRIPT_DIR/doctor/"* "$INSTALL_DIR/doctor/"
cp "$SCRIPT_DIR/plugin.json" "$INSTALL_DIR/"
cp "$SCRIPT_DIR/.claude-plugin/plugin.json" "$INSTALL_DIR/.claude-plugin/" 2>/dev/null || true
cp -r "$SCRIPT_DIR/commands/"* "$INSTALL_DIR/commands/" 2>/dev/null || true
cp -r "$SCRIPT_DIR/skills/"* "$INSTALL_DIR/skills/" 2>/dev/null || true
cp -r "$SCRIPT_DIR/hooks/"* "$INSTALL_DIR/hooks/" 2>/dev/null || true
cp -r "$SCRIPT_DIR/narrator/"* "$INSTALL_DIR/narrator/" 2>/dev/null || true
chmod +x "$INSTALL_DIR/statusline.sh" "$INSTALL_DIR/doctor/doctor.sh" "$INSTALL_DIR/doctor/fixes.sh" 2>/dev/null || true
chmod +x "$INSTALL_DIR/hooks/narrator-session-start.sh" "$INSTALL_DIR/hooks/narrator-prompt-submit.sh" 2>/dev/null || true
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
# Use the shared resolver so we reject Windows App-Store stubs and pick up
# portable installs (~/tools/python-*, AppData\Local\Programs\Python, etc.).
# shellcheck source=lib/resolve-runtime.sh
. "$SCRIPT_DIR/lib/resolve-runtime.sh"
PY=$(resolve_runtime python 2>/dev/null || true)
NODE=$(resolve_runtime node 2>/dev/null || true)
STATUSLINE_CMD="bash $INSTALL_DIR/statusline.sh"

# Advisory: which runtime will actually drive the statusline?
if [ -n "$PY" ]; then
    echo "  ✓ Runtime: Python at $PY (full dashboard, narrator enabled)"
elif [ -n "$NODE" ]; then
    echo "  ⚠ Runtime: Node.js only ($NODE) — statusline works, narrator disabled"
    echo "    (Narrator requires Python 3.9+. Install from python.org for the full experience.)"
else
    echo "  ⚠ Runtime: no Python or Node found — bash-only minimal statusline"
    echo "    Install Python 3 (python.org) or Node.js for full features + narrator."
fi

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

# ── Step 4b: Wire narrator hooks into settings.json ──
HOOK_SS="$INSTALL_DIR/hooks/narrator-session-start.sh"
HOOK_PS="$INSTALL_DIR/hooks/narrator-prompt-submit.sh"

if [ -n "$PY" ]; then
    _wire_result=$("$PY" - "$SETTINGS" "$HOOK_SS" "$HOOK_PS" << 'PYWIRE'
import json, os, sys, tempfile

settings_path = sys.argv[1]
hook_ss       = sys.argv[2]
hook_ps       = sys.argv[3]

# Load or create settings
if os.path.exists(settings_path):
    with open(settings_path, encoding="utf-8") as f:
        s = json.load(f)
else:
    s = {}

hooks = s.setdefault("hooks", {})

def _entry(cmd):
    return {"type": "command", "command": cmd}

def _ensure_hook(hooks_dict, event_key, cmd):
    """Append cmd to hooks[event_key] list if not already present. Idempotent."""
    entries = hooks_dict.setdefault(event_key, [])
    # Normalise: accept plain strings or {"type":"command","command":"..."} objects
    existing_cmds = set()
    for e in entries:
        if isinstance(e, dict):
            existing_cmds.add(e.get("command", ""))
        elif isinstance(e, str):
            existing_cmds.add(e)
    if cmd not in existing_cmds:
        entries.append(_entry(cmd))
        return True
    return False

added_ss = _ensure_hook(hooks, "SessionStart",      hook_ss)
added_ps = _ensure_hook(hooks, "UserPromptSubmit",  hook_ps)

# Atomic write: write to tmp then replace
dirn = os.path.dirname(settings_path) or "."
fd, tmp_path = tempfile.mkstemp(dir=dirn, suffix=".tmp")
try:
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(s, f, indent=2)
        f.write("\n")
    os.replace(tmp_path, settings_path)
except Exception:
    try:
        os.unlink(tmp_path)
    except OSError:
        pass
    raise

print("wired" if (added_ss or added_ps) else "already")
PYWIRE
    )
    if [ "$_wire_result" = "already" ]; then
        echo "  ↻ Narrator hooks already wired in settings.json"
    else
        echo "  ✓ Narrator hooks wired in settings.json"
    fi
else
    echo "  ⚠ Skipping narrator hooks — no Python found."
    echo "    Narrator requires Python 3.9+. Statusline still works via Node/bash."
fi
if [ -n "$PY" ]; then
    echo "  ℹ Narrator: rules-mode ON by default. Set ANTHROPIC_API_KEY + STATUSLINE_NARRATOR_HAIKU=1 for the Haiku layer."
fi

# ── Step 5: Install slash commands ──
mkdir -p "$HOME/.claude/commands"
cp "$SCRIPT_DIR/commands/"*.md "$HOME/.claude/commands/" 2>/dev/null && \
    echo "  ✓ Slash commands installed (/statusline-*, /explain, /narrate, /narrator-lang)" || \
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
    _tele_payload="{\"id\":\"$_uid\",\"v\":\"2.1\",\"engine\":\"installer\",\"tier\":\"$TIER\",\"os\":\"$(uname -s | tr A-Z a-z)\",\"event\":\"install\"}"
    _tele_url="https://statusline-telemetry.nadavf.workers.dev/ping"

    if command -v curl >/dev/null 2>&1; then
        curl -sS --max-time 3 -X POST -H "Content-Type: application/json" \
          -d "$_tele_payload" "$_tele_url" >/dev/null 2>&1 &
    elif command -v wget >/dev/null 2>&1; then
        wget -q --timeout=3 --header="Content-Type: application/json" \
          --post-data="$_tele_payload" "$_tele_url" -O /dev/null 2>/dev/null &
    elif [ -n "${PY:-}" ] && [ -x "$PY" ]; then
        "$PY" -c "
import urllib.request, json
try:
    req = urllib.request.Request('$_tele_url', data=b'''$_tele_payload''', method='POST',
        headers={'Content-Type': 'application/json'})
    urllib.request.urlopen(req, timeout=3).read()
except Exception: pass
" >/dev/null 2>&1 &
    fi
fi
