---
description: "Switch statusline tier (minimal, standard, full)"
argument-hint: "minimal | standard | full"
allowed-tools: ["Bash", "Read", "Write", "Edit"]
---

# Switch Statusline Tier

The user wants to switch their statusline tier. The argument tells you which tier.

## Tiers

- **minimal** — promo + model + CTX % + 5H % + git
- **standard** — + detailed tokens + cost + rate limit bar
- **full** — + multiline dashboard with timeline and rate limits

## Steps

1. Read `~/.claude/statusline-config.json`
2. Based on the argument:
   - `minimal`: set `"tier": "minimal"` and `"mode": "minimal"`
   - `standard`: set `"tier": "standard"` and `"mode": "minimal"`
   - `full`: set `"tier": "full"` and `"mode": "full"`
3. Write the updated config
4. Tell the user: "Switched to [tier]. Restart Claude Code to apply."
