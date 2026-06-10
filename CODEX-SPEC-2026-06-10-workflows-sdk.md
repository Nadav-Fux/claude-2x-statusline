# Codex Implementation Spec — Workflows + SDK-Era Features
**Repo:** `C:\Users\nadav\github\claude-2x-statusline` (canonical — all edits here)  
**Date:** 2026-06-10  
**For:** OpenAI Codex CLI — zero external context; every fact needed is in this file.  
**Suggested implementation order:** Option 5 → 2 → 1 → 3 → 4 → 7 → 6

---

## 1. Mission and Context

**What the statusline is.** `claude-2x-statusline` is a Claude Code statusline plugin. Claude Code runs the statusline on every hook event (SessionStart, UserPromptSubmit, etc.) by piping a single JSON object to stdin. The engines parse that JSON plus cached local state and emit ANSI-colored text for the terminal. Three engines share the same feature set: Python (`engines/python-engine.py`) is primary, Node.js (`engines/node-engine.js`) is a full parity port, PowerShell (`statusline.ps1`) is best-effort for Windows. A pure-bash fallback (`engines/bash-engine.sh`) renders only peak/git fields and **must never receive token/cost parsing duties** — this is a deliberate precedent.

**The blindspot before this spec.** As of 2026-06-10, the statusline measures the *main interactive session* only. When the user runs Claude Code workflows (multi-agent orchestrations), dozens of subagents burn account quota in the background. Their token footprint is not shown anywhere in the statusline, the narrator, or the VS Code extension. A user can watch $0.80/hr on the main session meter while workflows are actually draining $25/hr from their 5-hour quota — the 5-hour bar is the only early warning, and only if they notice it ticking faster than the cost line suggests.

**The June 15, 2026 SDK-credit change.** Starting 2026-06-15, Claude Code invoked as `claude -p` (print/non-interactive), Agent SDK programs, GitHub Actions with Claude, and third-party apps authenticating with the subscription token will **stop drawing from the 5-hour/weekly quota windows** and will instead draw from a **separate monthly dollar credit** (Pro $20/mo, Max5x $100/mo, Max20x $200/mo). This credit must be explicitly claimed first ("No credit is granted until claimed"). Drain order: SDK credit first; if exhausted and overflow is enabled (default OFF), requests continue but cost money from the billing account; if overflow is OFF, requests hard-stop until the next billing cycle. Interactive Claude Code, claude.ai, and Cowork remain on subscription quota windows. The rate-limits bars will, after 06-15, measure *interactive-only* usage — this changes their labeling semantics and has narrator implications.

---

## 2. Ground Rules — Do Not Touch

- **NEVER edit `C:\Users\nadav\.claude\cc-2x-statusline\`** — this is a deployment copy, not the source repo.
- **NEVER touch `~/.claude/settings.json`** — this is the user's live Claude Code settings.
- **No PowerShell spawns per statusline tick.** The statusline runs every ~300 ms. Any new feature that reads a file or makes a network call must cache results (minimum 30s TTL for file reads, 60s for network). No `subprocess.run(["powershell", ...])` per tick.
- **Performance budget:** Each engine invocation must complete in < 300 ms wall time (excluding network fetches, which must be async/non-blocking or happen via a background cache-refresh that returns stale data if the refresh is in flight).
- **Line endings:** `.sh` files must use LF only (repo `.gitattributes` enforces `eol=lf` for `*.sh`). New shell files must be written with LF endings.
- **Engine parity matrix:**
  | Feature | Python | Node.js | PowerShell | Bash |
  |---------|--------|---------|------------|------|
  | All options (1–7) | Required | Required | Best-effort | Skip |
  Bash skips everything in this spec (precedent: tokens/cost fields not parsed by bash).
- **No paid commands in tests.** Never call `claude -p`, `claude --print`, or any API in tests. All tests must be local, using fixtures and mocks.
- **Branch:** Work on a feature branch named `feature/workflows-sdk-era`. Commit per option using conventional commits: `feat(option1):`, `fix(option5):`, etc.
- **Tests:** Run `pytest tests/` before and after each option. All existing tests must remain green. Add new tests per option as specified below.

---

## 3. Architecture Primer — Verified Anchors

All line numbers verified against the repo on 2026-06-10.

### 3.1 `engines/python-engine.py`

| What | Line(s) | Notes |
|------|---------|-------|
| TIER_PRESETS dict | 66–73 | `minimal`, `standard`, `full` each a list of segment names |
| DEFAULT_CONFIG | 75–85 | `schedule_url`, `schedule_cache_hours`, `tier`, `separator`, etc. |
| `load_config()` | 188–198 | Reads `~/.claude/statusline-config.json`; merges over DEFAULT_CONFIG |
| `get_enabled_segments(config, schedule)` | 218–239 | Respects `custom` tier + remote feature flags |
| `read_stdin()` | 420–430 | Returns dict or `{}` |
| `seg_banner(ctx)` | 502–529 | Reads `schedule["banner"]` + `schedule["release"]` |
| `seg_peak_hours(ctx)` | 532–651 | Sets `ctx["is_peak"]`, `ctx["peak_start_local"]`, etc. |
| `seg_promo_2x` alias | 651 | `seg_promo_2x = seg_peak_hours` (backward compat) |
| `seg_model(ctx)` | 654–659 | `ctx["stdin"]["model"]["display_name"]` |
| `seg_context(ctx)` | 669–685 | input+cache_creation+cache_read / context_window_size |
| `seg_cost(ctx)` | 733–737 | `ctx["stdin"]["cost"]["total_cost_usd"]` |
| `seg_rate_limits(ctx)` | 918–987 | Fetches `https://api.anthropic.com/api/oauth/usage`, caches 60s to `~/.claude/statusline-usage-cache.json`; stores `ctx["usage_data"]` |
| `_get_oauth_token()` | 990–1019 | Reads env var, .credentials.json, macOS keychain |
| `build_timeline(ctx)` | 1026–1062 | Full-tier line 2 |
| `build_rate_limits_line(ctx)` | 1065–1099 | Full/standard tier line 3; reads `ctx["usage_data"]`; peak lightning tag at :1085 |
| `build_metrics_line(ctx)` | 1118–1138 | Full-tier line 4; includes `"peak = limits drain faster"` note at :1132 |
| SEGMENTS dict | 1144–1165 | Registry of all `seg_*` functions |
| `main()` | 1171–1278 | Orchestration; full-tier extra lines at :1258–1278 |

**stdin fields currently read (verified):**
- `model.display_name` (:655)
- `context_window.context_window_size` (:671)
- `context_window.current_usage.{input_tokens, cache_creation_input_tokens, cache_read_input_tokens}` (:675–678)
- `cost.total_cost_usd` (:734, :804)
- `cost.total_duration_ms` (:741, :805)
- `cost.total_lines_added/removed` (:749–750)
- `cwd` (:757)
- `vim.mode` (:893)
- `agent.name` (:905–907)
- `worktree.name` (:910–912)

**stdin fields present in payload but NOT read by engine:** `session_id`, `transcript_path`, `version`, `workspace`, `output_style`, `exceeds_200k_tokens`, `rate_limits.five_hour`, `rate_limits.seven_day`.

### 3.2 `engines/node-engine.js`

| What | Line(s) | Notes |
|------|---------|-------|
| TIER_PRESETS | 27–31 | Slightly different from Python: `minimal` includes `effort`; `standard`/`full` include `effort` but not `vim_mode` in minimal |
| DEFAULT_CONFIG | 33–38 | Same keys |
| SEGMENTS object | 248–421 | All segments as methods |
| `SEGMENTS.promo_2x` alias | 422 | `= SEGMENTS.peak_hours` |
| `buildRateLimitsLine(ctx)` | 446–457 | peak tag at :451; `ctx.usageData` |
| `buildMetricsLine(ctx)` | 459–468 | `"peak = limits drain faster"` at :465 |
| `main()` | 507–562 | Same structure |

### 3.3 `statusline.ps1`

Segment registry at lines 449–453:
```powershell
$segFns = @{
    banner='Seg_banner'; peak_hours='Seg_peak_hours'; promo_2x='Seg_peak_hours'
    model='Seg_model'; context='Seg_context'; git_branch='Seg_git_branch'; git_dirty='Seg_git_dirty'
    cost='Seg_cost'; duration='Seg_duration'; rate_limits='Seg_rate_limits'; effort='Seg_effort'; env='Seg_env'
}
```

### 3.4 `lib/rolling_state.py`

