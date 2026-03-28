---
description: "Switch statusline to full tier with dashboard. Use when user says 'statusline full', 'full statusline', 'statusline dashboard', 'show rate limits', or 'full mode'."
argument-hint: ""
allowed-tools: ["Bash", "Read", "Write", "Edit"]
---

# Switch to Full Tier

Switch the statusline to full mode with rate limits dashboard and timeline.

Preview:
```
OFF-PEAK ▸ Opus 4.6 ▸ 400K/1.0M 40% ▸ Cache:94% ▸ $4.2/hr ▸ $7.96 ▸ main saved

│ ━━━━━━━━━━━━━●━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ │  ━ off-peak ━ peak (3pm-9pm)
│ ▸ 5h ▰▰▱▱▱▱▱▱▱▱ 15% ⟳ 5pm ✓ · weekly ▰▰▰▱▱▱▱▱▱▱ 31% ⟳ 4/4 │
```

## Steps

1. Read `~/.claude/statusline-config.json`
2. Set `"tier": "full"` and `"mode": "full"`
3. Write the updated config
4. Tell the user: "Switched to full tier with dashboard. Restart Claude Code to apply."
