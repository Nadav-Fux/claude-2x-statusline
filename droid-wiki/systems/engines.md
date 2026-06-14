# Engines

## Purpose

Three independent implementations of the statusline renderer, each targeting a different runtime. They are not layered. The dispatcher picks one based on what is available on the machine.

## Dispatch flow

`statusline.sh` is the entry point. It sources `lib/resolve-runtime.sh` and tries interpreters in priority order:

```bash
PY=$(resolve_runtime python)
NODE=$(resolve_runtime node)

if [ -n "$PY" ]; then
    exec "$PY" "$SCRIPT_DIR/engines/python-engine.py" "$@"
elif [ -n "$NODE" ]; then
    exec "$NODE" "$SCRIPT_DIR/engines/node-engine.js" "$@"
else
    exec bash "$SCRIPT_DIR/engines/bash-engine.sh" "$@"
fi
```

Claude Code pipes a JSON object on stdin containing session metadata. The chosen engine reads it, renders ANSI-colored output, and writes to stdout.

## Engine comparison

| Aspect | Python | Node.js | Bash |
|--------|--------|---------|------|
| File | `engines/python-engine.py` | `engines/node-engine.js` | `engines/bash-engine.sh` |
| Lines | 1670 | 915 | 406 |
| Segments | All | All | 4 only (peak, model, context, git) |
| Rolling metrics | Yes | Yes | No |
| Narrator support | Yes (via `narrator/` package) | Yes (via `narrator-narrator-node.js`) | No |
| Schedule fetch | Yes | Yes | Yes (minimal) |
| Telemetry | Yes | Yes | Yes |
| Rate limits display | Yes | Yes | No |

## Python engine internals

`engines/python-engine.py` is the primary implementation. Key sections:

1. **ANSI constants** — Shared color palette
2. **Tier presets** — Segment lists for minimal/standard/full
3. **Schedule handling** — Fetch, cache, normalize, timezone conversion
4. **Segment renderers** — Individual functions per segment (`render_model`, `render_context`, `render_cost`, etc.)
5. **Timeline builder** — Horizontal schedule bar with position marker
6. **Rate limits line** — Battery bar visualization for 5h and weekly limits
7. **Metrics line** — Burn rate, context depletion, cache reuse
8. **Main loop** — Read stdin JSON, load config, render segments, append rolling sample, output

The engine imports shared libraries from `lib/`:
- `rolling_state` for burn rate and cache metrics
- `workflows` for live subagent detection

## Node.js engine internals

`engines/node-engine.js` mirrors the Python engine's structure. It imports `lib/rolling_state.js` for the rolling window. The Node.js engine exists for environments where Python is unavailable but Node.js is installed (common in JavaScript-heavy dev environments).

## Bash engine internals

`engines/bash-engine.sh` is the last-resort fallback. It renders only peak hours, model, context, git branch, and git dirty. It includes its own telemetry ID generation cascade and heartbeat logic. No rolling metrics, no rate limits, no narrator.

## Config loading

All engines read `~/.claude/statusline-config.json` for tier, mode, segment toggles, schedule URL, and telemetry settings. Missing or invalid config falls back to defaults. The `tier` field selects the segment preset; `mode` controls whether dashboard lines render.

## Schedule fetching

Python and Node engines fetch `schedule.json` from the configured URL (default: GitHub raw). The fetch is cached at `~/.claude/statusline-schedule.json` with a configurable TTL (default 3 hours). Fetch failures fall back to cache or built-in `DEFAULT_SCHEDULE`. See [peak hours and schedule](../features/peak-hours-schedule.md).

## Key source files

| File | Lines | Purpose |
|------|-------|---------|
| `statusline.sh` | 23 | Entry point and runtime dispatcher |
| `engines/python-engine.py` | 1670 | Primary engine with all features |
| `engines/node-engine.js` | 915 | Node.js parity implementation |
| `engines/bash-engine.sh` | 406 | Minimal Bash fallback |

## Related pages

- [Runtime resolution](runtime-resolution.md) — How the dispatcher finds interpreters
- [Shared libraries](shared-libraries.md) — Rolling state and workflow detection
- [Statusline tiers](../features/statusline-tiers.md) — Segment system and rendering
