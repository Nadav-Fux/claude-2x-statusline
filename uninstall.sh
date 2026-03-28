#!/usr/bin/env bash
# Uninstall claude-2x-statusline — removes all installed files
set -e

echo "  Uninstalling claude-2x-statusline..."

# Remove plugin directory
rm -rf "$HOME/.claude/cc-2x-statusline"

# Remove config and cache files
rm -f "$HOME/.claude/statusline-config.json"
rm -f "$HOME/.claude/statusline-schedule.json"

# Remove slash commands
rm -f "$HOME/.claude/commands/statusline-minimal.md"
rm -f "$HOME/.claude/commands/statusline-standard.md"
rm -f "$HOME/.claude/commands/statusline-full.md"
rm -f "$HOME/.claude/commands/statusline-tier.md"

# Remove legacy path
rm -f "$HOME/.claude/bin/statusline.sh"

# Remove usage cache
rm -f /tmp/claude/statusline-usage-cache.json 2>/dev/null

# Remove statusLine from settings.json
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
print('  Removed statusLine from settings.json')
" "$SETTINGS"
fi

echo ""
echo "  Uninstalled. Restart Claude Code."
echo ""
