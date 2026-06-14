# Configuration

The main configuration file is `~/.claude/statusline-config.json`. It is created by the installer and edited by slash commands.

## Full example

```json
{
  "tier": "full",
  "mode": "full",
  "segments": {
    "peak_hours": true,
    "model": true,
    "context": true,
    "workflows": true,
    "git_branch": true,
    "git_dirty": true,
    "cost": true,
    "rate_limits": true,
    "effort": true,
    "env": true,
    "auth_mode": false,
    "sdk_meter": false
  },
  "schedule_url": "https://raw.githubusercontent.com/Nadav-Fux/claude-2x-statusline/main/schedule.json",
  "schedule_cache_hours": 3,
  "telemetry": true,
  "diagnostics": "full"
}
```

## Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `tier` | string | `"standard"` | Display tier: `minimal`, `standard`, or `full` |
| `mode` | string | `"minimal"` | Rendering mode: `minimal` (line 1 only) or `full` (all dashboard lines) |
| `segments` | object | tier-dependent | Per-segment enable/disable overrides |
| `schedule_url` | string | GitHub raw URL | URL for remote schedule fetch |
| `schedule_cache_hours` | number | `3` | Hours between schedule refreshes |
| `telemetry` | boolean | `true` | Enable/disable all telemetry |
| `diagnostics` | string | `"full"` | Doctor report privacy: `full`, `minimal`, or `off` |

## Segment toggles

Individual segments can be enabled or disabled via the `segments` object. When a segment is not listed, the tier preset determines whether it renders.

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `STATUSLINE_DEBUG` | unset | Set to `1` for debug output on stderr |
| `STATUSLINE_NARRATOR_ENABLED` | `1` | Narrator kill switch |
| `STATUSLINE_NARRATOR_HAIKU` | `auto` | Haiku layer: `auto`, `1`, `0` |
| `STATUSLINE_NARRATOR_HAIKU_INTERVAL_MIN` | `15` | Max minutes between Haiku calls |
| `STATUSLINE_NARRATOR_THROTTLE_MIN` | `5` | Min minutes between narrator emits |
| `STATUSLINE_NARRATOR_LANGS` | auto-detect | `en`, `he`, or `en,he` |
| `STATUSLINE_DISABLE_TELEMETRY` | unset | Set to `1` to disable all telemetry |
| `ANTHROPIC_API_KEY` | unset | Enables Haiku narrator layer |
| `CLAUDE_SESSION_ID` | set by Claude Code | Session identifier for narrator memory rotation |
| `CLAUDE_PLUGIN_ROOT` | set by Claude Code | Plugin root directory for hook resolution |

## Related files

| File | Location | Purpose |
|------|----------|---------|
| `statusline-config.json` | `~/.claude/` | Main config (this page) |
| `statusline-state.json` | `~/.claude/` | Rolling window state (60-min ring buffer) |
| `statusline-schedule.json` | `~/.claude/` | Cached remote schedule |
| `narrator-memory.json` | `~/.claude/` | Narrator cross-session memory |
| `settings.json` | `~/.claude/` | Claude Code settings (statusLine stanza, hooks) |
| `.statusline-telemetry-id` | `~/.claude/` | Anonymous telemetry identifier |
| `statusline-usage-cache.json` | `~/.claude/` | Rate limit usage cache (VS Code extension) |
