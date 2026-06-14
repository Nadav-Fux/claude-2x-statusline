# Schedule format

The `schedule.json` file at the repository root is fetched by all running statuslines every 3 hours. It controls peak-hour labels, banners, release notifications, and feature flags.

## Current schedule

```json
{
  "v": 5,
  "updated": "2026-06-10",
  "cache_hours": 3,
  "mode": "normal",
  "default_tier": "full",
  "peak": {
    "enabled": true,
    "tz": "UTC",
    "days": [1, 2, 3, 4, 5],
    "start": 13,
    "end": 19,
    "label_peak": "Peak",
    "label_offpeak": "Off-Peak",
    "note": "Peak hours removed 2026-05-06..."
  },
  "labels": {
    "five_hour": "5h interactive",
    "weekly": "weekly interactive"
  },
  "banners": [
    {
      "text": "SDK credit cutover Jun 15 - claim it or claude -p stops",
      "expires": "2026-06-15",
      "color": "red"
    }
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

## Field reference

### Top-level fields

| Field | Type | Description |
|-------|------|-------------|
| `v` | number | Schema version (currently 5) |
| `updated` | string | Date this schedule was last modified (YYYY-MM-DD) |
| `cache_hours` | number | Suggested cache duration for clients |
| `mode` | string | `"normal"` (no peak throttling) or `"peak_hours"` |
| `default_tier` | string | Suggested tier for new installations |
| `peak` | object | Peak-hour window configuration |
| `labels` | object | Custom labels for rate limit segments |
| `banner` | object | Single legacy banner (deprecated, use `banners`) |
| `banners` | array | Active promotional banners with expiration |
| `release` | object | Version checking and update notification |
| `features` | object | Feature flag toggles for rendering |

### Peak configuration

| Field | Type | Description |
|-------|------|-------------|
| `enabled` | boolean | Whether peak segment renders |
| `tz` | string | Source timezone (e.g., `"UTC"`, `"America/Los_Angeles"`) |
| `days` | number[] | Days of week (1=Monday through 5=Friday) |
| `start` | number | Start hour (24h, in source timezone) |
| `end` | number | End hour (24h, in source timezone) |
| `label_peak` | string | Text shown during peak |
| `label_offpeak` | string | Text shown during off-peak |
| `note` | string | Internal note (not displayed) |

### Banner format

| Field | Type | Description |
|-------|------|-------------|
| `text` | string | Banner message text |
| `expires` | string | Expiration date (YYYY-MM-DD) |
| `color` | string | `"red"` (urgent), `"yellow"` (info) |

### Release configuration

| Field | Type | Description |
|-------|------|-------------|
| `latest_version` | string | Current release version |
| `minimum_version` | string | Minimum required version |
| `command` | string | Update command to suggest |
| `available_text` | string | Message for optional update |
| `required_text` | string | Message for required update |

### Feature flags

| Flag | Default | Effect |
|------|---------|--------|
| `show_peak_segment` | `true` | Toggle peak hours segment |
| `show_rate_limits` | `true` | Toggle rate limit bars |
| `show_timeline` | `true` | Toggle schedule timeline |

## Normalization

Engines normalize the schedule on load, filling missing fields from built-in defaults. A null, missing, or corrupt schedule falls back to `DEFAULT_SCHEDULE` rather than crashing.

## Related pages

- [Peak hours and schedule](../features/peak-hours-schedule.md) — How the schedule is used
- [Configuration](configuration.md) — Local config including `schedule_url` and `schedule_cache_hours`
