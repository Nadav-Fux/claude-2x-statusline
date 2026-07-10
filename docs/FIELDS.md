# FIELDS.md — data origins

Docs-as-spec: every rendered segment/row, mapped to its exact source (stdin
payload field, file path, API endpoint, or computation). This is the
authoritative cross-reference for "where does that number come from" —
keep it in sync with `engines/python-engine.py` (source of truth) and its
node/lib twins.

See also: `CONTRIBUTING.md`'s **display rule** ("whole field or nothing") —
every segment below either renders completely or renders nothing; there is
no blank/dash/null state.

Paths below are written as `~/.claude/...` for brevity; the engines resolve
this via `Path.home() / ".claude"` (Python) / `os.homedir()` + `.claude`
(Node). `$TMPDIR/claude/...` means `tempfile.gettempdir()` (Python) /
`os.tmpdir()` (Node), **not** `~/.claude` — those are throwaway render
caches, not user config/state.

## Line 1 — core segments

| Segment | What it shows | Exact source |
|---|---|---|
| `model` | Current model's short display name | `stdin.model.display_name`, text before the first `(` (e.g. `"Opus 4.8 (1M context)"` → `"Opus 4.8"`). `seg_model`. |
| `context` | Tokens used / context window size + % | `stdin.context_window.current_usage.{input_tokens,cache_creation_input_tokens,cache_read_input_tokens}` summed, divided by the resolved window size. Window size: `stdin.context_window.context_window_size`, **overridden** by a `[1m]`/`(1M context)` marker parsed out of `stdin.model.display_name`/`stdin.model.id` when present (`_resolve_ctx_window`, `_model_window_from_name`) — Claude Code reports a stale 200k size for 1M sessions, so the marker wins. `seg_context`. |
| `cost` | Cumulative session cost | `stdin.cost.total_cost_usd`. `seg_cost`. |
| `effort` | Thinking-effort level (e:LO/MED/HI) | `~/.claude/settings.json` → `effortLevel`. `seg_effort` / `load_claude_settings`. |
| `git_branch` | Checked-out branch | `git branch --show-current` (cwd from `stdin.cwd` / `stdin.workspace.current_dir`). `seg_git_branch`. |
| `git_dirty` | `saved` / `N changed` / `N unpushed` | `git status --porcelain` (line count = uncommitted) + `git rev-list --count @{u}..HEAD` (unpushed). `seg_git_dirty`. |
| `git_ahead_behind` | `↑N`/`↓N` vs upstream | `git rev-list --count @{u}..HEAD` / `git rev-list --count HEAD..@{u}`. `seg_git_ahead_behind`. |
| `churn` | Uncommitted diff stat (`Δ +ins −del · Nf`) | `git -C <cwd> diff --shortstat HEAD`, parsed by `parse_git_shortstat`. `seg_churn`. |
| `vim_mode` | NORMAL/INSERT | `stdin.vim.mode`. `seg_vim_mode`. |
| `agent` / worktree | Sub-agent name, `wt:<name>` | `stdin.agent.name`, `stdin.worktree.name`. `seg_agent`. |
| `env` | LOCAL (cyan) / REMOTE (magenta) | `$SSH_CLIENT` / `$SSH_TTY` / `$SSH_CONNECTION` env vars. `seg_env`. |
| `auth_mode` | Active billing credential | `$ANTHROPIC_API_KEY` (red warning if exported) → `$CLAUDE_CODE_OAUTH_TOKEN` → `~/.claude/.credentials.json` (`claudeAiOauth.accessToken`). `seg_auth_mode`. |
| render-time clock (multi-cli only) | Dim `HH:MM`, end of line 1 | Local wall-clock time from `get_local_time()` (auto-detected timezone). `_render_clock`, item 5 of the owner adoption package — **not** the Claude Code version (explicitly rejected). |

## Session-quality line (full + multi-cli tiers, line 4)

