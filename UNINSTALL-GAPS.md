# Uninstall Gaps — claude-2x-statusline

> **Status: ALL GAPS FIXED** — see commit history for details.

Audit date: 2026-04-19  
Fixed: 2026-04-20  
Tested on: Windows 11, Claude Code, bash via Git Bash  
Uninstall script: `~/.claude/cc-2x-statusline/uninstall.sh`

---

## Gaps Found (all resolved)

| # | Gap | Fix |
|---|---|---|
| 1 | Only 4 of 11 slash commands removed | All 11 `.md` files now removed |
| 2 | `enabledPlugins` entry left behind | Python block now removes keys starting with `claude-2x-statusline` |
| 3 | Narrator hooks not cleaned from `settings.json` | Python block now strips entries containing `cc-2x-statusline` from `hooks.*` arrays (both flat and nested format) |
| 4 | No VS Code extension uninstall | Loops over `code`, `cursor`, `windsurf`, `agy` and calls `--uninstall-extension` |
| 5 | Install script wired hooks in wrong format | `install.sh` now uses `{hooks:[{type,command}]}` wrapper |

---

## Before-Snapshot (state immediately before running uninstall)

| Artifact | Path | State |
|---|---|---|
| Install directory | `~/.claude/cc-2x-statusline/` | Present |
| Config file | `~/.claude/statusline-config.json` | Present |
| Schedule cache | `~/.claude/statusline-schedule.json` | Present |
| Usage cache | `/tmp/claude/statusline-usage-cache.json` | Present |
| Legacy bin script | `~/.claude/bin/statusline.sh` | Present |
| Slash command | `~/.claude/commands/statusline-tier.md` | Present |
| Slash commands (minimal/standard/full) | `~/.claude/commands/statusline-{minimal,standard,full}.md` | **NOT present** — these only live inside the install dir (`cc-2x-statusline/commands/`) and are apparently not copied to `~/.claude/commands/` on install |
| `statusLine` key in settings.json | `~/.claude/settings.json` → `"statusLine"` | Present: `{"type":"command","command":"bash /c/Users/Nadav/.claude/cc-2x-statusline/statusline.sh"}` |
| Plugin registry entry | `~/.claude/settings.json` → `enabledPlugins["claude-2x-statusline@nadav-plugins"]` | Present: `true` |
| Narrator hooks in settings.json | `~/.claude/settings.json` → `hooks.*` | **None** — no hooks point to cc-2x-statusline |
| VS Code extension | `code --list-extensions \| grep -i statusline` | **Not installed** |

---

## Uninstall Run Output

```
  Uninstalling claude-2x-statusline...
  Removed statusLine from settings.json

  Uninstalled. Restart Claude Code.
```

---

## After-Snapshot (what remained after uninstall)

| Artifact | Expected | Result |
|---|---|---|
| `~/.claude/cc-2x-statusline/` | Removed | REMOVED |
| `~/.claude/statusline-config.json` | Removed | REMOVED |
| `~/.claude/statusline-schedule.json` | Removed | REMOVED |
| `/tmp/claude/statusline-usage-cache.json` | Removed | REMOVED |
| `~/.claude/bin/statusline.sh` | Removed | REMOVED |
| `~/.claude/commands/statusline-tier.md` | Removed | REMOVED |
| `settings.json` `statusLine` key | Removed | REMOVED |
| `settings.json` `enabledPlugins["claude-2x-statusline@nadav-plugins"]` | Should be removed | **LEFT BEHIND** — still `true` |

---

## What the Uninstall DID Clean

Everything it explicitly targets was successfully removed:

- `~/.claude/cc-2x-statusline/` (install directory, recursively)
- `~/.claude/statusline-config.json`
- `~/.claude/statusline-schedule.json`
- `~/.claude/commands/statusline-tier.md`
- `~/.claude/commands/statusline-minimal.md` (not present, no-op `rm -f`)
- `~/.claude/commands/statusline-standard.md` (not present, no-op `rm -f`)
- `~/.claude/commands/statusline-full.md` (not present, no-op `rm -f`)
- `~/.claude/bin/statusline.sh` (legacy path)
- `/tmp/claude/statusline-usage-cache.json`
- `settings.json` → `statusLine` key

