# Patterns and conventions

## Never crash the caller

Every engine, hook, and script wraps its logic in error handling that fails silently. The statusline runs as a child of Claude Code; a crash would break the user's session. This pattern appears everywhere:

- `engines/python-engine.py` wraps all segment rendering in try/except
- `narrator/engine.py` catches all exceptions and returns `None`
- `hooks/narrator-*.sh` always exit 0
- `doctor/doctor.sh` always exits 0 (non-zero would block session hooks)
- Rolling state save functions silently skip on write failure

## Atomic file writes

State files (`statusline-state.json`, `narrator-memory.json`, `settings.json`) are written atomically: write to a `.tmp` file, then `os.replace()` (Python) or `fs.renameSync()` (Node.js) over the target. This prevents corruption if the process is interrupted mid-write.

## Three-engine parity

Python and Node.js engines must stay in sync. Segment definitions, tier presets, schedule parsing, and rolling-state logic are conceptually identical across `engines/python-engine.py` and `engines/node-engine.js`. The Bash engine is intentionally minimal (peak hours, model, context, git only). When adding a feature, implement it in both Python and Node.js.

## Bilingual support

All user-facing text supports English and Hebrew. The narrator detects locale from `$LANG`/`$LC_ALL`/`$LC_MESSAGES` environment variables. Each scoring template in `narrator/scoring.py` carries a `text_he` field. Override with `STATUSLINE_NARRATOR_LANGS=en`, `=he`, or `=en,he`.

## Windows compatibility

- Reject Microsoft Store app-execution alias stubs (`WindowsApps/*.exe`) in `lib/resolve-runtime.sh`
- Probe portable install locations (`~/tools/python-*/`, `AppData/Local/Programs/Python/`)
- Convert MSYS paths via `cygpath -w` in hook scripts
- Force UTF-8 on stdout to prevent cp1252 encoding crashes

## ANSI color conventions

All three engines share the same ANSI color palette:

| Constant | Code | Usage |
|----------|------|-------|
| `RST` | `\033[0m` | Reset |
| `BOLD` | `\033[1m` | Emphasis |
| `DIM` | `\033[2m` | Secondary info |
| `GREEN` | `\033[32m` | Healthy / off-peak |
| `YELLOW` | `\033[33m` | Warning / peak |
| `RED` | `\033[31m` | Critical / error |
| `CYAN` | `\033[36m` | Info / model |
| `BG_GREEN` | `\033[38;5;255;48;5;28m` | Green badge |
| `BG_YELLOW` | `\033[38;5;16;48;5;220m` | Yellow badge |
| `BG_RED` | `\033[38;5;255;48;5;124m` | Red badge |

## Telemetry transparency

Telemetry is opt-out, not opt-in, but the payload is minimal and documented. Three privacy levels: `full` (default, includes sanitized doctor reports), `minimal` (summary only), `off` (nothing sent). All submissions are sanitized client-side before upload. See [telemetry](../features/telemetry.md).

## Spike guards

Rolling-rate calculations include sanity checks to prevent absurd values from corrupting the display:

- Minimum window span: 3 minutes (180 seconds) before trusting a rate
- Maximum plausible rate: $200/hr (anything higher is treated as a spike)
- Negative cost deltas return `None` (session reset or corruption)
- Cache delta requires at least 60 seconds of span
