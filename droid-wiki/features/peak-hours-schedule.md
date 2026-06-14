# Peak hours and schedule

## Purpose

The schedule system lets the maintainer push configuration changes (peak-hour windows, promotional banners, release notifications, feature flags) to all running statuslines without requiring users to update. A JSON file on GitHub is fetched every 3 hours and cached locally.

## Schedule format

The `schedule.json` file at the repository root defines the remote configuration:

```json
{
  "v": 5,
  "mode": "normal",
  "default_tier": "full",
  "peak": {
    "enabled": true,
    "tz": "UTC",
    "days": [1, 2, 3, 4, 5],
    "start": 13,
    "end": 19,
    "label_peak": "Peak",
    "label_offpeak": "Off-Peak"
  },
  "banners": [
    { "text": "...", "expires": "2026-06-15", "color": "red" }
  ],
  "release": {
    "latest_version": "2.2.0",
    "minimum_version": "2.1.0",
    "command": "/statusline-update"
  },
  "features": {
    "show_peak_segment": true,
    "show_rate_limits": true,
    "show_timeline": true
  }
}
```

See [schedule format reference](../reference/schedule-format.md) for all fields.

## Fetch and cache cycle

1. Engine checks `~/.claude/statusline-schedule.json` for a cached copy
2. If cache age exceeds `schedule_cache_hours` (default 3), fetches from GitHub raw URL
3. Fetch uses HTTPS with a 5-second timeout
4. On fetch failure, falls back to cached copy or built-in defaults
5. Schedule is normalized: missing fields are filled from `DEFAULT_SCHEDULE`

The fetch is non-blocking on failure. A corrupt or null schedule falls back to defaults rather than crashing the statusline.

## Auto-timezone conversion

Peak hours are defined in a source timezone (currently UTC). The engine converts them to the user's local timezone for display:

- Uses `datetime.now(timezone.utc)` and local timezone detection
- Handles DST transitions
- Correctly handles the Saturday-to-Sunday cross-timezone spillover (a Pacific Saturday peak that reaches into Sunday for UTC+3 users)

This cross-timezone fix was a notable bug fix (see [lore](../lore.md)). Earlier versions did not detect the spillover window.

## Display behavior

When `mode` is `"normal"` (current state), the timeline line is hidden entirely. Rate limit bars and metrics still render in full tier.

When `mode` is `"peak_hours"`, the timeline renders a horizontal bar showing the peak window in the user's local time, with a position marker for "now."

Peak segment colors:

| State | Color | Condition |
|-------|-------|-----------|
| Off-Peak | Green badge | Outside peak window |
| Peak (deep) | Red badge | Many hours remain in peak |
| Peak (ending) | Yellow badge | Less than 1-2 hours remain |
| Peak (almost over) | Green badge | Less than 30 minutes remain |

## Banner system

Banners are promotional or informational notices with an expiration date. The engine filters out expired banners before display. Multiple banners can be active simultaneously. Colors: `red` (urgent), `yellow` (info).

## Release checking

The `release` block drives update notifications:

- `latest_version` — shown when user's version is below this
- `minimum_version` — shown as "required" when user's version is below this
- Version comparison uses semantic versioning (major.minor.patch)

## Key source files

| File | Purpose |
|------|---------|
| `schedule.json` | Remote schedule source (fetched by all statuslines) |
| `engines/python-engine.py` | Schedule fetch, normalize, timezone conversion |
| `engines/node-engine.js` | Node.js parity for schedule handling |
| `vscode/extension.ts` | VS Code extension schedule handling |

## Related pages

- [Statusline tiers](statusline-tiers.md) — How feature flags control rendering
- [Configuration reference](../reference/configuration.md) — Local config file format
- [Schedule format](../reference/schedule-format.md) — Complete schedule.json field reference
