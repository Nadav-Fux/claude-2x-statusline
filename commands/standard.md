---
description: "Switch statusline to standard tier"
allowed-tools: ["Bash", "Read", "Write", "Edit"]
---

Switch the statusline to standard tier.

Preview: `⚡ 2x ACTIVE 2h left ▸ Opus 4.6 ▸ 270K/1.0M 27% ▸ $7.96 ▸ ▰▱▱▱▱▱▱▱▱▱ 17% ▸ main 2 unsaved`

## Steps

1. Read `~/.claude/statusline-config.json`
2. Set `"tier": "standard"` and `"mode": "minimal"`
3. Write the updated config
4. Tell the user: "Switched to standard. Restart Claude Code to apply."