- State file: `~/.claude/statusline-state.json`
- Schema: `{"samples": [{"t": float, "cost": float, "tokens_in": int, "tokens_out": int, "cache_read": int, "cache_creation": int}]}`
- Atomic write: write to `.tmp` then `os.replace()` (:30–38)
- GLOBAL file (not per-session) — concurrent sessions interleave; guards at :105–107 drop negative cost deltas; spike guard at :115–117 drops rates > $200/hr
- `append_sample()` at :47; `rolling_rate()` at :83; `rolling_tokens_out()` at :120; `cache_delta()` at :142

### 3.5 `narrator/observations.py`

- `Observation` dataclass: :27–67
- `build(memory)` entry: :181
- `_apply_stdin(obs, data)`: :269–292
- **KNOWN BUG at :290–292:** reads `rate_limits.pct_5h` and `rate_limits.pct_7d` from stdin — these fields DO NOT EXIST in Claude Code's hook payload. The correct field names in the payload are `rate_limits.five_hour` (object with `utilization` key) and `rate_limits.seven_day`. The result: `obs.rate_limit_5h_pct` and `obs.rate_limit_7d_pct` are always 0.0, causing the narrator to emit broken messages like "5-hour budget ends in ~0m".
- Fallback state read: :205–210 (rolling_state.json), :124–137 (_load_statusline_state)

### 3.6 `narrator/scoring.py`

- `off_peak_wide_open` template: :264–276 (recommends heavy refactors during off-peak — now obsolete since peak throttling was removed 2026-05-06)
- `subagent_suggestion` template: :391–407
- `peak_rate_ok` template: :244–262

### 3.7 `narrator/narrator-node.js`

- `buildObservation(memory)`: :51–115 — same stdin parsing bug pattern (reads stdinData fields directly but not from oauth usage cache)
- `buildInsights(obs, memory)`: :133–213
- `off_peak_wide_open` at :188–191
- `peak_rate_ok` at :185–187

### 3.8 `doctor/doctor.sh`

- `SEG_DETAIL` array: :23–329 (detailed per-segment docs)
- `SEG_ONELINER` array: :332–351 (one-line purposes for table)
- Segment list in explain loop: :362–365

### 3.9 `schedule.json` (repo root)

Current content (must be updated by Option 2):
```json
{
  "v": 4,
  "mode": "peak_hours",
  "default_tier": "full",
  "peak": { "enabled": true, "tz": "UTC", "days": [1,2,3,4,5], "start": 13, "end": 19, ... },
  "labels": { "five_hour": "5h", "weekly": "weekly", "five_hour_note": "", "weekly_note": "" },
  "banner": { "text": "", "expires": "", "color": "yellow" },
  "release": { "latest_version": "2.2.0", ... },
  "features": { "show_peak_segment": true, "show_rate_limits": true, "show_timeline": true }
}
```

The banner schema supports: `text` (string), `expires` (YYYY-MM-DD), `color` ("yellow"|"red"|"green"|"blue"|"gray"). The expiry check at `seg_banner` line :519: `ctx["local_time"].date() > exp_date`. This means a banner with `"expires": "2026-07-13"` shows through and including July 13.

### 3.10 `vscode/extension.ts`

- `CONTEXT_PATH` at :58: `path.join(os.tmpdir(), 'claude', 'statusline-context.json')`
- The PS1 engine writes this file. Python/Node engines do not currently write it.
- On Windows: `%TEMP%\claude\statusline-context.json`

---

## 4. Data Contracts

### 4.1 Completed Workflow Manifest — `wf_*.json`

Location: `<session-dir>/workflows/wf_*.json` where `<session-dir>` is derived from:
1. `stdin.transcript_path` with `.jsonl` stripped (e.g. `~/.claude/projects/-Users-nadav-github-repo/<session-id>`)
2. OR `~/.claude/projects/<proj-slug>/<session-id>/`
3. Fallback: `~/.claude/sessions/<pid>.json` contains `{pid, sessionId, cwd, status, updatedAt}` (updated live)

**Synthetic example** (write to `tests/fixtures/wf_sample.json`):
```json
{
  "runId": "wf_abc123",
  "taskId": "task_xyz789",
  "agentCount": 3,
  "durationMs": 42000,
  "status": "completed",
  "totalTokens": 287450,
  "totalToolCalls": 18,
  "workflowName": "code-review-workflow",
  "scriptPath": "/project/.claude/workflows/review.js",
  "defaultModel": "claude-sonnet-4-5",
  "startTime": "2026-06-10T08:00:00.000Z",
  "phases": [{"name": "analyze", "agentCount": 2}, {"name": "report", "agentCount": 1}],
  "summary": "Reviewed 3 files, found 2 issues",
  "result": "completed",
  "logs": [],
  "workflowProgress": [
    {"type": "workflow_phase", "index": 0, "title": "analyze"},
    {
      "type": "workflow_agent",
      "index": 0,
      "label": "File Analyzer",
      "phaseIndex": 0,
      "phaseTitle": "analyze",
      "agentId": "agent-001",
      "model": "claude-sonnet-4-5",
      "state": "done",
      "startedAt": "2026-06-10T08:00:01.000Z",
      "queuedAt": "2026-06-10T08:00:00.500Z",
      "attempt": 1,
      "lastToolName": "read_file",
      "lastToolSummary": "Read main.py",
      "promptPreview": "Review main.py for issues...",
      "tokens": 85000,
      "durationMs": 12000
    },
    {
      "type": "workflow_agent",
      "index": 1,
      "label": "Test Analyzer",
      "phaseIndex": 0,
      "phaseTitle": "analyze",
      "agentId": "agent-002",
      "model": "claude-sonnet-4-5",
      "state": "done",
      "startedAt": "2026-06-10T08:00:01.200Z",
      "queuedAt": "2026-06-10T08:00:00.600Z",
      "attempt": 1,
      "lastToolName": "bash",
      "lastToolSummary": "Run tests",
      "promptPreview": "Run and analyze tests...",
      "tokens": 117450,
      "durationMs": 18000
    },
    {
      "type": "workflow_agent",
      "index": 2,
      "label": "Report Writer",
      "phaseIndex": 1,
      "phaseTitle": "report",
      "agentId": "agent-003",
      "model": "claude-sonnet-4-5",
      "state": "done",
      "startedAt": "2026-06-10T08:00:20.000Z",
      "queuedAt": "2026-06-10T08:00:19.500Z",
      "attempt": 1,
      "lastToolName": null,
      "lastToolSummary": null,
      "promptPreview": "Synthesize findings...",
      "tokens": 85000,
      "durationMs": 10000
    }
  ]
}
```

