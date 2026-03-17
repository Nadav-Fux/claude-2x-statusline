<div align="center">

# ⚡ claude-2x-statusline

### Know when to code. Never waste a 2X window again.

A minimal, Israel-timezone status line for **Claude Code** that shows when the doubled-usage promotion is active.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Claude Code](https://img.shields.io/badge/Claude_Code-compatible-blueviolet?logo=data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMjQiIGhlaWdodD0iMjQiIHZpZXdCb3g9IjAgMCAyNCAyNCIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48cGF0aCBkPSJNMTIgMkM2LjQ4IDIgMiA2LjQ4IDIgMTJzNC40OCAxMCAxMCAxMCAxMC00LjQ4IDEwLTEwUzE3LjUyIDIgMTIgMnoiIGZpbGw9IiNmZmYiLz48L3N2Zz4=)](https://claude.ai)
[![Cross-platform](https://img.shields.io/badge/Platform-macOS%20%7C%20Linux%20%7C%20Windows-green)](#requirements)

---

</div>

## Preview

Here's what it looks like in your Claude Code terminal:

```
╭─────────────────────────────────────────────────────────────────╮
│                                                                 │
│  claude ›                                                       │
│                                                                 │
│  14:23  ██ 2x ACTIVE ██ 5h 37m left  | main +3                 │
│                                                                 │
╰─────────────────────────────────────────────────────────────────╯
```

### Status states

**2X Active — plenty of time** (green background)
```diff
+ 09:15  2x ACTIVE   6h 45m left  | feature-branch +2
```

**2X Active — running out** (yellow background)
```
! 12:30  2x ACTIVE   1h 30m left  | main
```

**2X Active — almost gone!** (red background)
```diff
- 13:45  2x ACTIVE   15m left  | main +7
```

**Peak hours — 1X mode** (dim, with countdown)
```
  15:20  PEAK  2x returns in 4h 40m | main
```

**Weekend — all day 2X**
```diff
+ 11:00  2x ACTIVE   21h 00m left  weekend | main
```

---

## How it works

```
 ┌──────────────────────────────────────────────────────────┐
 │                    Israel Time (auto DST)                │
 │                                                          │
 │  ╔═══════════╗                        ╔═══════════╗      │
 │  ║  2X  ON   ║  ◀── off-peak ──▶     ║  1X PEAK  ║      │
 │  ╚═══════════╝                        ╚═══════════╝      │
 │  00:00 ░░░░░░░░░░░░░░ 14:00 ████████ 20:00 ░░░░░ 00:00 │
 │        ▲ 2X active          ▲ peak          ▲ 2X again  │
 │                                                          │
 │  Weekend: 2X ALL DAY  (Fri 9:00 → Mon 9:00)            │
 └──────────────────────────────────────────────────────────┘
```

Pure Python (bash/Linux/macOS) or PowerShell (Windows), zero external dependencies. Calculates Israel timezone from UTC (handles DST), checks the current promotion window, and outputs a single ANSI-colored line.

| Color | Meaning | Time left |
|:-----:|---------|-----------|
| 🟩 | 2X active, relax | > 3 hours |
| 🟨 | 2X active, plan ahead | 1–3 hours |
| 🟥 | 2X active, use it NOW | < 1 hour |
| ⬜ | Peak (1X), countdown to 2X | — |

---

## Promotion schedule

Based on the [Claude March 2026 promotion](https://support.claude.com/en/articles/14063676-claude-march-2026-usage-promotion):

| When | Status | Israel Time |
|------|:------:|-------------|
| Weekdays off-peak | **2X** | 00:00–14:00, 20:00–00:00 |
| Weekdays peak | 1X | 14:00–20:00 |
| Weekends | **2X** | Friday 9:00 → Monday 9:00 |

**Active: March 13–27, 2026.** Edit `PROMO_START` / `PROMO_END` in the script for future promotions.

---

## Install

### macOS / Linux

**One-liner:**
```bash
git clone https://github.com/Nadav-Fux/claude-2x-statusline.git ~/.claude/cc-2x-statusline \
  && bash ~/.claude/cc-2x-statusline/install.sh
```

**Manual:**
1. Copy `statusline.sh` to `~/.claude/bin/`
2. Add to `~/.claude/settings.json`:
```json
{
  "statusLine": {
    "type": "command",
    "command": "bash ~/.claude/bin/statusline.sh"
  }
}
```
3. Restart Claude Code.

### Windows (PowerShell)

**One-liner:**
```powershell
irm https://raw.githubusercontent.com/Nadav-Fux/claude-2x-statusline/main/install.ps1 | iex
```

**Manual:**
1. Copy `statusline.ps1` to `~\.claude\bin\`
2. Add to `~\.claude\settings.json`:
```json
{
  "statusLine": {
    "type": "command",
    "command": "powershell -NoProfile -ExecutionPolicy Bypass -File \"%USERPROFILE%\\.claude\\bin\\statusline.ps1\""
  }
}
```
3. Restart Claude Code.

---

## Uninstall

**macOS / Linux:**
```bash
bash ~/.claude/cc-2x-statusline/uninstall.sh
```

**Windows:**
```powershell
Remove-Item "$env:USERPROFILE\.claude\bin\statusline.ps1" -Force
# Then remove the statusLine entry from settings.json
```

---

## Customization

| What | Where | Example |
|------|-------|---------|
| Timezone | `il_offset` in script | Change to `1` for CET |
| Promo dates | `PROMO_START` / `PROMO_END` | `20260401` for April promo |
| Peak hours | `peak_start` / `peak_end` (UTC) | `14` / `20` for different window |

---

## Requirements

**macOS / Linux:**
- `python3` (no external packages)
- Claude Code with status line support

**Windows:**
- PowerShell 5.1+ (built-in on Windows 10/11)
- Claude Code with status line support
- No Python needed!

---

<div align="center">

**Made with Claude Code** | [MIT License](LICENSE)

</div>
