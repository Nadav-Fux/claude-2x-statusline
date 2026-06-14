# Doctor diagnostics

## Purpose

The doctor is a diagnostic tool that checks installation health, explains statusline segments, and can automatically fix common problems. It runs as a standalone script invoked by the `/statusline-doctor` command or directly from the terminal.

## Modes

| Mode | Command | Output |
|------|---------|--------|
| Diagnose | `doctor.sh` | Human-readable report with pass/warn/fail counts |
| JSON | `doctor.sh --json` | Machine-readable JSON for tooling |
| Fix | `doctor.sh --fix` | Interactive prompts to apply fixes |
| Explain all | `doctor.sh --explain` | Table of all 18 segments with one-line descriptions |
| Explain one | `doctor.sh --explain <segment>` | Detailed explanation: format, computation, colors, hide conditions |
| Report | `doctor.sh --report` | Send anonymous telemetry ping (deprecated, now no-op) |

The doctor always exits 0. A non-zero exit would block Claude Code session hooks.

## Checks performed

The 1338-line `doctor/doctor.sh` checks:

1. `settings.json` has a `statusLine` stanza
2. The stanza points at cc-2x-statusline (not hijacked by another plugin, e.g. token-optimizer)
3. Windows-specific `PATH=... bash ...` inline env (cmd.exe cannot parse that)
4. `statusline-config.json` presence and JSON validity
5. Python / Node / bash runtime availability (including portable installs)
6. Dry-run execution of the statusLine command (exit code, line count, milliseconds)
7. Git origin points at `Nadav-Fux/claude-2x-statusline`
8. Narrator hooks wired in `settings.json` (handles nested Claude Code hook structure)
9. Redundant per-tier slash commands

## Auto-fix engine

`doctor/fixes.sh` applies one fix per invocation. Known fix hints:

| Hint | What it fixes |
|------|---------------|
| `add-statusline` | `settings.json` has no `statusLine` stanza |
| `restore-statusline` | statusLine was hijacked by another plugin |
| `wrap-command` | Windows: strip inline `VAR=val bash ...` and route through wrapper |
| `create-config` | `statusline-config.json` missing; write default |

All `settings.json` changes are atomic (write to `.tmp`, rename over target).

## Segment explanations

The doctor stores detailed segment explanations as a bash associative array (`SEG_DETAIL`). Each entry is a multi-line string covering:

- **What it shows** — plain-language description
- **How it's computed** — the calculation logic
- **Display values** — possible values and their meanings
- **Colors** — what each color means
- **When it hides** — conditions that suppress the segment

18 segments are documented: `peak_hours`, `model`, `context`, `vim_mode`, `agent`, `workflows`, `git_branch`, `git_dirty`, `cost`, `rate_limits`, `burn_rate`, `cache_hit`, `context_depletion`, `effort`, `env`, `usage_credits`, `auth_mode`, `sdk_meter`.

## Diagnostic code

Every doctor run (when telemetry is enabled) displays a stable per-machine hex code:

```
Diagnostic code: abc12345 (telemetry: full — see README to change privacy)
```

This code is derived from a one-way hash of hostname + username. It is stable across runs, allowing the maintainer to correlate reports from the same machine without identifying the user.

## Privacy levels

| Level | What gets sent | When |
|-------|----------------|------|
| `full` (default) | Summary + sanitized full report on failure | Automatic |
| `minimal` | Summary only | Automatic |
| `off` | Nothing | Never |

Full reports are sanitized client-side: home paths become `~/`, usernames become `<user>`, hostnames become `<host>`. Reports auto-delete after 30 days.

## Key source files

| File | Purpose |
|------|---------|
| `doctor/doctor.sh` | Main diagnostic engine (1338 lines) |
| `doctor/fixes.sh` | Automated fix application (215 lines) |
| `commands/statusline-doctor.md` | `/statusline-doctor` slash command definition |
| `commands/explain.md` | `/explain` slash command definition |
| `tests/test_doctor.py` | Doctor check tests |
| `tests/test_doctor_telemetry.py` | Doctor telemetry and diagnostic code tests |

## Related pages

- [Telemetry](telemetry.md) — How diagnostic data is collected and transmitted
- [Installer pipeline](../systems/installer.md) — What the doctor verifies
- [Configuration reference](../reference/configuration.md) — Config file that the doctor checks
