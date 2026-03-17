---
description: "Switch statusline to minimal tier. Use when user says 'statusline minimal', 'basic statusline', 'simple statusline', or 'minimal mode'."
argument-hint: ""
allowed-tools: ["Bash", "Read", "Write", "Edit"]
---

# Switch to Minimal Tier

Switch the statusline to minimal mode: time + 2x promo + git only.

Preview: `22:44 ▸ ⚡ 2x 5h left ▸ main ~3`

## Steps

1. Read `~/.claude/statusline-config.json`
2. Set `"tier": "minimal"` and `"mode": "minimal"`
3. Write the updated config
4. Tell the user: "Switched to minimal tier. Restart Claude Code to apply."