---

## What It MISSED

### 1. `enabledPlugins["claude-2x-statusline@nadav-plugins"]` in settings.json

**File:** `~/.claude/settings.json`  
**Leftover value:**
```json
"enabledPlugins": {
  "claude-2x-statusline@nadav-plugins": true
}
```

The uninstall script's Python snippet only removes the `statusLine` key. It does not touch `enabledPlugins`. After uninstall, the plugin is still listed as enabled in the registry, which means:
- Claude Code's plugin manager still considers it "on"
- On restart, Claude Code may attempt to load or validate the plugin and silently fail or emit errors
- The orphaned entry persists across future sessions until manually removed

### 2. VS Code extension (situational — not installed here)

The script has no logic to detect or remove the `claude-statusline` VS Code extension. On systems where it is installed, running:
```bash
code --uninstall-extension <publisher>.claude-statusline
```
would be needed. The script does not attempt this at all.

### 3. `statusline-minimal.md`, `statusline-standard.md`, `statusline-full.md` not copied to commands/ on install

These three commands exist in `cc-2x-statusline/commands/` but were never symlinked or copied to `~/.claude/commands/` (only `statusline-tier.md` was installed there). The uninstall script tries to remove all three from `~/.claude/commands/`, but they were never there — so these `rm -f` calls are silent no-ops. This suggests either the install script has a bug (failing to deploy 3 of 4 commands), or the design changed and the uninstall script was not updated.

---

## Recommended Fixes for uninstall.sh

### Fix 1 — Remove the `enabledPlugins` entry (critical)

Replace the existing Python block with:

```bash
if [ -f "$SETTINGS" ] && [ -n "$PY" ]; then
    "$PY" -c "
import json, sys
with open(sys.argv[1]) as f:
    s = json.load(f)
s.pop('statusLine', None)
plugins = s.get('enabledPlugins', {})
plugins.pop('claude-2x-statusline@nadav-plugins', None)
if not plugins:
    s.pop('enabledPlugins', None)
with open(sys.argv[1], 'w') as f:
    json.dump(s, f, indent=2)
print('  Removed statusLine and plugin entry from settings.json')
" "$SETTINGS"
fi
```

### Fix 2 — Remove VS Code extension if installed

Add after the settings.json block:

```bash
# Remove VS Code extension if installed
if command -v code &>/dev/null; then
    if code --list-extensions 2>/dev/null | grep -qi "statusline"; then
        code --uninstall-extension "$(code --list-extensions 2>/dev/null | grep -i statusline | head -1)" 2>/dev/null && \
            echo "  Removed VS Code statusline extension"
    fi
fi
```

### Fix 3 — Audit install.sh to match commands being installed/removed

The install script should be verified to copy all four command files to `~/.claude/commands/`:
- `statusline-minimal.md`
- `statusline-standard.md`  
- `statusline-full.md`
- `statusline-tier.md`

Currently only `statusline-tier.md` is being installed to `~/.claude/commands/`. Either the install script should deploy all four, or the uninstall script should remove only the ones that are actually installed.

---

## Summary Table

| Gap | Severity | Fix |
|---|---|---|
| `enabledPlugins` entry left in settings.json | High — orphaned plugin registration, may cause errors on restart | Add `plugins.pop('claude-2x-statusline@nadav-plugins', None)` to the Python snippet |
| VS Code extension not uninstalled | Medium — but not installed in this environment | Add `code --uninstall-extension` block with install-check guard |
| Install/uninstall mismatch on 3 command files | Low — silent no-ops, no residue | Audit install.sh; align what gets deployed to `~/.claude/commands/` |
