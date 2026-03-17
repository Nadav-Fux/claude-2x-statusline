---
description: "Switch statusline to standard tier. Use when user says 'statusline standard', 'normal statusline', 'default statusline', or 'standard mode'."
argument-hint: ""
allowed-tools: ["Bash", "Read", "Write", "Edit"]
---

# Switch to Standard Tier

Switch the statusline to standard mode: time + 2x + model + context % + cost + duration + git.

Preview: `22:44 ▸ ⚡ 2x 5h left ▸ Opus 4.6 ▸ 40% ▸ $0.42 ▸ 23m ▸ main ~3`

## Steps

1. Read `~/.claude/statusline-config.json`
2. Set `"tier": "standard"` and `"mode": "minimal"`
3. Write the updated config
4. Tell the user: "Switched to standard tier. Restart Claude Code to apply."
