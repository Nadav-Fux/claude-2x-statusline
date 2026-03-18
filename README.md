<div align="center">

# claude-2x-statusline

### Modular, multi-tier statusline for Claude Code

Track the 2X promotion, monitor usage, see rate limits — all in one line.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Claude Code](https://img.shields.io/badge/Claude_Code-compatible-blueviolet)](#)
[![Cross-platform](https://img.shields.io/badge/Platform-macOS%20%7C%20Linux%20%7C%20Windows-green)](#requirements)

**[Live Preview & Tier Picker](https://statusline.nvision.me)**

---

</div>

## Preview

### Minimal tier
```
22:44 ▸ ⚡ 2x  5h 37m left ▸ main ~3
```

### Standard tier
```
22:44 ▸ ⚡ 2x  5h 37m left ▸ Opus 4.6 ▸ 40% ▸ $0.420 ▸ 23m ▸ main ~3
```

### Full tier
```
22:44 ▸ ⚡ 2x  5h 37m left ▸ Opus 4.6 ▸ ▰▰▰▰▱▱▱▱▱▱ 40% ▸ $0.42 ▸ main ~3 ↑1

│ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━●━━━━━━━━ │  ━ 2x ━ 1x 14:00-20:00  ● now
│ ▸ current ▰▰▱▱▱▱▱▱▱▱ 15% ⟳ 10pm · weekly ▰▰▰▱▱▱▱▱▱▱ 31% ❄ ⟳ mar 20 │
```

### During peak hours (1X)
```
16:30 ▸ PEAK → 2x in 4h 40m ▸ Opus 4.6 ▸ ▰▰▰▰▰▰▰▱▱▱ 72% ▸ $1.23 ▸ main
```

---

## Tiers

| Tier | Segments | Best for |
|------|----------|----------|
| **Minimal** | Time + 2x promo + git | Clean, distraction-free |
| **Standard** | + model + context % + cost + duration | Daily use (default) |
| **Full** | + rate limits + timeline + lines changed | Power users |
| **Custom** | Pick individual segments | Your choice |

Choose your tier during install, or edit `~/.claude/statusline-config.json` anytime.

---

## Segments

| Segment | What it shows | Source | Tier |
|---------|---------------|--------|------|
| `time` | Israel time (auto DST) | Calculated | All |
| `promo_2x` | 2X status + countdown | Calculated | All |
| `git_branch` | Current branch | `git` | All |
| `git_dirty` | Uncommitted changes | `git` | All |
| `model` | Active model name | Claude Code stdin | Standard+ |
| `context` | Context window usage % | Claude Code stdin | Standard+ |
| `cost` | Session cost in USD | Claude Code stdin | Standard+ |
| `duration` | Session duration | Claude Code stdin | Standard+ |
| `git_ahead_behind` | Commits ahead/behind remote | `git` | Full |
| `lines` | Lines added/removed | Claude Code stdin | Full |
| `rate_limits` | Current + weekly utilization | OAuth API (cached 60s) | Full |
| `ts_errors` | TypeScript errors (cached) | `/tmp/tsc-errors-*.txt` | Full |

---

## Full mode (`--full`)

Add `--full` to your statusline command for the expanded dashboard:

```
│ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━●━━━━━━━━━━━━━ │  ━ 2x ━ peak
│ ▸ 5h ▰▰▱▱▱▱▱▱▱▱ 15% ⟳ 10pm · weekly ▰▰▰▱▱▱▱▱▱▱ 32% 2x ⟳ mar 20 │
```

- **Timeline bar** — 48-char visualization of today's 2x/peak hours with current position
- **Rate limits** — 5-hour and weekly utilization with reset times
- **2x indicator** — Shows when usage is doubled

---

## Engines (auto-detected)

| Engine | Platform | Features | Dependencies |
|--------|----------|----------|--------------|
| **Python** | macOS, Linux, Windows | All segments + rate limits + full mode | Python 3 |
| **PowerShell** | Windows | All segments + rate limits + full mode | PowerShell 5.1+ (built-in) |
| **Node.js** | Any | All segments except rate limits | Node.js |
| **Pure bash** | Any | Minimal tier only | None |

The wrapper auto-detects: Python > Node.js > pure bash. Windows uses PowerShell directly.

---

## Install

### Option 1: Claude Code Plugin (recommended)

If you have Claude Code plugins enabled:
```
/plugin
```
Then select `Nadav-Fux/claude-2x-statusline`. After install, use `/statusline setup` to pick your tier.

### Option 2: npx (one command)

```bash
npx claude-2x-statusline
```

### Option 3: Git clone

**macOS / Linux:**
```bash
git clone https://github.com/Nadav-Fux/claude-2x-statusline.git ~/.claude/cc-2x-statusline \
  && bash ~/.claude/cc-2x-statusline/install.sh
```

**Windows (PowerShell):**
```powershell
irm https://raw.githubusercontent.com/Nadav-Fux/claude-2x-statusline/main/install.ps1 | iex
```

### Option 4: curl (one-liner)

```bash
curl -fsSL https://raw.githubusercontent.com/Nadav-Fux/claude-2x-statusline/main/install.sh | bash
```

### Manual

1. Clone or download to `~/.claude/cc-2x-statusline/`
2. Add to `~/.claude/settings.json`:

```json
{
  "statusLine": {
    "type": "command",
    "command": "bash ~/.claude/cc-2x-statusline/statusline.sh"
  }
}
```

For full mode:
```json
{
  "statusLine": {
    "type": "command",
    "command": "bash ~/.claude/cc-2x-statusline/statusline.sh --full"
  }
}
```

3. Restart Claude Code.

---

## Configuration

Create `~/.claude/statusline-config.json` to customize:

```json
{
  "tier": "standard",
  "mode": "minimal",
  "promo_start": 20260313,
  "promo_end": 20260327
}
```

### Custom tier

Pick exactly which segments you want:

```json
{
  "tier": "custom",
  "segments": {
    "time": true,
    "promo_2x": true,
    "model": true,
    "context": true,
    "git_branch": true,
    "git_dirty": true,
    "git_ahead_behind": false,
    "cost": true,
    "duration": false,
    "lines": false,
    "ts_errors": false,
    "rate_limits": true
  }
}
```

See `config.example.json` for all options.

---

## Promotion schedule

| When | Status | Israel Time |
|------|:------:|-------------|
| Weekdays off-peak | **2X** | 00:00–14:00, 20:00–00:00 |
| Weekdays peak | 1X | 14:00–20:00 |
| Weekends | **2X** | Friday 9:00 → Monday 9:00 |

**Active: March 13–27, 2026.** Edit `promo_start` / `promo_end` in config for future promotions.

---

## Uninstall

```bash
bash ~/.claude/cc-2x-statusline/uninstall.sh
```

---

## Requirements

- Claude Code with status line support
- **One of:** Python 3 | Node.js | PowerShell 5.1+ | bash (minimal only)
- No external packages needed for any engine

---

<div align="center">

**Made with Claude Code** | [MIT License](LICENSE)

</div>
