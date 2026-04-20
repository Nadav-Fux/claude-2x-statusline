#!/usr/bin/env bash
# Uninstall claude-2x-statusline — removes all installed files
set -e

echo "  Uninstalling claude-2x-statusline..."

# Remove plugin directory
rm -rf "$HOME/.claude/cc-2x-statusline"

# Remove config and cache files
rm -f "$HOME/.claude/statusline-config.json"
rm -f "$HOME/.claude/statusline-schedule.json"

# Remove ALL slash commands (11 files installed by install.sh)
rm -f "$HOME/.claude/commands/explain.md"
rm -f "$HOME/.claude/commands/narrate.md"
rm -f "$HOME/.claude/commands/narrator-lang.md"
rm -f "$HOME/.claude/commands/statusline-doctor.md"
rm -f "$HOME/.claude/commands/statusline-full.md"
rm -f "$HOME/.claude/commands/statusline-init.md"
rm -f "$HOME/.claude/commands/statusline-minimal.md"
rm -f "$HOME/.claude/commands/statusline-onboarding.md"
rm -f "$HOME/.claude/commands/statusline-standard.md"
rm -f "$HOME/.claude/commands/statusline-tier.md"
rm -f "$HOME/.claude/commands/statusline-update.md"

# Remove legacy path
rm -f "$HOME/.claude/bin/statusline.sh"

# Remove usage cache
rm -f "$HOME/.claude/statusline-usage-cache.json" 2>/dev/null
rm -f /tmp/claude/statusline-usage-cache.json 2>/dev/null

# Remove heartbeat and install markers
rm -f "$HOME/.claude/.statusline-heartbeat"
rm -f "$HOME/.claude/.statusline-install-done"
rm -f "$HOME/.claude/.statusline-telemetry-id"

# Clean settings.json: statusLine key, narrator hooks, enabledPlugins entry
SETTINGS="$HOME/.claude/settings.json"
PY=$(command -v python3 2>/dev/null || command -v python 2>/dev/null)
if [ -f "$SETTINGS" ] && [ -n "$PY" ]; then
    "$PY" -c "
import json, sys

path = sys.argv[1]
with open(path) as f:
    s = json.load(f)

changed = False

# 1. Remove statusLine key
if 'statusLine' in s:
    del s['statusLine']
    changed = True
    print('  Removed statusLine from settings.json')

# 2. Remove narrator hooks from hooks.* arrays
MARKER = 'cc-2x-statusline'
hooks = s.get('hooks', {})
for event_key in list(hooks.keys()):
    arr = hooks[event_key]
    if not isinstance(arr, list):
        continue
    filtered = []
    for entry in arr:
        if not isinstance(entry, dict):
            filtered.append(entry)
            continue
        # Check top-level command field
        cmd = entry.get('command', '')
        if isinstance(cmd, str) and MARKER in cmd:
            changed = True
            continue
        # Check nested hooks array
        inner = entry.get('hooks', [])
        if isinstance(inner, list):
            inner_filtered = [
                h for h in inner
                if not (isinstance(h, dict) and MARKER in h.get('command', ''))
            ]
            if len(inner_filtered) < len(inner):
                changed = True
            if not inner_filtered:
                # All hooks in this entry were ours — drop the whole entry
                continue
            entry['hooks'] = inner_filtered
        filtered.append(entry)
    if len(filtered) < len(arr):
        if filtered:
            hooks[event_key] = filtered
        else:
            del hooks[event_key]
if hooks != s.get('hooks', {}):
    if hooks:
        s['hooks'] = hooks
    else:
        s.pop('hooks', None)
if changed:
    print('  Removed narrator hooks from settings.json')

# 3. Remove enabledPlugins entry
ep = s.get('enabledPlugins', {})
if isinstance(ep, dict):
    keys_to_remove = [k for k in ep if k.startswith('claude-2x-statusline')]
    for k in keys_to_remove:
        del ep[k]
        changed = True
    if not ep:
        s.pop('enabledPlugins', None)
    if keys_to_remove:
        print('  Removed enabledPlugins entry from settings.json')

if changed:
    with open(path, 'w') as f:
        json.dump(s, f, indent=2)
        f.write('\n')
" "$SETTINGS"
fi

# Uninstall VS Code extension from known editors
for editor in code cursor windsurf agy; do
    if command -v "$editor" >/dev/null 2>&1; then
        "$editor" --uninstall-extension nadav-fux.claude-statusline 2>/dev/null || true
    fi
done

echo ""
echo "  Uninstalled. Restart Claude Code."
echo ""
