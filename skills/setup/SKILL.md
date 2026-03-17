---
description: "Set up the claude-2x-statusline. Use when user says 'statusline setup', 'install statusline', 'configure statusline', or 'set up status line'."
argument-hint: ""
allowed-tools: ["Bash", "Read", "Write", "Edit", "AskUserQuestion"]
---

# Statusline Setup

Install and configure the claude-2x-statusline for Claude Code.

## Steps

1. Ask the user which tier they want using AskUserQuestion with these options:
   - **Minimal** — Time + 2x promo + git (`22:44 ▸ ⚡ 2x 5h left ▸ main ~3`)
   - **Standard** — + model + context + cost + duration (`22:44 ▸ ⚡ 2x 5h left ▸ Opus 4.6 ▸ 40% ▸ $0.42 ▸ 23m ▸ main ~3`)
   - **Full** — + rate limits + timeline dashboard (adds `▰▰▰▰▱▱▱▱▱▱ 40%` bar + timeline + weekly limits)

2. Write the config file at `~/.claude/statusline-config.json`:
```json
{
  "tier": "<chosen_tier>",
  "mode": "<minimal for minimal/standard, full for full>",
  "promo_start": 20260313,
  "promo_end": 20260327
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

5. Tell the user to restart Claude Code to see the new statusline.
