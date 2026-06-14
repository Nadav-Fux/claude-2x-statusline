# Getting started

## Prerequisites

- Claude Code (CLI or terminal)
- One of: Python 3.9+ (recommended, enables narrator), Node.js (any LTS), or Bash 4+
- Git for cloning the repository

The installer auto-detects the best available runtime. Python unlocks the full feature set including the narrator. Node.js provides full statusline parity without the narrator. Bash renders a minimal statusline only.

## Installation

### Option 1: Ask Claude

Paste into Claude Code:

```
Install the claude-2x-statusline plugin from github.com/Nadav-Fux/claude-2x-statusline
```

Claude clones the repo, runs the installer, asks which tier you want, and configures everything.

### Option 2: One-liner (macOS / Linux)

```bash
git clone https://github.com/Nadav-Fux/claude-2x-statusline.git ~/.claude/cc-2x-statusline && bash ~/.claude/cc-2x-statusline/install.sh
```

### Option 3: Windows (PowerShell)

```powershell
irm https://raw.githubusercontent.com/Nadav-Fux/claude-2x-statusline/main/install.ps1 | iex
```

The installer writes `~/.claude/statusline-config.json`, updates `~/.claude/settings.json` with the `statusLine` stanza, installs slash commands, and fetches the initial remote schedule. Restart Claude Code to activate.

## Running tests

```bash
# Python tests (narrator, scoring, peak hours, rolling state, memory, etc.)
pip install pytest tzdata
python -m pytest tests/ -v

# Node.js runtime test
node --test tests/node-runtime.test.mjs

# Worker test
node --test worker/worker.test.mjs
```

## Switching tiers

| Command | Effect |
|---------|--------|
| `/statusline-minimal` | 1-line minimal display |
| `/statusline-standard` | 2-line standard display |
| `/statusline-full` | 4-line full dashboard (recommended) |

## Configuration

Edit `~/.claude/statusline-config.json` to change tier, segments, schedule URL, or telemetry settings. See [configuration reference](../reference/configuration.md) for all options.

## Updating

Run `/statusline-update` inside Claude Code, or:

```bash
bash ~/.claude/cc-2x-statusline/update.sh
```

## Troubleshooting

Run `/statusline-doctor` to diagnose common problems. The doctor checks `settings.json` wiring, runtime availability, config validity, and can auto-fix issues. See [doctor diagnostics](../features/doctor.md).
