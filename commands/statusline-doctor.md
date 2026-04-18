---
description: "Diagnose (and optionally fix) claude-2x-statusline problems"
allowed-tools: ["Bash"]
argument-hint: "[--fix] [--report] [--json]"
---

Run the claude-2x-statusline doctor.

The doctor checks for:
- `settings.json` has a `statusLine` stanza
- The stanza still points at cc-2x-statusline (not hijacked by another plugin)
- Windows-specific `PATH=… bash …` inline env (cmd.exe can't parse that)
- `statusline-config.json` presence and JSON validity
- Python / Node / bash runtime availability (including portable installs)
- Dry-run execution of the statusLine command (exit, line count, ms)
- Git origin points at `Nadav-Fux/claude-2x-statusline`
- Redundant per-tier slash commands

## Steps

1. Locate the doctor. Prefer the installed copy, fall back to the repo clone:
   - `~/.claude/cc-2x-statusline/doctor/doctor.sh`
   - `~/Github/claude-2x-statusline/doctor/doctor.sh` (fallback)
2. Run it with the user's arguments: `$ARGUMENTS`
   - No args → human-readable report
   - `--fix` → interactive fix prompts (requires TTY)
   - `--json` → machine-readable output
   - `--report` → send anonymous telemetry ping (IDs of failed checks only)
3. Show the output verbatim. Do not paraphrase.
4. If fixes were applied, remind the user to restart Claude Code.
