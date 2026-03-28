---
description: "Set up the claude-2x-statusline. Use when user says 'statusline setup', 'install statusline', 'configure statusline', or 'set up status line'."
argument-hint: ""
allowed-tools: ["Bash", "Read", "Write", "Edit", "AskUserQuestion"]
---

# Statusline Setup

Install and configure the claude-2x-statusline for Claude Code.

## Steps

1. Ask the user which tier they want using AskUserQuestion with these options:
   - **Minimal** — Peak status + model + CTX% + rate limit + git
   - **Standard** — + detailed tokens + cost + rate limit bar
   - **Full** (recommended) — + timeline + rate limits dashboard

2. Write the config file at `~/.claude/statusline-config.json`:
```json
{
  "tier": "<chosen_tier>",
  "mode": "<minimal for minimal/standard, full for full>",
  "schedule_url": "https://raw.githubusercontent.com/Nadav-Fux/claude-2x-statusline/main/schedule.json",
  "schedule_cache_hours": 6
}
```

3. Find the plugin root directory (where `engines/` lives). Use the `CLAUDE_PLUGIN_ROOT` environment variable if available, otherwise find it via:
```bash
find ~/.claude -name "python-engine.py" -path "*/engines/*" 2>/dev/null | head -1 | xargs dirname | xargs dirname
```

4. Update `~/.claude/settings.json` to set the statusLine command pointing to the plugin's `statusline.sh`:
```json
{
  "statusLine": {
    "type": "command",
    "command": "bash <plugin_root>/statusline.sh"
  }
}
```

5. Fetch the initial schedule:
```bash
curl -s https://raw.githubusercontent.com/Nadav-Fux/claude-2x-statusline/main/schedule.json -o ~/.claude/statusline-schedule.json
```

6. Tell the user to restart Claude Code to see the new statusline. Peak hours auto-update from GitHub every 6 hours.
