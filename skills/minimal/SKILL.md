---
description: "Switch statusline to minimal tier. Use when user says 'statusline minimal', 'basic statusline', 'simple statusline', or 'minimal mode'."
argument-hint: ""
allowed-tools: ["Bash", "Read", "Write", "Edit"]
---

# Switch to Minimal Tier

Switch the statusline to minimal mode: peak status + model + CTX% + rate limit + git.

Preview: `OFF-PEAK ▸ Opus 4.6 ▸ CTX 40% ▸ 15% 5H ▸ main saved`

## Steps

1. Read `~/.claude/statusline-config.json`
2. Set `"tier": "minimal"` and `"mode": "minimal"`
3. Write the updated config
4. Tell the user: "Switched to minimal tier. Restart Claude Code to apply."
