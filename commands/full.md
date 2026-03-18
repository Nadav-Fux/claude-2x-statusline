---
description: "Switch statusline to full tier (with dashboard)"
allowed-tools: ["Bash", "Read", "Write", "Edit"]
---

Switch the statusline to full tier with multiline dashboard.

Preview:
```
⚡ 2x ACTIVE 2h left ▸ Opus 4.6 ▸ 270K/1.0M 27% ▸ $7.96 ▸ main 2 unsaved
│ ━━━━━━━━━━━━●━━━━━━━━━━━━━ │  ━ 2x ━ peak
│ ▸ 5h 17% ⟳ 3:00pm · weekly 34% ⟳ 19/3 │
```

## Steps

1. Read `~/.claude/statusline-config.json`
2. Set `"tier": "full"` and `"mode": "full"`
3. Write the updated config
4. Tell the user: "Switched to full. Restart Claude Code to apply."
