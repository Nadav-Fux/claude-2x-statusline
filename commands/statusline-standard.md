---
description: "Switch statusline to standard tier"
allowed-tools: ["Read", "Write"]
---

Switch the statusline to standard tier.

1. Read `~/.claude/statusline-config.json`
2. Set `"tier": "standard"` and `"mode": "minimal"`
3. Write the updated config
4. Tell the user: "Switched to standard. Restart Claude Code to apply."
