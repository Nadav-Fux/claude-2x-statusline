#!/usr/bin/env bash
# Install claude-2x-statusline
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DEST="$HOME/.claude/bin/statusline.sh"

mkdir -p "$(dirname "$DEST")"
cp "$SCRIPT_DIR/statusline.sh" "$DEST"
chmod +x "$DEST"

# Add to Claude Code settings
SETTINGS="$HOME/.claude/settings.json"
if [ -f "$SETTINGS" ]; then
    if command -v python3 &>/dev/null; then
        python3 -c "
import json, sys
with open('$SETTINGS') as f:
    s = json.load(f)
s['statusLine'] = {'type': 'command', 'command': 'bash ~/.claude/bin/statusline.sh'}
with open('$SETTINGS', 'w') as f:
    json.dump(s, f, indent=2)
print('Updated settings.json')
"
    else
        echo "Add this to $SETTINGS manually:"
        echo '  "statusLine": { "type": "command", "command": "bash ~/.claude/bin/statusline.sh" }'
    fi
else
    mkdir -p "$(dirname "$SETTINGS")"
    echo '{ "statusLine": { "type": "command", "command": "bash ~/.claude/bin/statusline.sh" } }' > "$SETTINGS"
    echo "Created settings.json"
fi

echo "Installed! Restart Claude Code to see the status line."
