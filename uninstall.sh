#!/usr/bin/env bash
# Uninstall claude-2x-statusline
set -e

rm -f "$HOME/.claude/bin/statusline.sh"

SETTINGS="$HOME/.claude/settings.json"
if [ -f "$SETTINGS" ] && command -v python3 &>/dev/null; then
    python3 -c "
import json
with open('$SETTINGS') as f:
    s = json.load(f)
s.pop('statusLine', None)
with open('$SETTINGS', 'w') as f:
    json.dump(s, f, indent=2)
print('Removed statusLine from settings.json')
"
fi

echo "Uninstalled. Restart Claude Code."
