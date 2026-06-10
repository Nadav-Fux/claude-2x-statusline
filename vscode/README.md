# Claude Code Statusline — VS Code Extension

Displays a live status bar inside VS Code (and compatible editors such as Cursor, Windsurf, and Antigravity) showing:

- **Peak / Off-Peak hours** for Claude Code rate-limit windows (configurable timezone)
- **5-hour and 7-day rate-limit utilisation** with battery-bar visualisation (reads Anthropic OAuth API)
- **Context-window usage** (tokens used / window size) including active workflow agents and subagent token counts when multi-agent workflows are running
- **Effort level** (low / medium / high) from your `~/.claude/settings.json`

## Data source

Context-window data is read from `%TEMP%\claude\statusline-context.json`, written by the
[claude-2x-statusline](https://github.com/Nadav-Fux/claude-2x-statusline) statusline engine hooks.
The file is ignored if it is older than 10 minutes (session ended).

## Configuration

Settings are under `claudeStatusline.*` in VS Code preferences:
- `tier` — display tier (`auto` | `minimal` | `standard` | `full`)
- `refreshInterval` — poll interval in seconds (default 30)
- `showRateLimits` — toggle 5h/7d rate-limit items
- `showPeakHours` — toggle peak-hours item
