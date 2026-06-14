# Installer pipeline

## Purpose

Cross-platform setup that detects the runtime, asks for tier preference, writes config, wires hooks into `settings.json`, installs slash commands, and fetches the initial schedule. Separate implementations for bash (macOS/Linux) and PowerShell (Windows).

## Install flow (install.sh)

The 611-line `install.sh` does:

1. **Parse args** — `--tier`, `--update`, `--quiet` flags
2. **Detect runtime** — Source `lib/resolve-runtime.sh`, check Python 3.9+ vs older Python vs Node vs Bash
3. **Copy files** — Clone or copy repo to `~/.claude/cc-2x-statusline/`
4. **Ask tier** — Interactive prompt (or use `--tier` flag)
5. **Write config** — `~/.claude/statusline-config.json` with chosen tier, mode, schedule URL
6. **Wire settings.json** — Add `statusLine` stanza via `lib/wire-json.sh` (atomic)
7. **Wire hooks** — Add narrator hooks to `settings.json` hooks section
8. **Install commands** — Copy command `.md` files or register plugin
9. **Fetch schedule** — Download `schedule.json` to `~/.claude/statusline-schedule.json`
10. **Install VS Code extension** — Detect supported editors, install extension
11. **Send telemetry** — Install ping with engine, tier, OS
12. **Print summary** — Runtime selected, tier chosen, restart reminder

## Install flow (install.ps1)

The PowerShell installer (`install.ps1`, 535 lines) mirrors the bash flow. It handles Windows-specific concerns:

- Finds Python via registry and common install paths
- Rejects Microsoft Store stubs
- Uses `lib/Wire-Json.ps1` for settings.json manipulation
- Detects VS Code, Cursor, Windsurf, Antigravity via `--list-extensions`

## Update flow

`update.sh` (and `update.ps1`) perform in-place updates:

1. `cd` to install directory
2. `git pull origin main`
3. Re-run installer in `--update --quiet` mode
4. Report version change

The `/statusline-update` command invokes this flow.

## Uninstall flow

`uninstall.sh` removes all traces:

1. Remove `~/.claude/cc-2x-statusline/` directory
2. Remove `~/.claude/statusline-config.json`
3. Remove `~/.claude/statusline-schedule.json`
4. Remove slash commands from `~/.claude/commands/`
5. Remove `statusLine` key from `settings.json`
6. Remove `enabledPlugins` entry from `settings.json`
7. Remove narrator hooks from `settings.json`
8. Uninstall VS Code extension (loops over `code`, `cursor`, `windsurf`, `agy`)
9. Remove telemetry ID file

All `settings.json` modifications are atomic. The uninstall script was audited and all gaps were fixed (see `UNINSTALL-GAPS.md`).

## Settings.json wiring

The installer writes this stanza into `~/.claude/settings.json`:

```json
{
  "statusLine": {
    "type": "command",
    "command": "bash /path/to/cc-2x-statusline/statusline.sh"
  }
}
```

Hook wiring adds entries to the `hooks.SessionStart` and `hooks.UserPromptSubmit` arrays, using the `{type: "command", command: "..."}` wrapper format.

## Key source files

| File | Lines | Purpose |
|------|-------|---------|
| `install.sh` | 611 | Bash installer (macOS/Linux) |
| `install.ps1` | 535 | PowerShell installer (Windows) |
| `uninstall.sh` | ~100 | Uninstaller |
| `update.sh` | ~40 | Bash updater |
| `update.ps1` | ~50 | PowerShell updater |
| `lib/wire-json.sh` | 365 | JSON manipulation for bash |
| `lib/Wire-Json.ps1` | 213 | JSON manipulation for PowerShell |
| `bin.js` | 35 | npx wrapper that spawns platform-appropriate installer |

## Related pages

- [Runtime resolution](runtime-resolution.md) — How the installer detects interpreters
- [Doctor diagnostics](../features/doctor.md) — Verifies installer results
- [Hooks and commands](hooks-and-commands.md) — What the installer wires
- [Getting started](../overview/getting-started.md) — User-facing install instructions
