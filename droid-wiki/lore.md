# Lore

The development history of claude-2x-statusline, reconstructed from changelog entries, commit messages, and code annotations.

## Eras

### Initial build (pre-April 2026)

The plugin started as a simple statusline showing model info and context percentage. The earliest changelog entries (April 19, 2026) describe features that were already substantial, suggesting the initial development happened before the changelog system was introduced.

### Feature sprint: April 19, 2026

Six features shipped in a single day, each with its own changelog post:

- **Rolling-window metrics** — Burn rate switched from lifetime averages to a 10-minute rolling window with spike guards. This was prompted by absurd values like $800/hr appearing when a single expensive API call hit the window.
- **Narrator hook** — The two-layer insight system (rules engine + optional Haiku) was introduced. The rules engine was designed to be always-on and sub-50ms to avoid adding latency to prompt submission.
- **`/explain` command** — Segment-by-segment documentation was added to the doctor, making 18 segments self-documenting.
- **Bug fixes** — Saturday UTC peak was invisible to UTC+3 users on local Sunday (the cross-timezone spillover bug). Four separate numeric overflow bugs were fixed: $1.2M/hr, $55B projected cost, 29M% context, $813/hr burn rate.
- **Install telemetry** — Full transparency post documenting exact JSON payloads, what is and is not collected, and the opt-out mechanism.
- **Windows hardening** — Rejection of Microsoft Store stub binaries, cygpath conversion, UTF-8 forcing, and portable Python probing.

### Polish and expansion (April 20-21, 2026)

- **Bilingual narrator** (Apr 20) — Hebrew auto-detect from locale environment variables. All 18 insight templates received `text_he` translations. A structural test was added to enforce the bilingual contract on new templates.
- **Rich doctor diagnostics** (Apr 20) — 3-tier privacy system (full/minimal/off) with auto-upload of sanitized reports on failure. Stable per-machine diagnostic codes.
- **Plugin manifest** (Apr 20) — Bumped to v2.2.0, added hooks registration to `plugin.json` so marketplace installs auto-wire narrator.
- **Node parity** (Apr 21) — The Node.js narrator port was completed, giving Node-only users the same rules engine as Python users. Framed narrator notes as `//// ... ////` for visual distinction.

### Maintenance (May 2026)

- **Doctor narrator hook detection fix** (May 2) — Fixed a false positive on Windows/Git Bash where installed narrator hooks were reported as missing. The fix reads `settings.json` via stdin, walks the nested hook structure, and normalizes MSYS `/c/...` paths.
- **Route and metadata fixes** (May 1) — Restored the `/failures` route in the worker, expanded diagnostic code acceptance to 8-character hex, fixed path quoting in install.sh.

### VS Code extension (June 2026)

The VS Code extension was bumped to v0.2.0 (June 11, 2026) with packaging support for vsce. The extension reads live data from terminal statusline output files and renders battery bars in the editor status bar.

### Narrator Node parity completion (June 14, 2026)

The final commit completed Node narrator parity, added hooks fallback logic, synchronized versions across manifest files, and corrected documentation.

## Longest-standing features

- **Three-engine dispatch** (`statusline.sh` + `lib/resolve-runtime.sh`) — The Python/Node/Bash priority cascade has been the core architecture since the beginning.
- **Schedule system** — The remote-updatable `schedule.json` with auto-timezone conversion was one of the first features and remains the killer feature.
- **ANSI color palette** — The shared color constants (RST, BOLD, GREEN, BG_GREEN, etc.) appear identically in all three engines.

## Deprecated features

- **Peak-hour throttling** — Anthropic removed peak-hour throttling on 2026-05-06. The `peak_hours` segment is retained only for custom-tier users who still want a historical schedule cue. The schedule's `mode` was changed to `"normal"`.
- **`--report` doctor flag** — Retired to no-op when the auto-upload system replaced manual reporting. The flag still parses but does nothing.

## Major rewrites

- **Node narrator port** (Apr 21, 2026) — The narrator pipeline (engine, observations, scoring, memory, Haiku) was ported from Python to a single self-contained `narrator-node.js` module. This gave Node-only environments full narrator parity.
- **Rolling-window rewrite** (Apr 19, 2026) — Burn rate calculation was overhauled from lifetime session averages to a 10-minute rolling window. The old approach produced misleading numbers during bursty sessions.

## Notable incidents

- **Token-optimizer hijack** — The doctor's `restore-statusline` fix exists because another plugin was hijacking the `statusLine` stanza in `settings.json`. The doctor detects this and can restore the correct command.
- **Numeric spike bugs** — Four separate overflow bugs ($1.2M/hr, $55B, 29M%, $813/hr) were all caused by missing guards in rate calculations. They were fixed with the minimum-span and maximum-plausible-rate guards that now protect all rolling computations.
