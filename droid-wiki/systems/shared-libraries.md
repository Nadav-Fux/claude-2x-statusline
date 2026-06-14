# Shared libraries

## Purpose

The `lib/` directory contains building blocks shared across engines, narrator, installer, and doctor. Each library has parallel implementations where needed.

## Rolling state

60-minute ring buffer for burn rate and cache metrics. See [rolling metrics](../features/rolling-metrics.md) for full details.

| File | Language | Key functions |
|------|----------|---------------|
| `lib/rolling_state.py` | Python | `append_sample`, `rolling_rate`, `rolling_tokens_out`, `cache_delta` |
| `lib/rolling_state.js` | JavaScript | Same API, Node.js port |

Both write to `~/.claude/statusline-state.json` with atomic tmpfile + rename. Constants: `MAX_AGE_SECS = 3600`, `MIN_SPAN_SECS = 180`, `MAX_PLAUSIBLE_RATE = 200.0`.

## Workflow detection

`lib/workflows.py` reads Claude Code session and workflow state to display live subagent activity in the statusline.

### Session directory resolution

`find_session_dir()` derives the Claude Code session directory from hook stdin or session state. It tries:

1. `transcript_path` from stdin (the `.jsonl` file is a sibling of the session directory)
2. `session_id` + `cwd` from stdin (constructs `~/.claude/projects/<slug>/<sid>/`)
3. Session matching by `cwd` in `~/.claude/sessions/*.json` (prefers busy status, freshest `updatedAt`)

The `project_slug()` function mirrors Claude Code's project-dir naming: every non-alphanumeric character becomes `-`.

### Live workflow detection

`detect_live_workflows()` scans `session_dir/subagents/workflows/wf_*/` for in-flight workflows. For each, it counts agents and sums context tokens by reading the last usage block from each `agent-*.jsonl` file.

### Completed workflow aggregation

`read_completed_workflows()` aggregates `session_dir/workflows/wf_*.json` manifests for total tokens, run count, and agent count.

### Token usage reading

`read_agent_last_usage_tokens()` reads the last `"usage"` block from a JSONL transcript. It reads only the last 64KB of the file for efficiency, and handles truncated final writes by falling back to the second-to-last match.

## JSON manipulation

Cross-platform JSON merge/query helpers used by installers and doctor.

| File | Language | Backend |
|------|----------|---------|
| `lib/wire-json.sh` | Bash (dispatches to Python/Node/jq/PowerShell) | Auto-detected |
| `lib/Wire-Json.ps1` | PowerShell | Native PS objects |

`wire-json.sh` selects a backend on first use:

1. Python (via `resolve_runtime python`)
2. Node.js (via `resolve_runtime node`)
3. `jq` if available
4. PowerShell (`pwsh` or `powershell`)
5. `"none"` (operations become no-ops)

It provides functions for merging JSON objects, getting values by path, and setting values by path. The installer uses it to atomically update `settings.json` with the `statusLine` stanza.

## Key source files

| File | Lines | Purpose |
|------|-------|---------|
| `lib/rolling_state.py` | 157 | Python ring buffer |
| `lib/rolling_state.js` | 121 | Node.js ring buffer |
| `lib/workflows.py` | 193 | Session/workflow detection |
| `lib/wire-json.sh` | 365 | Cross-platform JSON merge/query |
| `lib/Wire-Json.ps1` | 213 | PowerShell JSON helpers |
| `lib/resolve-runtime.sh` | 85 | Runtime resolver (see [runtime resolution](runtime-resolution.md)) |

## Related pages

- [Rolling metrics](../features/rolling-metrics.md) — How rolling state feeds burn rate display
- [Runtime resolution](runtime-resolution.md) — How wire-json picks its backend
- [Engines](engines.md) — How engines consume these libraries