| Segment | What it shows | Exact source |
|---|---|---|
| `burn_rate` (label `spending`) | `$/hr` burn rate + `ctx full ~Nm` projection | `stdin.cost.total_cost_usd` / `total_duration_ms`, sampled into `~/.claude/statusline-state.json` (or the session-scoped `~/.claude/statusline-state-<session_id[:8]>.json` once `set_session_id` runs, so concurrent sessions don't cross-contaminate) via `lib/rolling_state.append_sample`; rate = 10-minute rolling average (`rolling_rate(10)`), falling back to lifetime average (`cost / elapsed_hours`) when the rolling window has no signal yet. Context-depletion projection uses `rolling_tokens_out(10)` against the resolved context window. `seg_burn_rate`. |
| `cache_hit` (label `cache reuse`) | Cache-reuse % + savings estimate | `stdin.context_window.current_usage.{cache_read_input_tokens,cache_creation_input_tokens}`. `hit_pct = cache_read * 100 // (cache_read + cache_creation)` (hidden below 1000 total cache tokens). `savings_pct = clamp(hit_pct * 0.9, 0, 90)`. Delta (`↑N`) from `rolling_state.cache_delta(5)`. `seg_cache_hit`. |
| `eff` **(new)** | Efficiency dots `●●●●○` | The same `hit_pct` `seg_cache_hit` just computed, stashed on `ctx["cache_hit_pct"]` (Node: `ctx.cacheHitPct`) and mapped `0-100% → 0-5` filled dots, round-half-up. Purple (`\x1b[38;2;178;148;255m`). No letters/grades. Hidden whenever `cache_hit` was (not enough cache data). `seg_eff`. |
| `tool_count` **(new)** | This session's tool-call count, `⚒ N` | Count of literal `"type":"tool_use"` occurrences in the transcript JSONL at `stdin.transcript_path` (raw regex scan, not per-line JSON parsing). Cached by `session_id` + transcript mtime at `$TMPDIR/claude/statusline-toolcount-<sha256(session_id)[:16]>.json` — **never** under `~/.claude/`. Missing/unreadable transcript or missing `session_id`/`transcript_path` omits the whole segment; a genuine zero-tool-calls reading still renders `⚒ 0`. Purple icon. `seg_tool_count`. |
| `workflows` | Live workflow agent count / session cumulative | `~/.claude/projects/<slug>/<session_id>/{workflows,subagents/workflows}/wf_*.json` manifests (`lib/workflows.py`), plus a per-session high-water-mark at `<session_dir>/.statusline-wf-peak.json`. `seg_workflows`. |

## Claude rate limits (5h / weekly)

| Row | What it shows | Exact source |
|---|---|---|
| `5h` bucket | 5-hour rolling rate-limit bar | `usage_data.five_hour.{utilization,resets_at}`, from the cached OAuth usage response. **Short window** — thresholds red ≥80% / yellow ≥50%. |
| `weekly` bucket | 7-day rolling rate-limit bar | `usage_data.seven_day.{utilization,resets_at}`. **Long window** — thresholds red ≥75% / yellow ≥45% (item 1 of the owner adoption package). |
| `sonnet` sub-row | Sonnet-specific weekly utilization | `usage_data.seven_day_sonnet.utilization` — resets on the same clock as `weekly`, so it also uses the long-window thresholds. |
| — | `usage_data` itself | `GET https://api.anthropic.com/api/oauth/usage` (bearer = OAuth token), cached at `~/.claude/statusline-usage-cache.json` (60s TTL; render path only reads the cache, refresh happens synchronously but is skipped when the cache is fresh). OAuth token resolution order: `$CLAUDE_CODE_OAUTH_TOKEN` → `~/.claude/.credentials.json` (`claudeAiOauth.accessToken`) → macOS Keychain (`security find-generic-password -s "Claude Code-credentials" -w`). `seg_rate_limits`, `_get_oauth_token`. |
| `usage_credits` (label `overflow`) | Extra-usage/overflow credit status | `usage_data.extra_usage.{enabled,consumed_usd,limit_usd}` (same cached OAuth response above). `seg_usage_credits`. |
| `sdk_meter` (label `sdk`) | Month-to-date SDK credit burn | Direct: `usage_data.sdk_credit.{limit_usd,remaining_usd}` (same OAuth response). Fallback ledger: `~/.claude/statusline-sdk-ledger.json` (`{month, month_total_usd, plan_ceiling_usd}`) — externally fed, only rendered when stamped for the current month. `seg_sdk_meter`. |

**Window-aware color rule** (item 1): a usage-bar label naming a sub-day
window (`5h`, `12h`, …) uses the tighter red ≥80% / yellow ≥50% thresholds;
every other label (`7d`, `30d`, `weekly`, `wk`, GLM's `tok`, a monthly meter)
uses red ≥75% / yellow ≥45% since it covers a week/month/token-quota, not
hours. See `_is_long_window_label` / `color_for_pct` (Python) and
`isLongWindowLabel` / `colorPct` (Node).

## External providers (multi-cli tier + full tier when enabled)

All provider records are fetched by `lib/usage_providers.py` (mirrored in
`lib/usage_providers.js`), cached at `~/.claude/statusline-usage-<provider>.json`,
and refreshed via a detached background process — the render path only ever
reads the cache (never blocks on network). See `CONTRIBUTING.md`'s provider
architecture section for the general contract.

| Provider | What it shows | Exact source |
|---|---|---|
| **Codex** | 5h + weekly (or `Xh`/`Xd`, honestly labeled by actual window size) rate-limit bars, per detected plan | **Live path** (preferred, `source: "app-server"`): spawns `codex app-server`, performs a read-only `initialize` → `account/rateLimits/read` JSON-RPC handshake (never starts a model turn), authenticated via Codex's own on-disk `~/.codex/auth.json` (existence-checked, no token handling by us). Authoritative for 120s (`CODEX_LIVE_TTL`) before a detached refresh. **Rollout fallback** (self-healing): scans `~/.codex/sessions/*/*/*/rollout-*.jsonl` (year/month/day-nested), newest-mtime-first, up to 40 files (`CODEX_ROLLOUT_SCAN_LIMIT`), extracting the last known rate-limit snapshot/token counts per plan. Plans idle >7 days age out of `all_plans`. `get_codex_usage`, `_codex_app_server_snapshot`, `_codex_rollout_snapshots`, `_codex_rollout_files`. |
| **GLM** | 5h bar + `tok` (token-quota) metric | `GET https://api.z.ai/api/monitor/usage/quota/limit`, bearer/raw auth key resolved in order: OS keychain/secret store → `$ZAI_API_KEY` → `$ZHIPU_API_KEY` → `external_providers.glm.api_key` in config → scanned from `~/.codex/providers.env` (`ZAI_API_KEY=...`/`ZHIPU_API_KEY=...` lines). Response `data.limits[]` items: `type: "TIME_LIMIT"` → `five_hour` (label `5h`), `type: "TOKENS_LIMIT"` → `weekly` slot (label `tok` — a token quota, not a time window, but still classified LONG by the color rule). Cached 60s (`GLM_CACHE_TTL`), detached refresh. `parse_glm_quota_response`, `get_glm_usage`, `_glm_key_with_source`. |
| **Antigravity (AGY)** | Two pools (Gemini; Claude+GPT) × 5h + weekly bars | **Primary — quota-summary** (`_map_antigravity_quota_summary`): RPC `RetrieveUserQuotaSummary` (`/exa.language_server_pb.LanguageServerService/RetrieveUserQuotaSummary`), tried first against the **local** Antigravity IDE language server — discovered via `ps aux` (matching the language-server process to pull its `--csrf_token`/`--extension_server_port` args), then its actual LISTEN ports via `lsof -nP -iTCP -sTCP:LISTEN -a -p <pid>` on `127.0.0.1` (self-signed TLS accepted only for localhost) — then against the **cloud** endpoint `https://cloudcode-pa.googleapis.com/v1internal:retrieveUserQuotaSummary` using an OAuth token read from the `antigravity-usage` CLI's own stored config (`~/Library/Application Support/antigravity-usage/accounts/<email>/tokens.json` on macOS, XDG-equivalent elsewhere — read-only, never logged/cached by us). Refreshed every 120s (`ANTIGRAVITY_CACHE_TTL`) in a detached child. **CLI fallback** (5h-only, compact): shells out to the `antigravity-usage` binary itself (`antigravity-usage quota --json --method auto`, owns its own OAuth refresh), used only when no fresh quota-summary cache exists. `get_antigravity_usage`, `_antigravity_local_summary`, `_antigravity_cli_usage`. |
| **Copilot** | Remaining/used credits (label `Copilot`, resets next calendar month) | GitHub CLI: `gh api /organizations/<org>/settings/billing/usage?year=Y&month=M` (org mode) or `gh api /users/<login>/settings/billing/usage?year=Y&month=M` (individual mode), filtered to SKUs matching `Copilot AI Credits` / `Copilot Premium Requests` (configurable). Requires `gh auth status` to already be authenticated. Cached 300s (`COPILOT_CACHE_TTL`). `get_copilot_usage`, `refresh_copilot_cache`. An optional standalone cron wrapper exists at `scripts/copilot-credits-refresh.sh` but is not required — the Python stale-while-revalidate path is first-class. |

## Sessions / jobs

| Segment | What it shows | Exact source |
|---|---|---|
| `sessions` | `◉ N sess · M busy` (hidden when ≤1 live session) | `~/.claude/sessions/*.json`, each with `updatedAt` (within 15 min = "live") and `status` (`"busy"` counted separately). `lib/session_cockpit.collect_session_counts` / `render_session_summary`. |
| `jobs` | `↻ N jobs · M inflight` (or a single job's name) | `~/.claude/jobs/<job_id>/state.json` (`state`, `tempo`, `inFlight.{tasks,queued}`, filtered to non-finished/running states within 15 min) + worker count from `~/.claude/daemon/roster.json` (`workers` map size). `lib/job_monitor.collect_active_jobs` / `render_jobs_summary`. |

## Narrator (SessionStart / UserPromptSubmit hooks — not a statusline segment)

The narrator is Python-only (`narrator/engine.py`); it does not render on the
statusline itself. It runs as a Claude Code hook (`hooks/narrator-session-start.sh`,
`hooks/narrator-prompt-submit.sh`, wired into `~/.claude/settings.json`'s
`hooks.{SessionStart,UserPromptSubmit}`) and writes plain text to stdout,
which Claude Code surfaces as hook output above the prompt.

| Input | Exact source |
|---|---|
| Persisted narrator state (cost milestones, last-seen observations, language pref) | `~/.claude/narrator-memory.json` (atomic tmp+rename write). `narrator/memory.py`. |
| Live session snapshot (context %, cost, model, peak status) | `$TMPDIR/claude/statusline-context.json`, written every statusline render by `_write_vscode_context` (Python) / `writeVscodeContext` (Node) and read by `narrator/observations.py`. |
| Cross-CLI usage insights (`cross_cli_capped`, `cross_cli_offload`) | The same external-provider records `lib/usage_providers` collects for the multi-cli tier (Claude weekly vs. an external provider's coolest window). `narrator/observations.py`. |
| Optional Haiku-generated phrasing | Anthropic API call (model `claude-haiku-*`), gated by cost/frequency limits in `narrator/haiku.py`; falls back to template strings when unavailable. |

## Doctor / installer settings.json backups (item 4)

Not a rendered field, but part of this adoption package: every write to
`~/.claude/settings.json` — `doctor/fixes.sh`'s `set_statusline_command`,
`lib/wire-json.sh`'s `wire_json` (used by `install.sh` for both the
`statusLine` stanza and the narrator hook merge), and `install.sh`'s legacy
narrator-hook healing migration — first copies the existing file to
`settings.json.bak.<unix-epoch-seconds>` (skipped when the file doesn't
exist yet, since there's nothing to back up). The atomic tmp-file-then-rename
write pattern is unchanged; the backup is purely additive.
