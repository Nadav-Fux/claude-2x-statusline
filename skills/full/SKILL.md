---
description: "Switch statusline to full tier with dashboard. Use when user says 'statusline full', 'full statusline', 'statusline dashboard', 'show rate limits', or 'full mode'."
argument-hint: ""
allowed-tools: ["Bash", "Read", "Write", "Edit"]
---

# Switch to Full Tier

Switch the statusline to full mode with rate limits dashboard and timeline.

Preview:
```
22:44 ▸ ⚡ 2x 5h left ▸ Opus 4.6 ▸ ▰▰▰▰▱▱▱▱▱▱ 40% ▸ $0.42 ▸ main ~3 ↑1

│ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━●━━━━━━━━━━━━━━━━━━ │
│ ▸ current ▰▰▱▱▱▱▱▱▱▱ 15% ⟳ 10pm · weekly ▰▰▰▱▱▱▱▱▱▱ 31% ❄ │
```

## Steps

1. Read `~/.claude/statusline-config.json`
2. Set `"tier": "full"` and `"mode": "full"`
3. Write the updated config
4. Tell the user: "Switched to full tier with dashboard. Restart Claude Code to apply."
