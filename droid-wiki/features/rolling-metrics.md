# Rolling metrics

## Purpose

The rolling metrics system provides real-time burn rate ($/hr), cache reuse percentage, and context depletion estimates. Instead of using lifetime session averages, it computes rates over a sliding window so momentary spikes do not distort the numbers.

## Architecture

A 60-minute ring buffer at `~/.claude/statusline-state.json` stores samples. Each sample captures a point-in-time snapshot:

```json
{
  "t": 1718400000,
  "cost": 4.23,
  "tokens_in": 150000,
  "tokens_out": 32000,
  "cache_read": 120000,
  "cache_creation": 8000
}
```

The statusline engine appends a sample on every render cycle. Samples older than 60 minutes are evicted on each write.

## Burn rate calculation

The burn rate uses a 10-minute window by default. The algorithm:

1. Filter samples to the last `window_min` minutes
2. Compute cost delta between oldest and latest sample
3. Divide by elapsed hours
4. Apply sanity guards

Guards prevent spikes from corrupting the display:

| Guard | Value | Rationale |
|-------|-------|-----------|
| Minimum span | 180 seconds (3 minutes) | One expensive API call can create a $800/hr spike |
| Maximum plausible rate | $200/hr | Anything higher is treated as a spike; falls back to session average |
| Negative cost delta | Returns `None` | Session reset or state corruption |

If the rolling rate returns `None` (insufficient data or spike detected), the engine falls back to the lifetime session rate.

## Cache metrics

Cache reuse shows what fraction of input tokens came from the prompt cache:

```
cache reuse 96% ↑2.3k saving
```

- The percentage is `cache_read / total_input_tokens * 100`
- The delta (`↑2.3k saving`) shows cache_read tokens added in the last 5 minutes
- When cache is idle, the display shows `cache reuse 96% idle`
- The word "reuse" emphasizes that cache reads cost roughly 10% of normal input

## Context depletion estimate

The `ctx_mins_left` field projects when the context window will fill, based on the rate of context growth over the rolling window. This drives the narrator's "context filling up" warnings.

## Dual implementation

The rolling state has parallel implementations that must stay in sync:

| File | Language | Used by |
|------|----------|---------|
| `lib/rolling_state.py` | Python | `engines/python-engine.py`, `narrator/observations.py` |
| `lib/rolling_state.js` | JavaScript | `engines/node-engine.js`, `narrator/narrator-node.js` |

Both use the same file format, same constants (`MAX_AGE_SECS = 3600`, `MIN_SPAN_SECS = 180`, `MAX_PLAUSIBLE_RATE = 200.0`), and same atomic write pattern.

## Key source files

| File | Purpose |
|------|---------|
| `lib/rolling_state.py` | Python ring buffer: append, evict, rate calculation |
| `lib/rolling_state.js` | Node.js port with identical API |
| `engines/python-engine.py` | Consumes rolling state for line 4 metrics |
| `engines/node-engine.js` | Node.js consumer |
| `tests/test_rolling_state.py` | Unit tests for rate calculation and spike guards |

## Related pages

- [Statusline tiers](statusline-tiers.md) — Where the metrics appear in the display
- [Narrator](narrator.md) — How rolling metrics feed into narrator insights
