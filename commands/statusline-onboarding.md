---
description: "Show the post-install quickstart for claude-2x-statusline"
allowed-tools: ["Read"]
---

Show a concise first-run quickstart after installing or updating `claude-2x-statusline`.

## Steps

1. Read `~/.claude/statusline-config.json` if it exists.
2. Tell the user which tier is currently active (`minimal`, `standard`, or `full`).
3. Tell the user the 4 most useful next commands:
   - `/statusline-doctor` — verify wiring and hook health
   - `/statusline-update` — update to the latest version
   - `/statusline-minimal`, `/statusline-standard`, `/statusline-full` — change tier
   - `/explain peak_hours` or `/explain rate_limits` — learn what the statusline is showing
4. If the config file is missing, tell the user to run `/statusline-init` first.
5. End with: "If you just installed it, restart Claude Code once so the status line and hooks reload."
