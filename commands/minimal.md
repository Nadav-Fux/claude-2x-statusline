---
description: "Switch statusline to minimal tier"
allowed-tools: ["Bash", "Read", "Write", "Edit"]
---

Switch the statusline to minimal tier.

Preview: `⚡ 2x ACTIVE 2h left ▸ Opus 4.6 ▸ CTX 27% ▸ 17% 5H ▸ main 2 unsaved`

## Steps

1. Read `~/.claude/statusline-config.json`
2. Set `"tier": "minimal"` and `"mode": "minimal"`
3. Write the updated config
4. Tell the user: "Switched to minimal. Restart Claude Code to apply."