Key facts:
- `totalTokens` is the harness-reported total. The per-agent `tokens` field equals the **final context size** (input+cache_creation+cache_read of that agent's last assistant message) — verified ±2 tokens.
- The file does NOT exist while the workflow is running.

### 4.2 Live Workflow Files — `subagents/workflows/wf_X/agent-*.jsonl`

If `<session-dir>/subagents/workflows/wf_X/` exists but `<session-dir>/workflows/wf_X.json` does NOT, the workflow is in flight.

Agent turn file: `<session-dir>/subagents/workflows/wf_X/agent-<id>.jsonl`
- Each line is a JSON object
- `type: "assistant"` lines carry `message.usage`:
  ```json
  {"type": "assistant", "message": {"usage": {"input_tokens": 45000, "cache_creation_input_tokens": 20000, "cache_read_input_tokens": 70826, "output_tokens": 1234}}, "isSidechain": true}
  ```
- `type: "user"`, `type: "attachment"` lines never carry usage
- Plain (non-workflow) Agent-tool subagents live at `<session-dir>/subagents/agent-*.jsonl`
- Meta file: `agent-*.meta.json` `{"agentType": "workflow-subagent" | "general-purpose", "description": ...}`

**Synthetic example** (write to `tests/fixtures/agent_sample.jsonl`):
```jsonl
{"type": "user", "message": {"content": "Review main.py for issues"}, "isSidechain": true}
{"type": "assistant", "message": {"content": "...", "usage": {"input_tokens": 10000, "cache_creation_input_tokens": 5000, "cache_read_input_tokens": 20000, "output_tokens": 500}}, "isSidechain": true}
{"type": "user", "message": {"content": "Now check tests"}, "isSidechain": true}
{"type": "assistant", "message": {"content": "...", "usage": {"input_tokens": 12000, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 45000, "output_tokens": 800}}, "isSidechain": true}
```

> **THE FORMULA — READ THIS BEFORE WRITING ANY TOKEN COUNTING CODE**
>
> ```
> ⚠️  WARNING: NEVER SUM USAGE BLOCKS ACROSS ALL LINES IN AN AGENT FILE ⚠️
>
> cache_read_input_tokens is RE-BILLED on EVERY TURN. If you sum all
> "usage" objects in the file you will multiply the cache cost by the
> number of turns.
>
> Real measured example:
>   Summing 63 usage blocks  →  5,444,721 tokens  (WRONG)
>   Using only the LAST block →    135,826 tokens  (CORRECT)
>
> The ONLY correct formula for current/final agent context footprint:
>   tokens = last_usage.input_tokens
>           + last_usage.cache_creation_input_tokens
>           + last_usage.cache_read_input_tokens
>
> Do NOT include output_tokens in the footprint — they are output, not context.
>
> Live read strategy:
>   1. Read the last ~64 KB of the agent file (tail)
>   2. Regex-find all complete "usage":{...} blocks
>   3. Take the LAST match only
>   4. Guard against a partial trailing line (writer appends concurrently):
>      a JSON line is valid only if it ends with a '}' and the outer JSON is parseable
> ```

### 4.3 Usage Cache — `~/.claude/statusline-usage-cache.json`

Written by `seg_rate_limits()` in python-engine.py (:918–987) and node-engine.js (:356–384).

Example structure (actual API response):
```json
{
  "five_hour": {
    "utilization": 23.5,
    "resets_at": "2026-06-10T14:00:00Z"
  },
  "seven_day": {
    "utilization": 41.0,
    "resets_at": "2026-06-14T00:00:00Z"
  },
  "seven_day_sonnet": {
    "utilization": 15.0,
    "resets_at": "2026-06-14T00:00:00Z"
  },
  "extra_usage": {
    "enabled": false,
    "consumed_usd": 0.0,
    "limit_usd": null
  }
}
```

The `extra_usage` block is the post-06-15 overflow/SDK-credit channel (currently `enabled: false` for most users).

### 4.4 Narrator Bug Context

`narrator/observations.py` `_apply_stdin()` at line 290–292:
```python
rate_limits = data.get("rate_limits", {})
obs.rate_limit_5h_pct = float(rate_limits.get("pct_5h", 0.0))   # ← key doesn't exist in payload
obs.rate_limit_7d_pct = float(rate_limits.get("pct_7d", 0.0))   # ← key doesn't exist in payload
```

The actual Claude Code hook payload has `rate_limits.five_hour.utilization` (if populated at all) — but the engine's real usage data comes from the oauth/usage API cached in `statusline-usage-cache.json`. The fix for Option 5 is to populate `rate_limit_5h_pct` and `rate_limit_7d_pct` from that cache file (same source `seg_rate_limits()` uses), not from stdin.

### 4.5 SDK Ledger File — `~/.claude/statusline-sdk-ledger.json`

New file introduced by Option 7:
```json
{
  "schema_version": 1,
  "billing_cycle_day": 1,
  "plan_ceiling_usd": 20.0,
  "entries": [
    {
      "session_id": "abc123",
      "cwd": "/project",
      "start_time": "2026-06-10T08:00:00Z",
      "end_time": "2026-06-10T08:15:00Z",
      "cost_usd": 0.45,
      "model": "claude-sonnet-4-5",
      "kind": "print"
    }
  ],
  "month_total_usd": 0.45,
  "last_updated": "2026-06-10T08:15:00Z"
}
```

---

## 5. Option Specifications

---

### Option 5 — Peak-Era Cleanup + Narrator Bug Fix

**Priority: implement first.** This is pure cleanup with one critical bug fix; it unblocks Options 3 and 6.

**Context:** On 2026-05-06, Anthropic permanently removed peak-hour throttling. The 5-hour quota still exists but no longer drains faster during business hours. The peak segment machinery (schedule check, timezone conversion, lightning bolts, timeline bar colors) is now misleading. Simultaneously, the narrator's rate-limit templates have been broken since day one because the stdin parsing reads wrong field names.

#### 5.1 Files to touch

| File | Change |
|------|--------|
| `engines/python-engine.py` | Remove `peak_hours` and `promo_2x` from TIER_PRESETS (keep function + registry for custom-tier); remove lightning tag (`:983`) and peak note (`:1132`) |
| `engines/node-engine.js` | Same: remove from TIER_PRESETS (:27–31), remove peak tag (:451, :465) |
| `statusline.ps1` | Remove `peak_hours`/`promo_2x` from segment registry (keep `Seg_peak_hours` function for custom-tier users) |
| `schedule.json` | Set `"mode": "normal"` — this causes `seg_peak_hours` to return `""` (already handled at python :541, node :266) |
| `narrator/observations.py` | Fix `_apply_stdin()` :290–292; add `_load_usage_cache()` helper |
| `narrator/narrator-node.js` | Same fix in `buildObservation()` |
| `narrator/scoring.py` | Retire `off_peak_wide_open` template; update `peak_rate_ok` template |
| `narrator/narrator-node.js` | Retire `off_peak_wide_open` at :188–191; update `peak_rate_ok` |
| `doctor/doctor.sh` | Update `SEG_DETAIL[peak_hours]` and `SEG_ONELINER[peak_hours]` to say "historical / custom-tier only" |
| `README.md` | Update rate-limits section; remove peak/off-peak timing language |

#### 5.2 Algorithm — Python-engine TIER_PRESETS

**Before:**
```python
"minimal": ["peak_hours", "model", "context", "git_branch", "git_dirty", "rate_limits", "env"],
"standard": ["peak_hours", "model", "context", "vim_mode", "agent", "git_branch", "git_dirty", "cost", "effort", "env"],
"full": ["peak_hours", "model", "context", "vim_mode", "agent", "git_branch", "git_dirty", "cost", "effort", "env"],
```

**After:**
```python
"minimal": ["model", "context", "git_branch", "git_dirty", "rate_limits", "env"],
"standard": ["model", "context", "vim_mode", "agent", "git_branch", "git_dirty", "cost", "effort", "env"],
"full": ["model", "context", "vim_mode", "agent", "git_branch", "git_dirty", "cost", "effort", "env"],
```

`seg_peak_hours` function remains in `SEGMENTS` under both `"peak_hours"` and `"promo_2x"` keys — custom-tier users who list `"peak_hours": true` in their config still get it.

The `is_peak` / `is_offpeak` ctx flags also remain (they default to `False`/`True`), so any code that reads `ctx.get("is_peak")` is safe.

#### 5.3 Algorithm — Remove lightning tags

**Python** `build_rate_limits_line()` (line 1085):
```python
# REMOVE THIS LINE:
peak_tag = f" {YELLOW}⚡ peak{RST}" if ctx.get("is_peak") else f" {GREEN}✓{RST}"
# REPLACE WITH:
peak_tag = ""
```

**Python** `build_metrics_line()` (line 1131–1132):
```python
# REMOVE:
if ctx.get("is_peak"):
    parts.append(f"{YELLOW}⚡ peak = limits drain faster{RST}")
```

**Node.js** `buildRateLimitsLine()` (line 451): Remove `ctx.isPeak` ternary for peakTag.
**Node.js** `buildMetricsLine()` (line 465): Remove the `ctx.isPeak` check and lightning line.

Also remove the `peak_tag` variable from `seg_rate_limits()` line :982–986 (Python) and the equivalent in Node.

#### 5.4 Algorithm — Narrator bug fix

Add a new helper to `narrator/observations.py` after the existing `_load_statusline_state()`:

```python
def _load_usage_cache() -> dict:
    """Load the rate-limits usage cache written by seg_rate_limits()."""
    cache_path = Path.home() / ".claude" / "statusline-usage-cache.json"
    try:
        age = time.time() - cache_path.stat().st_mtime
        if age > 300:  # 5-minute staleness tolerance for narrator
            return {}
        return json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
```

Then in `_apply_stdin()` at the bug location (:290–292), replace with:

```python
# DO NOT read rate_limits from stdin — those fields never exist in the hook payload.
# Instead, populate from the oauth/usage cache that seg_rate_limits() maintains.
# (Populated below in build() after _apply_stdin returns.)
obs.rate_limit_5h_pct = 0.0
obs.rate_limit_7d_pct = 0.0
```

Then in `build()`, after the `_apply_stdin(obs, stdin_data)` call, add:

```python
# Populate rate-limit percentages from oauth/usage cache (correct source)
usage_cache = _load_usage_cache()
if usage_cache:
    obs.rate_limit_5h_pct = float(usage_cache.get("five_hour", {}).get("utilization", 0.0))
    obs.rate_limit_7d_pct = float(usage_cache.get("seven_day", {}).get("utilization", 0.0))
```

Apply the same fix to `narrator-node.js` `buildObservation()`: after stdin parsing, add a `try/catch` block that reads `~/.claude/statusline-usage-cache.json` and populates `obs.rate_limit_5h_pct` and `obs.rate_limit_7d_pct`.

#### 5.5 Algorithm — Retire off_peak_wide_open

In `narrator/scoring.py`, the `off_peak_wide_open` block at :264–276 should be **removed entirely** (not commented out). The condition was `not obs.is_peak and max_rl < 50` — since `is_peak` will always be `False` after the fix, this template would fire constantly if left in.

In `narrator/narrator-node.js`, remove the `off_peak_wide_open` block at :188–191 identically.

The `peak_rate_ok` template can remain as-is for custom-tier users who still use the peak segment. It fires only when `obs.is_peak is True`, which is only possible if the user has `peak_hours` in their custom tier config and the schedule mode is not `normal`.

#### 5.6 schedule.json — Switch mode to normal

```json
{
  "v": 5,
  "updated": "2026-06-10",
  "mode": "normal",
  ...
}
```

Keep the `peak` block intact (for custom-tier users who pull the schedule for their timezone config). Change only `"mode"` from `"peak_hours"` to `"normal"`.

Also update the `"note"` in the peak block: `"Peak hours removed 2026-05-06. This block retained for custom-tier timezone config only."`.

#### 5.7 Acceptance Criteria — Option 5

1. `pytest tests/test_peak_hours.py` — all existing tests pass (they test the peak-hours math logic, not whether the segment is in presets).
2. `pytest tests/test_narrator_observations.py` — all existing tests pass.
3. New test `tests/test_narrator_rate_limits.py`:
   - Write a fake `statusline-usage-cache.json` with `five_hour.utilization = 72.5`
   - Call `observations.build({"current": {}})` with a monkeypatched home dir
   - Assert `obs.rate_limit_5h_pct == 72.5`
   - Assert it does NOT read from stdin's `rate_limits` key
4. `echo '{"cost":{"total_cost_usd":1.0},"context_window":{"context_window_size":200000,"current_usage":{"input_tokens":50000,"cache_creation_input_tokens":0,"cache_read_input_tokens":0}}}' | python engines/python-engine.py` — output must NOT contain `⚡` or `peak = limits drain faster`
5. Same stdin piped to `node engines/node-engine.js` — same assertion.
6. Doctor `doctor.sh --explain peak_hours` must print "historical / custom-tier only" (or equivalent updated text).

---

### Option 2 — schedule.json Banners

**Context:** Two important announcements need to reach users via the existing remote-controlled banner system. The `seg_banner()` function reads `schedule.banner.{text, expires, color}` from the cached schedule. The function already handles expiry checking (line :519). No engine code changes needed — this is purely a `schedule.json` edit.

#### 2.1 Files to touch

- `schedule.json` (repo root only — this is what the remote URL serves)

#### 2.2 Banner schema

The current schema supports a single banner. To show TWO banners simultaneously, the banner text must concatenate both into one string with a separator, or the schedule schema must be extended. Check: `seg_banner` at :502–529 reads `schedule.get("banner", {})` as a single dict. Node reads `ctx.schedule.banner` as a single object.

**IMPLEMENTER NOTE:** The current schema supports only ONE banner object. To avoid a breaking schema change, either: (a) concatenate the two messages into one banner text with `|` separator, OR (b) extend the schema to support `banners: []` array and update both engines to handle it. Option (b) is cleaner but requires engine changes. This spec recommends option (b) since it adds a single 5-line loop in each engine with a fallback to the old single-banner path for backward compat.

#### 2.3 Extended banner schema (option b — recommended)

Add `banners` array support to `seg_banner()` in Python:

```python
def seg_banner(ctx):
    schedule = ctx["schedule"]
    badges = []
    release_notice = build_release_notice(schedule)
    if release_notice:
        badges.append(release_notice)

    # New: support banners array (multiple banners)
    banner_list = schedule.get("banners", [])
    if not banner_list:
        # Backward compat: single banner object
        b = schedule.get("banner", {})
        if b.get("text"):
            banner_list = [b]

    color_map = {"yellow": BG_YELLOW, "red": BG_RED, "green": BG_GREEN, "blue": BG_BLUE, "gray": BG_GRAY}
    for banner in banner_list:
        text = banner.get("text", "")
        if not text:
            continue
        expires = banner.get("expires", "")
        if expires:
            try:
                exp_date = datetime.strptime(expires, "%Y-%m-%d").date()
                if ctx["local_time"].date() > exp_date:
                    continue
            except Exception:
                pass
        bg = color_map.get(banner.get("color", "yellow"), BG_YELLOW)
        badges.append(f"{bg} {text} {RST}")

    return " ".join(badges)
```

Apply identically to Node.js `SEGMENTS.banner()` at :249–262.

#### 2.4 schedule.json update

```json
{
  "v": 5,
  "updated": "2026-06-10",
  "mode": "normal",
  "banner": { "text": "", "expires": "", "color": "yellow" },
  "banners": [
    {
      "text": "SDK credit cutover Jun 15 — claim it or claude -p stops",
      "expires": "2026-06-15",
      "color": "red"
    },
    {
      "text": "Weekly +50% promo ends Jul 13",
      "expires": "2026-07-13",
      "color": "yellow"
    }
  ],
  ...
}
```

**Escalation for the +50% promo:** If the schedule schema supports a `color_final_week` field, switch to `"red"` in the final 7 days. This requires engine logic: `if (days_until_expiry <= 7) use color_final_week`. This is optional polish — implement only if time allows.

#### 2.5 Acceptance Criteria — Option 2

1. Both engines render the red SDK banner when today <= 2026-06-15.
2. Both engines render the amber weekly banner when today <= 2026-07-13.
3. After 2026-06-15, only the weekly banner shows.
4. After 2026-07-13, no banner shows.
5. Old single-banner format still works (backward compat test with `{"banner": {"text": "test", "color": "green"}}`).
6. New test `tests/test_banners.py`:
   - Inject a schedule with `banners: [...]` and various `local_time` dates
   - Assert correct banners render or hide per date

---

### Option 1 — seg_workflows: Workflow Token Visibility

**This is the most complex option. Implement after Options 5 and 2.**

#### 1.1 Overview

Show two states:
- **Live:** A workflow is running → show agent count + sum of current context footprints
- **Idle:** No workflow running → show session cumulative from completed wf_*.json manifests

Example outputs:
- Live: `⚙ 4 agents ctx Σ 312K`
- Idle: `wf: agents ctx Σ 1.32M · 8 runs`
- If no workflows at all: return `""` (segment hidden)

The label **"agents ctx Σ"** (not "total tokens") is deliberate — see Section 4 formula warning. These are context footprint sizes, not cumulative API billing.

#### 1.2 Session Directory Discovery

```python
def _find_session_dir(stdin_data: dict) -> Path | None:
    """Derive the session transcript directory from stdin or fallback."""
    # Method 1: transcript_path (most reliable)
    tp = stdin_data.get("transcript_path", "")
    if tp:
        p = Path(tp)
        if p.suffix == ".jsonl":
            p = p.parent
        if p.is_dir():
            return p

    # Method 2: session_id + cwd-based slug
    session_id = stdin_data.get("session_id", "")
    cwd = stdin_data.get("cwd", "")
    if session_id and cwd:
        slug = cwd.replace("/", "-").replace("\\", "-").replace(":", "").lstrip("-")
        candidate = Path.home() / ".claude" / "projects" / slug / session_id
        if candidate.is_dir():
            return candidate

    # Method 3: scan ~/.claude/sessions/*.json for pid match
    sessions_dir = Path.home() / ".claude" / "sessions"
    if sessions_dir.is_dir():
        pid = str(os.getpid())
        for f in sessions_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if str(data.get("pid", "")) == pid or f.stem == pid:
                    sid = data.get("sessionId", "")
                    cwd2 = data.get("cwd", "")
                    if sid and cwd2:
                        slug = cwd2.replace("/", "-").replace("\\", "-").replace(":", "").lstrip("-")
                        candidate = Path.home() / ".claude" / "projects" / slug / sid
                        if candidate.is_dir():
                            return candidate
            except Exception:
                pass
    return None
```

#### 1.3 Cache Strategy

The segment must run every ~300ms but file I/O is expensive. Use a module-level dict as in-process cache keyed by `(session_dir_path, mtime_of_workflows_dir, count_of_wf_json_files)`. If the key is unchanged from the last call, return cached result immediately.

```python
_WF_CACHE: dict = {}   # module-level

def _wf_cache_key(session_dir: Path) -> tuple:
    wf_dir = session_dir / "workflows"
    live_dir = session_dir / "subagents" / "workflows"
    try:
        mtime1 = wf_dir.stat().st_mtime if wf_dir.is_dir() else 0
        count1 = sum(1 for _ in wf_dir.glob("wf_*.json")) if wf_dir.is_dir() else 0
    except Exception:
        mtime1 = count1 = 0
    try:
        mtime2 = live_dir.stat().st_mtime if live_dir.is_dir() else 0
        count2 = sum(1 for _ in live_dir.glob("wf_*/")) if live_dir.is_dir() else 0
    except Exception:
        mtime2 = count2 = 0
    return (str(session_dir), mtime1, count1, mtime2, count2)
```

#### 1.4 Live Workflow Detection

```python
def _detect_live_workflows(session_dir: Path) -> list[dict]:
    """Return list of in-flight workflow dicts with agent_count and tokens."""
    live_base = session_dir / "subagents" / "workflows"
    completed_dir = session_dir / "workflows"
    if not live_base.is_dir():
        return []

    results = []
    for wf_subdir in live_base.iterdir():
        if not wf_subdir.is_dir() or not wf_subdir.name.startswith("wf_"):
            continue
        # Only live if no completed manifest exists
        manifest_path = completed_dir / f"{wf_subdir.name}.json"
        if manifest_path.exists():
            continue
        # Count agents and sum context tokens
        agent_count = 0
        total_tokens = 0
        for jsonl_file in wf_subdir.glob("agent-*.jsonl"):
            if jsonl_file.name.endswith(".meta.json"):
                continue
            agent_count += 1
            tokens = _read_agent_last_usage_tokens(jsonl_file)
            total_tokens += tokens
        if agent_count > 0:
            results.append({"name": wf_subdir.name, "agents": agent_count, "tokens": total_tokens})
    return results
```

#### 1.5 Reading Agent Last Usage Tokens (THE CRITICAL FUNCTION)

> **NEVER sum all usage blocks. Always use only the LAST complete usage block.**

```python
import re

_USAGE_PATTERN = re.compile(
    r'"usage"\s*:\s*\{\s*"input_tokens"\s*:\s*(\d+)\s*,\s*'
    r'"cache_creation_input_tokens"\s*:\s*(\d+)\s*,\s*'
    r'"cache_read_input_tokens"\s*:\s*(\d+)\s*,\s*'
    r'"output_tokens"\s*:\s*(\d+)'
)

def _read_agent_last_usage_tokens(jsonl_path: Path) -> int:
    """Read the last ~64KB of an agent jsonl file and return the last
    complete usage block's input+cache_creation+cache_read total.
    
    WARNING: Do NOT sum across lines. cache_read is re-billed each turn.
    Only the LAST usage block reflects the true current context footprint.
    """
    try:
        size = jsonl_path.stat().st_size
        chunk_size = min(65536, size)  # 64KB tail
        with open(jsonl_path, "rb") as f:
            if size > chunk_size:
                f.seek(-chunk_size, 2)  # seek from end
            tail_bytes = f.read()
        tail_text = tail_bytes.decode("utf-8", errors="replace")
        
        matches = list(_USAGE_PATTERN.finditer(tail_text))
        if not matches:
            return 0
        
        last = matches[-1]
        # Guard: ensure this isn't a truncated line (writer appending concurrently)
        # Check that the match is not near the very end of an incomplete line
        after_match = tail_text[last.end():last.end() + 20]
        if after_match and not any(c in after_match for c in ('}', '\n')):
            # Possibly truncated — use second-to-last if available
            if len(matches) >= 2:
                last = matches[-2]
            else:
                return 0
        
        inp = int(last.group(1))
        cache_create = int(last.group(2))
        cache_read = int(last.group(3))
        # output_tokens (group 4) deliberately excluded — not context footprint
        return inp + cache_create + cache_read
    except Exception:
        return 0
```

**Note on Windows file sharing:** Windows allows concurrent reads from files opened with `FILE_SHARE_READ` (Python's default open mode). This is safe.

#### 1.6 Completed Workflow Aggregation

```python
def _read_completed_workflows(session_dir: Path) -> dict:
    """Return aggregate stats from all wf_*.json completed manifests."""
    wf_dir = session_dir / "workflows"
    if not wf_dir.is_dir():
        return {"total_tokens": 0, "run_count": 0, "agent_count": 0}
    
    total_tokens = 0
    run_count = 0
    agent_count = 0
    for wf_file in wf_dir.glob("wf_*.json"):
        try:
            data = json.loads(wf_file.read_text(encoding="utf-8"))
            if data.get("status") != "completed":
                continue
            total_tokens += int(data.get("totalTokens", 0))
            run_count += 1
            agent_count += int(data.get("agentCount", 0))
        except Exception:
            pass
    return {"total_tokens": total_tokens, "run_count": run_count, "agent_count": agent_count}
```

#### 1.7 Main Segment Function

```python
def seg_workflows(ctx):
    """Show workflow agent token footprint: live count or session cumulative."""
    stdin_data = ctx.get("stdin", {})
    session_dir = _find_session_dir(stdin_data)
    if not session_dir:
        return ""
    
    cache_key = _wf_cache_key(session_dir)
    if _WF_CACHE.get("key") == cache_key:
        return _WF_CACHE.get("result", "")
    
    # Check for live workflows
    live = _detect_live_workflows(session_dir)
    if live:
        total_agents = sum(w["agents"] for w in live)
        total_tokens = sum(w["tokens"] for w in live)
        result = f"{CYAN}⚙ {total_agents} agents ctx Σ {_fmt_tokens(total_tokens)}{RST}"
        _WF_CACHE["key"] = cache_key
        _WF_CACHE["result"] = result
        return result
    
    # Idle: show session cumulative
    completed = _read_completed_workflows(session_dir)
    if completed["run_count"] == 0:
        return ""
    
    tok_str = _fmt_tokens(completed["total_tokens"])
    result = (f"{DIM}wf:{RST} agents ctx Σ {WHITE}{tok_str}{RST} "
              f"{DIM}· {completed['run_count']} runs{RST}")
    _WF_CACHE["key"] = cache_key
    _WF_CACHE["result"] = result
    return result
```

#### 1.8 Registration

**SEGMENTS dict** (python-engine.py, after :1164):
```python
"workflows": seg_workflows,
```

**TIER_PRESETS** — add `"workflows"` to `standard` and `full` lists (after `"agent"`):
```python
"standard": ["model", "context", "vim_mode", "agent", "workflows", "git_branch", ...],
"full": ["model", "context", "vim_mode", "agent", "workflows", "git_branch", ...],
```

**build_metrics_line()** — add compact form for full-tier line 4:
```python
wf = seg_workflows(ctx)
if wf:
    parts.insert(0, wf)  # workflows first on metrics line
```

#### 1.9 Node.js Parity

Add equivalent `workflows(ctx)` method to SEGMENTS object in `node-engine.js`. The algorithm is identical; use Node.js fs API. Key points:
- Use `fs.readFileSync` with `Buffer.slice(-65536)` for the tail read
- Same regex pattern
- Same cache (module-level `let wfCache = {}`)
- Same `_fmt_tokens` helper (already exists in Node as `fmtTokens`)

#### 1.10 `build_metrics_line` addition (Python, lines 1118–1138)

After `cache = seg_cache_hit(ctx)`:
```python
wf = seg_workflows(ctx)
if wf:
    parts.append(wf)
```

Note: remove the `is_peak` check that was removed in Option 5.

#### 1.11 Docs Updates

**doctor/doctor.sh** — add to `SEG_DETAIL` and `SEG_ONELINER`:
```bash
SEG_DETAIL[workflows]="What it shows:
  When a workflow (multi-agent orchestration) is running: the number of active
  agents and their combined current context footprint (input+cache tokens of each
  agent's most recent turn).
  When idle: session-cumulative tokens across all completed workflow runs and
  the number of runs.

Label semantics:
  'agents ctx Σ' means context footprint (final context window size of each
  agent), NOT cumulative API billing across all turns. cache_read_input_tokens
  are re-billed each turn; only the last turn is counted to avoid inflation.

When it hides:
  Hidden if no session directory can be found, or if no workflows have run
  this session."

SEG_ONELINER[workflows]="Live workflow agent count + context Σ (or session cumulative)"
```

Add `workflows` to the segment list in the explain loop at :362–365.

**README.md** — add a row to the segment table in the "Main Status Line" section:
```
| `⚙ 4 agents ctx Σ 312K` | Workflow footprint | Live: agents running + context Σ; Idle: session cumulative |
```

**config.example.json** — add `"workflows": true` to the `segments` block.

#### 1.12 Acceptance Criteria — Option 1

1. Fixture test in `tests/test_workflows.py`:
   - Set up a fake session dir with a `subagents/workflows/wf_test/agent-001.jsonl` containing the trap fixture (two usage blocks — see Section 6)
   - Assert the segment returns a value containing `ctx Σ` and the tokens match the LAST usage block only (not the sum of both)
   - Assert the agent count is 1
2. Fixture test for completed workflow:
   - Write a fake `wf_sample.json` (from Section 4.1) to `workflows/`
   - No live workflow dirs
   - Assert segment returns string containing `wf:` and `8 runs` (or whatever count matches)
3. Test for no-session case (stdin has no `transcript_path` and no match in `.claude/sessions/`): assert segment returns `""`
4. `pytest tests/` — all pass
5. Doctor `doctor.sh --explain workflows` prints the description.

---

### Option 3 — Rate-Limits as Interactive-Usage Anchor

**Context:** Post-06-15, the 5h/7d bars measure only interactive usage. This option promotes them visually and adds a delta indicator when account utilization is rising faster than the session cost implies (i.e., workflows or parallel sessions are the real drain).

#### 3.1 Post-06-15 Label Change

After 2026-06-15, relabel the bars from "5h"/"weekly" to "5h (interactive)"/"weekly (interactive)". This should be driven by the `schedule.json` remote labels — update the labels in schedule.json with a `labels_after` dict and a `labels_cutover_date` field, OR simply change the `five_hour` label directly on the cutover date via a schedule.json push.

**Simpler approach:** Add to `schedule.json`:
```json
"labels": {
  "five_hour": "5h interactive",
  "weekly": "weekly interactive",
  ...
}
```
This will automatically flow to `build_rate_limits_line()` which already reads `labels.five_hour` and `labels.weekly` at :1093–1094.

#### 3.2 seven_day_sonnet

The usage cache may contain a `seven_day_sonnet` block. Show it in `build_rate_limits_line()` if non-zero:

```python
sds = usage_data.get("seven_day_sonnet", {})
sds_pct = int(sds.get("utilization", 0))
if sds_pct > 0:
    sds_bar = build_usage_bar(sds_pct, bw)
    sds_color = color_for_pct(sds_pct)
    sds_reset = sds.get("resets_at", "")
    sds_time = _format_reset(sds_reset, "datetime")
    sonnet_part = f"{DIM}sonnet{RST} {sds_bar} {sds_color}{sds_pct:3d}%{RST} {DIM}⟳{RST} {WHITE}{sds_time}{RST}"
    # Append to the rate limits line after the weekly part
```

#### 3.3 Off-Loop Delta Indicator

Heuristic: if the 5-hour utilization delta over the rolling window (last 10 minutes) is notably larger than what the session cost delta would predict, something outside the main session is burning quota.

```python
def _check_offloop_drain(ctx, usage_data: dict) -> str:
    """Return a warning string if account quota is draining faster than session cost explains."""
    fh_pct = float(usage_data.get("five_hour", {}).get("utilization", 0))
    
    # Need a previous reading to compare — store in ctx or rolling_state
    prev_fh_pct = ctx.get("_prev_fh_pct")
    now = time.time()
    prev_time = ctx.get("_prev_fh_time", now)
    ctx["_prev_fh_pct"] = fh_pct
    ctx["_prev_fh_time"] = now
    
    if prev_fh_pct is None:
        return ""
    
    elapsed_min = (now - prev_time) / 60.0
    if elapsed_min < 2:
        return ""
    
    fh_delta_pct = fh_pct - prev_fh_pct
    if fh_delta_pct <= 0:
        return ""
    
    # Compare to cost delta
    session_cost_delta = _rs_rate(10)  # $/hr from rolling_state
    if session_cost_delta is None:
        return ""
    
    # Rough calibration: 1% of 5h limit ≈ $0.80 typical spend
    # If rate limit delta implies >2x the session cost delta, warn.
    CALIBRATION_USD_PER_PCT = 0.80
    expected_pct_per_hr = session_cost_delta / CALIBRATION_USD_PER_PCT
    actual_pct_per_hr = fh_delta_pct / elapsed_min * 60
    
    if actual_pct_per_hr > expected_pct_per_hr * 2.5 and fh_delta_pct > 3:
        return f" {YELLOW}⚠ off-loop drain{RST}"
    return ""
```

**IMPLEMENTER NOTE:** The calibration constant `0.80` (USD per 1% of 5h limit) is an approximation. The actual conversion depends on model, token mix, and plan. The heuristic is intentionally conservative (2.5× threshold + 3% minimum delta) to reduce false positives. Mark this behavior as "approximate" in doctor docs.

Add `_check_offloop_drain(ctx, usage_data)` call in `build_rate_limits_line()` and append the result to the line.

#### 3.4 Acceptance Criteria — Option 3

1. Both engines: piping stdin with a populated usage cache that has `seven_day_sonnet.utilization = 35` renders the sonnet bar in full-tier output.
2. Labels in `build_rate_limits_line()` reflect `schedule.labels` which can be remotely updated.
3. New test `tests/test_option3_offloop.py`: mock a scenario where fh_pct grew 5% in 2 minutes but session cost_delta implies only 1%/hr — assert the `⚠ off-loop drain` string appears.

---

### Option 4 — Usage-Credits / SDK-Credit Overflow Segment

**Context:** The `extra_usage` block in the usage cache represents overflow spending (and post-06-15, the SDK credit channel). This option renders it.

#### 4.1 New Segment: seg_usage_credits

```python
def seg_usage_credits(ctx):
    """Show extra_usage / SDK-credit overflow status from usage cache."""
    usage_data = ctx.get("usage_data")
    if not usage_data:
        return ""
    
    extra = usage_data.get("extra_usage", {})
    if not extra:
        return ""
    
    enabled = extra.get("enabled", False)
    consumed = float(extra.get("consumed_usd", 0.0))
    limit = extra.get("limit_usd")  # None = unknown/unlimited
    
    if not enabled and consumed == 0:
        return ""  # Hidden: extra usage not active
    
    if not enabled:
        return f"{DIM}overflow: off{RST}"
    
    if limit is not None and limit > 0:
        pct = int(consumed * 100 / limit)
        bar = build_usage_bar(pct, 8)
        color = color_for_pct(pct)
        return f"{DIM}overflow{RST} {bar} {color}${consumed:.2f}/${limit:.0f}{RST}"
    
    return f"{DIM}overflow{RST} {YELLOW}${consumed:.2f}{RST}"
```

Register in SEGMENTS as `"usage_credits"`. Add to full-tier preset only (not standard — too noisy for standard).

Post-06-15: when `extra_usage` becomes the SDK credit channel, the labels in this segment should update. No code change needed — the segment already renders `consumed_usd` and `limit_usd` from the cache, which the API will populate.

#### 4.2 Acceptance Criteria — Option 4

1. Cache file with `extra_usage: {enabled: true, consumed_usd: 5.50, limit_usd: 20.0}` → segment renders `overflow ████░░░░ $5.50/$20`.
2. `extra_usage: {enabled: false, consumed_usd: 0}` → segment returns `""`.
3. New test in `tests/test_usage_credits.py`.

---

### Option 7 — SDK Credit Meter + Auth Badge

#### 7.1 Auth Badge: seg_auth_mode

```python
def seg_auth_mode(ctx):
    """Warn if ANTHROPIC_API_KEY is exported (the -p billing trap).
    Show auth mode: oauth / api-key / setup-token."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    oauth_token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "")
    
    if api_key:
        # DANGER: exported API key will be used by claude -p and billed to API account
        return f"{BG_RED} API-KEY EXPORTED — claude -p bills API acct {RST}"
    
    if oauth_token:
        if oauth_token.startswith("sk-ant-oat01-"):
            return f"{DIM}auth:setup-token{RST}"
        return f"{DIM}auth:oauth{RST}"
    
    # Check .credentials.json
    creds_path = Path.home() / ".claude" / ".credentials.json"
    if creds_path.exists():
        try:
            data = json.loads(creds_path.read_text(encoding="utf-8"))
            if data.get("claudeAiOauth", {}).get("accessToken"):
                return f"{DIM}auth:oauth{RST}"
        except Exception:
            pass
    
    return f"{DIM}auth:?{RST}"
```

Register as `"auth_mode"` in SEGMENTS. **Not in any tier preset by default** — opt-in via custom tier. The API-key warning is always shown if ANTHROPIC_API_KEY is set, regardless of tier. Add special logic: if `api_key` is set, prepend the warning to line 1 unconditionally (like `banner`).

```python
# In main(), after banner injection:
if os.environ.get("ANTHROPIC_API_KEY"):
    api_warn = seg_auth_mode(ctx)
    if api_warn and api_warn not in parts:
        parts.insert(0, api_warn)
```

#### 7.2 SDK Burn Ledger

**Discovery approach for detecting print-mode sessions:** Read `~/.claude/sessions/*.json`. Each session file has fields including (to be verified against live data): `kind`, `entrypoint`, `status`. If `kind == "print"` or `entrypoint == "print"` or similar marker, the session is a `claude -p` invocation. 

**IMPLEMENTER NOTE:** The exact field names for distinguishing interactive vs print sessions in `~/.claude/sessions/*.json` are not confirmed. Inspect the file schema on the target machine and use whichever field distinguishes them. Fallback: any session with `status == "completed"` and duration < 60s and cost > 0 is likely print mode. Document the approximation in doctor.

**Ledger file location:** `~/.claude/statusline-sdk-ledger.json` (see Section 4.5 for schema).

**Billing cycle reset:** The config key `sdk_billing_day` (int, 1–28) determines when the monthly total resets. Default: 1 (first of month). If today's date matches `billing_day`, and the ledger's `last_updated` is from a prior month, reset `month_total_usd` to 0 and archive entries.

**Segment: seg_sdk_meter**

```python
def seg_sdk_meter(ctx):
    """Show month-to-date SDK credit burn vs plan ceiling."""
    ledger_path = Path.home() / ".claude" / "statusline-sdk-ledger.json"
    if not ledger_path.exists():
        return ""
    
    try:
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    except Exception:
        return ""
    
    consumed = float(ledger.get("month_total_usd", 0.0))
    ceiling = float(ledger.get("plan_ceiling_usd", 20.0))
    
    if consumed == 0:
        return ""
    
    pct = int(consumed * 100 / ceiling) if ceiling > 0 else 0
    color = color_for_pct(pct)
    bar = build_usage_bar(pct, 8)
    
    # Check if SDK credit depleted + overflow status
    extra = ctx.get("usage_data", {}).get("extra_usage", {})
    overflow_enabled = extra.get("enabled", False)
    
    suffix = ""
    if pct >= 100 and not overflow_enabled:
        suffix = f" {BG_RED} BLOCKED {RST}"
    elif pct >= 100 and overflow_enabled:
        suffix = f" {YELLOW}overflow ON{RST}"
    
    return (f"{DIM}sdk{RST} {bar} {color}${consumed:.2f}/${ceiling:.0f}{RST}"
            f"{DIM} ~per-machine approx{RST}{suffix}")
```

Register as `"sdk_meter"` in SEGMENTS. Not in preset lists by default. Users enable via custom tier config.

**Defensive probe:** If a future stdin or usage-cache payload exposes `sdk_credit.remaining_usd` or similar, prefer it. Add a check at the top of `seg_sdk_meter`:
```python
# Future: if the API exposes sdk_credit directly, prefer it
sdk_direct = ctx.get("usage_data", {}).get("sdk_credit", {})
if sdk_direct.get("remaining_usd") is not None:
    # Use direct data, not ledger approximation
    ...
```

#### 7.3 Acceptance Criteria — Option 7

1. When `ANTHROPIC_API_KEY` is set in env: line 1 contains the red API-key warning regardless of tier.
2. When `ANTHROPIC_API_KEY` is not set and oauth token found: `auth:oauth` rendered (opt-in segment).
3. Ledger with `month_total_usd: 15.0, plan_ceiling_usd: 20.0` → renders `sdk ████████░░ $15/$20 ~per-machine approx`.
4. Ledger with `pct >= 100` and `extra_usage.enabled: false` → renders `BLOCKED`.
5. New test `tests/test_option7_auth.py`.

---

### Option 6 — Narrator Enrichment + VS Code

**Depends on Option 1 completing first.**

#### 6.1 New Observation Fields

Add to `Observation` dataclass in `narrator/observations.py` (after :67):
```python
# Workflow fields (populated if session dir found)
subagent_tokens_live: int = 0      # sum of live agent ctx Σ
subagent_runs_session: int = 0     # completed workflow run count
active_workflow_agents: int = 0    # count of currently running agents
```

In `build(memory)`, after the existing field population, add:
```python
# Workflow data (reuses seg_workflows logic)
try:
    session_dir = _find_session_dir(stdin_data or {})
    if session_dir:
        live_wfs = _detect_live_workflows(session_dir)
        obs.active_workflow_agents = sum(w["agents"] for w in live_wfs)
        obs.subagent_tokens_live = sum(w["tokens"] for w in live_wfs)
        if not live_wfs:
            completed = _read_completed_workflows(session_dir)
            obs.subagent_runs_session = completed["run_count"]
except Exception:
    pass
```

Import `_find_session_dir`, `_detect_live_workflows`, `_read_completed_workflows` from `engines.python-engine` or refactor them into a shared `lib/workflows.py` module that both the engine and narrator can import.

**IMPLEMENTER NOTE:** If creating `lib/workflows.py`, move the shared functions there and import them in both `python-engine.py` and `narrator/observations.py`. This is cleaner than importing from engines.

#### 6.2 New Scoring Template

In `narrator/scoring.py`, add after the `subagent_suggestion` template:

```python
if obs.active_workflow_agents > 0 and obs.subagent_tokens_live > 100_000:
    tok_str = f"{obs.subagent_tokens_live / 1_000_000:.1f}M" if obs.subagent_tokens_live >= 1_000_000 else f"{obs.subagent_tokens_live // 1000}K"
    key = "workflow_background_drain"
    results.append(Insight(
        text=(
            f"Workflows running {obs.active_workflow_agents} agents ({tok_str} ctx) in the background — "
            f"your main context looks clean but account quota is draining. "
            f"Rate-limit bars reflect this, not the cost line."
        ),
        text_he=(
            f"Workflows מריצים {obs.active_workflow_agents} סוכנים ({tok_str} ctx) ברקע — "
            f"ה-context הראשי נראה נקי אבל המכסה נצרכת. "
            f"בר rate-limit משקף את זה, לא שורת העלות."
        ),
        urgency=7,
        novelty=_novelty(key, memory),
        actionability=5,
        uniqueness=10,
        template_key=key,
    ))
```

Apply equivalent to `narrator-node.js` `buildInsights()` function.

#### 6.3 VS Code Context File

In `python-engine.py` `main()`, at the end of rendering (after all print statements), add:

```python
# Write context file for VS Code extension
try:
    _write_vscode_context(ctx)
except Exception:
    pass
```

```python
def _write_vscode_context(ctx):
    """Write statusline data to %TEMP%/claude/statusline-context.json for VS Code extension."""
    import tempfile
    context_dir = Path(tempfile.gettempdir()) / "claude"
    context_dir.mkdir(parents=True, exist_ok=True)
    context_path = context_dir / "statusline-context.json"
    
    usage_data = ctx.get("usage_data", {})
    wf_live = ctx.get("_wf_live", [])   # set by seg_workflows if called
    wf_completed = ctx.get("_wf_completed", {})
    
    payload = {
        "ts": int(time.time()),
        "five_hour_pct": int(usage_data.get("five_hour", {}).get("utilization", 0)),
        "seven_day_pct": int(usage_data.get("seven_day", {}).get("utilization", 0)),
        "cost_usd": ctx["stdin"].get("cost", {}).get("total_cost_usd", 0),
        "ctx_pct": 0,
        "is_peak": ctx.get("is_peak", False),
        "active_workflow_agents": sum(w["agents"] for w in wf_live),
        "subagent_tokens_live": sum(w["tokens"] for w in wf_live),
        "subagent_runs_session": wf_completed.get("run_count", 0),
    }
    
    cw = ctx["stdin"].get("context_window", {})
    size = cw.get("context_window_size", 0)
    if size > 0:
        usage = cw.get("current_usage", {})
        current = usage.get("input_tokens", 0) + usage.get("cache_creation_input_tokens", 0) + usage.get("cache_read_input_tokens", 0)
        payload["ctx_pct"] = int(current * 100 / size)
    
    # Atomic write
    tmp_path = context_path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(payload), encoding="utf-8")
    os.replace(str(tmp_path), str(context_path))
```

The VS Code extension reads `CONTEXT_PATH` at `vscode/extension.ts :58`. The schema of `statusline-context.json` is currently undocumented; the extension should be updated to display `active_workflow_agents` and `subagent_tokens_live` if non-zero. Check `vscode/extension.ts` for the parsing logic and add the new fields accordingly.

#### 6.4 Acceptance Criteria — Option 6

1. `Observation` dataclass has `subagent_tokens_live`, `subagent_runs_session`, `active_workflow_agents` fields.
2. With a fake session dir containing live workflows, `observations.build({})` returns non-zero `active_workflow_agents`.
3. The `workflow_background_drain` template fires in narrator scoring when `active_workflow_agents > 0` and `subagent_tokens_live > 100K`.
4. After `main()` runs (via subprocess with fixture stdin), `%TEMP%/claude/statusline-context.json` exists and contains `active_workflow_agents` key.
5. `pytest tests/test_narrator_observations.py` — all pass.

---

## 6. Test Fixtures Appendix

No `tests/fixtures/` directory currently exists in the repo. Create it.

### 6.1 `tests/fixtures/stdin_minimal.json`

A synthetic stdin payload for basic engine testing:
```json
{
  "session_id": "sess_test_001",
  "transcript_path": "/tmp/test-session.jsonl",
  "model": { "display_name": "Claude Sonnet 4.6 (test)" },
  "context_window": {
    "context_window_size": 200000,
    "current_usage": {
      "input_tokens": 45000,
      "cache_creation_input_tokens": 10000,
      "cache_read_input_tokens": 60000,
      "output_tokens": 2000
    }
  },
  "cost": {
    "total_cost_usd": 2.34,
    "total_duration_ms": 1800000,
    "total_lines_added": 150,
    "total_lines_removed": 30
  },
  "cwd": "/tmp/test-project",
  "vim": { "mode": "" },
  "agent": { "name": "" },
  "worktree": { "name": "" }
}
```

### 6.2 `tests/fixtures/wf_sample.json`

Already shown in Section 4.1. Create this file.

### 6.3 `tests/fixtures/agent_sample.jsonl` — THE TRAP FIXTURE

This fixture is designed to catch the "sum all blocks" bug:
```jsonl
{"type": "user", "message": {"content": "Start task"}, "isSidechain": true}
{"type": "assistant", "message": {"content": "Starting...", "usage": {"input_tokens": 30000, "cache_creation_input_tokens": 15000, "cache_read_input_tokens": 0, "output_tokens": 500}}, "isSidechain": true}
{"type": "user", "message": {"content": "Continue"}, "isSidechain": true}
{"type": "assistant", "message": {"content": "Continuing...", "usage": {"input_tokens": 12000, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 45826, "output_tokens": 800}}, "isSidechain": true}
```

Sum of all blocks: 30000+15000+0 + 12000+0+45826 = **102,826** (WRONG)
Correct answer (last block only): 12000 + 0 + 45826 = **57,826** (CORRECT)

Any test using this fixture must assert the result equals 57,826, not 102,826.

Note: This is also the fixture that proves why output_tokens are excluded: they are response tokens, not context tokens. The context footprint is input side only.

### 6.4 `tests/fixtures/usage_cache_sample.json`

```json
{
  "five_hour": { "utilization": 72.5, "resets_at": "2026-06-10T14:00:00Z" },
  "seven_day": { "utilization": 41.0, "resets_at": "2026-06-14T00:00:00Z" },
  "seven_day_sonnet": { "utilization": 15.0, "resets_at": "2026-06-14T00:00:00Z" },
  "extra_usage": { "enabled": false, "consumed_usd": 0.0, "limit_usd": null }
}
```

---

## 7. Definition of Done + Suggested Commit Sequence

### Definition of Done

- [ ] All existing `pytest tests/` tests pass (zero regressions)
- [ ] Each option has at least the tests specified in its Acceptance Criteria section
- [ ] `echo '<stdin_minimal.json contents>' | python engines/python-engine.py` runs without error and produces non-empty output
- [ ] `echo '<stdin_minimal.json contents>' | node engines/node-engine.js` same
- [ ] `doctor.sh --explain workflows` prints the workflows description
- [ ] `doctor.sh --explain peak_hours` mentions "historical / custom-tier only"
- [ ] `schedule.json` has `"mode": "normal"` and version bumped to v5
- [ ] `README.md` has the new `workflows` segment row in the table
- [ ] `config.example.json` has `"workflows": true` in the segments block
- [ ] No changes to `C:\Users\nadav\.claude\cc-2x-statusline\` or `~/.claude/settings.json`
- [ ] No `ANTHROPIC_API_KEY` or any secret is committed
- [ ] All `.sh` files use LF line endings

### Suggested Commit Sequence

```
fix(option5): remove peak-era UI artifacts and fix narrator rate-limit bug

  - TIER_PRESETS: remove peak_hours/promo_2x from minimal/standard/full
  - build_rate_limits_line/build_metrics_line: remove lightning tag + peak note
  - observations._apply_stdin: stop reading non-existent pct_5h/pct_7d from stdin
  - observations.build: populate rate_limit_{5h,7d}_pct from statusline-usage-cache.json
  - scoring/narrator-node: retire off_peak_wide_open template
  - schedule.json: set mode=normal, bump to v5
  - tests: test_narrator_rate_limits.py verifying cache-sourced rate limits

feat(option2): add schedule.json banners for SDK cutover and +50% promo expiry

  - seg_banner/SEGMENTS.banner: support banners[] array (backward compat with single banner)
  - schedule.json: add two banner entries with correct expiry dates
  - tests: test_banners.py with date-based fixture scenarios

feat(option1): seg_workflows — live + idle workflow token visibility

  - lib/workflows.py: _find_session_dir, _detect_live_workflows, _read_completed_workflows, _read_agent_last_usage_tokens
  - python-engine: seg_workflows segment, register in SEGMENTS, add to standard+full tiers
  - node-engine: parity workflows segment
  - build_metrics_line: surface compact wf data on full-tier line 4
  - doctor: SEG_DETAIL[workflows] + SEG_ONELINER[workflows]
  - README: workflows row in segment table
  - config.example.json: workflows: true
  - tests: test_workflows.py with trap fixture asserting last-block-only logic

feat(option3): rate-limits interactive labeling + seven_day_sonnet + off-loop drain indicator

  - schedule.json: update labels to "5h interactive" / "weekly interactive"
  - build_rate_limits_line: render seven_day_sonnet bar when non-zero
  - build_rate_limits_line: _check_offloop_drain heuristic
  - tests: test_option3_offloop.py

feat(option4): seg_usage_credits — overflow/SDK-credit channel display

  - seg_usage_credits in python-engine + node-engine
  - register in SEGMENTS; add to full tier
  - tests: test_usage_credits.py

feat(option7): auth badge + SDK burn meter

  - seg_auth_mode: API-key export warning + auth mode display
  - seg_sdk_meter: ledger-based monthly SDK burn meter
  - ANTHROPIC_API_KEY check in main() unconditional prepend
  - tests: test_option7_auth.py

feat(option6): narrator workflow enrichment + VS Code context file

  - Observation: subagent_tokens_live, subagent_runs_session, active_workflow_agents
  - observations.build: populate from lib/workflows.py
  - scoring: workflow_background_drain template
  - narrator-node: parity
  - _write_vscode_context: write to %TEMP%/claude/statusline-context.json
  - tests: test_narrator_observations.py additions
```

---

## 8. Open Questions (IMPLEMENTER NOTE)

1. **`~/.claude/sessions/*.json` schema:** The spec assumes `kind` or `entrypoint` fields distinguish interactive vs print sessions. Inspect actual files on the target machine before implementing Option 7's ledger. If no reliable distinguisher exists, fall back to duration+cost heuristic and document it clearly.

2. **`vscode/extension.ts` parsing:** The VS Code extension currently reads `CONTEXT_PATH` but the spec did not fully audit what fields it expects. Before writing new fields in `_write_vscode_context`, read `vscode/extension.ts` from line 58 onwards to understand the full parsing contract and avoid breaking existing extension behavior.

3. **`lib/workflows.py` vs inline:** Option 6 suggests extracting shared workflow functions to `lib/workflows.py`. Option 1 puts them inline in `python-engine.py`. The implementer must choose one approach and apply it consistently across both options. Recommendation: if Option 1 is implemented first with inline functions, extract to `lib/workflows.py` during Option 6.

4. **Banner escalation color:** The `color_final_week` escalation for the +50% promo banner is optional. If implementing it, the engine change is in `seg_banner()`: compute `days_until = (exp_date - local_time.date()).days` and use `color_final_week` if `days_until <= 7`.

5. **Node.js tail read for 64KB:** Node.js does not have a direct "seek from end" API for text reading. Use `fs.openSync` + `fs.fstatSync` + `fs.readSync` with a buffer. Alternatively, use `Buffer.alloc(65536)` and read from `fileSize - 65536`.

6. **`_WF_CACHE` dict thread safety:** Python's GIL protects simple dict reads/writes in CPython. However, if the statusline is ever called from multiple threads (not currently the case), the cache should use a threading.Lock. For now, the GIL is sufficient.

7. **Windows path slug for session discovery:** The `cwd.replace("\\", "-").replace(":", "").lstrip("-")` slug must match exactly how Claude Code generates the project slug. On Windows, `C:\Users\nadav\project` becomes `-Users-nadav-project` after this transform, but Claude Code may use a different convention. Verify against an actual `~/.claude/projects/` listing on the target machine.

8. **`schedule.json` remote vs local:** The schedule.json in the repo root is fetched by users from the raw GitHub URL (config `schedule_url`). Changes to this file take 3 hours to propagate (cache TTL). Time-sensitive changes (like the SDK cutover banner) should be pushed immediately before the cutover date.
