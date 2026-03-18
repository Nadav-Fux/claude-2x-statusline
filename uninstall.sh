#!/usr/bin/env bash
# Uninstall claude-2x-statusline
set -e

rm -rf "$HOME/.claude/cc-2x-statusline"
rm -f "$HOME/.claude/bin/statusline.sh"
rm -f "$HOME/.claude/statusline-config.json"

SETTINGS="$HOME/.claude/settings.json"
PY=$(command -v python3 2>/dev/null || command -v python 2>/dev/null)
if [ -f "$SETTINGS" ] && [ -n "$PY" ]; then
    "$PY" -c "
import json, sys
with open(sys.argv[1]) as f:
    s = json.load(f)
s.pop('statusLine', None)
with open(sys.argv[1], 'w') as f:
    json.dump(s, f, indent=2)
print('Removed statusLine from settings.json')
" "$SETTINGS"
fi

echo "Uninstalled. Restart Claude Code."
