#!/usr/bin/env bash
# claude-2x-statusline — doctor
#
# Diagnoses common problems, explains what's wrong in plain language, and
# can apply confirmed fixes. Patterns learned the hard way across multiple
# machines and the token-optimizer hijack incident — see README > "Known
# issues the doctor catches" for the full list.
#
# Modes:
#   doctor.sh              diagnose + print human report
#   doctor.sh --json       diagnose + emit JSON (for tooling)
#   doctor.sh --fix        diagnose + prompt to fix each fixable issue
#   doctor.sh --report     diagnose + send anonymous ping to telemetry
#   doctor.sh --explain             list all segments with one-line purposes
#   doctor.sh --explain <segment>   detailed explanation of a single segment
#
# Exit: 0 always. Non-zero exit would block Claude Code session hooks.

set -u

# ── Segment explanations ─────────────────────────────────────────────────
# Stored as a bash associative array; each value is a multi-line string.
declare -A SEG_DETAIL
SEG_DETAIL[peak_hours]="What it shows:
  Visual indicator showing whether you are currently inside or outside the
  peak-hour window defined by Anthropic's rate-limiting policy.

How it's computed:
  Reads the schedule (remote schedule.json or local fallback). Compares the
  current local time to today's peak window after converting Pacific time to
  your system timezone (DST-aware).

Display values:
  Off-Peak — green badge; limits consumed at the normal (1×) rate.
  Peak     — red or yellow badge; limits consumed faster.

Countdown:
  'peak in 3h 22m'  — minutes until peak starts.
  'peak ends 1h 5m' — minutes remaining in the current peak window.
  '3pm-9pm'         — the peak window expressed in YOUR local timezone.

Colors:
  Green  = Off-Peak (no throttling).
  Red    = Deep into peak (many hours remain).
  Yellow = Peak ending soon (< 1-2 hours).
  Green  = Peak almost over (< 30 minutes).

When it hides:
  Never; always present on all tiers."

SEG_DETAIL[model]="What it shows:
  The Claude model Claude Code is currently using, e.g. 'Opus 4.7' or
  'Sonnet 4.6' or 'Haiku 4.5'.

How it's computed:
  Read from the model.display_name field of the JSON Claude Code passes to
  the statusline on every hook invocation.

Display format:
  Short canonical name: 'Opus 4.7', 'Sonnet 4.6', 'Haiku 4.5'.
  Falls back to the raw string if it does not match a known pattern.

Colors: none — plain text.

When it hides:
  Never; always present on all tiers."

SEG_DETAIL[context]="What it shows:
  Tokens used out of the total context window, plus a percentage.
  Example: '360K/1.0M 36%' = 360 000 tokens used of a 1 000 000-token window.

How it's computed:
  tokens_used and context_window come from the stdin JSON that Claude Code
  provides at hook time. The percentage is tokens_used / context_window × 100.

Thresholds / colors:
  No color change on the number itself; the context_depletion segment (burn
  rate line) turns RED when the window is projected to fill in < 30 minutes.

When it hides:
  Hidden if context_window is 0 or not reported by Claude Code."

SEG_DETAIL[vim_mode]="What it shows:
  The current Vim keybinding mode active in Claude Code.
  Example: 'NORMAL', 'INSERT'.

How it's computed:
  Claude Code exposes the vim mode via the hook stdin payload when Vim
  keybindings are enabled in settings.json. The Python engine reads
  input_data.vim_mode (or the nested keymap stanza).

Colors: none — plain text.

When it hides:
  Completely absent when Vim mode is not enabled in Claude Code settings,
  or when the payload does not contain a vim_mode field."

SEG_DETAIL[agent]="What it shows:
  The name of the current sub-agent (or 'agent') when Claude Code is running
  in a multi-agent / subagent context.
  Example: 'search-agent', 'code-agent'.

How it's computed:
  Read from the agent_name or agent.name field of the hook stdin JSON.

When it hides:
  Hidden when not running inside a subagent (the field is absent or empty).
  This is the most common case — most users never see this segment."

SEG_DETAIL[worktree]="What it shows:
  The name of the current git worktree when working in a linked worktree
  (not the main worktree).
  Example: 'wt:feature-x'.

How it's computed:
  The engine calls 'git worktree list' and checks whether the current
  directory is inside a linked worktree. If so, the worktree name is shown.

When it hides:
  Hidden in the main (primary) worktree, or outside any git repo.
  Only appears when you have checked out a branch into a separate worktree
  directory via 'git worktree add'."

SEG_DETAIL[git_branch]="What it shows:
  The name of the currently checked-out git branch.
  Example: 'main', 'feature/my-branch'.

How it's computed:
  Runs 'git -C <workspace_dir> rev-parse --abbrev-ref HEAD'. Falls back to
  the workspace.current_dir from the hook JSON if git is not available.

Colors: none — plain text.

When it hides:
  Hidden when the current directory is not inside a git repository, or when
  git is not installed."

SEG_DETAIL[git_dirty]="What it shows:
  Whether the working tree has uncommitted or unpushed changes.
  'clean'               — no uncommitted changes and nothing to push.
  '2 unsaved'           — two files have uncommitted modifications.
  '3 unpushed'          — three local commits ahead of upstream.
  '2 changed, 3 unpushed' — both conditions.

How it's computed:
  Runs 'git -C <dir> status --porcelain' for uncommitted count, and
  'git rev-list --count @{u}..HEAD' for unpushed count.

Colors:
  Green  = 'clean' (no changes, nothing to push).
  Yellow = any non-clean state.

When it hides:
  Hidden when not inside a git repo."

SEG_DETAIL[cost]="What it shows:
  Cumulative session cost in USD.
  Example: '\$15.83' = you have spent \$15.83 this session.

How it's computed:
  Accumulated from the cost_usd field in each hook invocation payload.
  Persisted to the session state file between hook calls so the total grows
  across the session.

Colors: none — plain text.

When it hides:
  Shows \$0.00 at the very start of a session. Never fully hidden."

SEG_DETAIL[effort]="What it shows:
  The thinking-effort level currently configured in settings.json.
  Values: 'e:LO', 'e:MED', 'e:HI'.

How it's computed:
  Read from the thinking.effort or thinking.budget_tokens field in
  ~/.claude/settings.json, mapped to LO/MED/HI buckets.

When it hides:
  Hidden when thinking / extended reasoning is not enabled in settings."

SEG_DETAIL[rate_limits]="What it shows:
  Two graphical bars representing your Anthropic rate-limit consumption:
  the 5-hour rolling window and the weekly limit.

  Example: '5h ▰▰▱▱▱▱▱▱▱▱ 20% ⟳ 5:00pm · weekly ▰▰▰▰▱▱▱▱▱▱ 42% ⟳ 4/4 11:00pm'

Parts explained:
  '5h'                      — 5-hour rolling window limit.
  '▰▰▱▱▱▱▱▱▱▱ 20%'         — filled blocks = consumed; 20% of window used.
  '⟳ 5:00pm'               — time when the 5-hour window resets (local time).
  '⚡ peak'                  — shown during peak hours; consumption runs faster.
  'weekly'                  — weekly limit block (not affected by peak hours).
  '⟳ 4/4 11:00pm'          — date and time of the next weekly reset.

How it's computed:
  Polls the Anthropic usage API (or reads a locally cached snapshot). The
  engine re-fetches at most once per minute to avoid hammering the API.

Colors:
  Green  = < 50% consumed.
  Yellow = 50-80% consumed.
  Red    = > 80% consumed.

When it hides:
  Not shown on the minimal tier. Present on standard and full tiers."

SEG_DETAIL[env]="What it shows:
  Whether Claude Code is running on the local machine or over SSH.
  'LOCAL' = local session. 'REMOTE' = SSH/remote server.

How it's computed:
  Checks for the presence of the SSH_CLIENT, SSH_TTY, or SSH_CONNECTION
  environment variables. If any are set, reports REMOTE.

Colors:
  Cyan    = LOCAL.
  Magenta = REMOTE (SSH).

When it hides:
  Never; always present on all tiers."

SEG_DETAIL[burn_rate]="What it shows:
  Spending rate in USD per hour. The parenthesized label tells you the
  window:
    '\$6.3/hr (10m)'      — rolling 10-minute window (preferred, most current).
    '\$7.9/hr (session)'  — lifetime session average (fallback during warm-up
                            or when no recent activity).

How it's computed:
  The engine keeps a rolling 10-minute window of (timestamp, cost_usd) pairs
  at ~/.claude/statusline-state.json. It computes
  (delta_cost / delta_minutes) × 60 to get the hourly rate. Until 2+ samples
  span at least 1 minute, it falls back to total_cost_usd / session_hours.

Colors:
  RED    — rate ≥ \$10/hr.
  YELLOW — rate ≥ \$5/hr.
  MAGENTA — otherwise (visible).

When it hides:
  Only when no cost data exists at all (new session, first hook call)."

SEG_DETAIL[cache_hit]="What it shows:
  Cache hit ratio + whether the cache is actively working right now.
  Format:
    'cache 96% ↑2.3k active'  — 96% hit ratio; 2300 cache-read tokens in
                                 the last 5 min = saving money right now.
    'cache 96% idle'          — hit ratio is fine but no net new cache
                                 reads in the last 5 min (nothing to save).

How it's computed:
  hit_pct = cache_read_tokens / (cache_read_tokens + cache_creation_tokens) × 100.
  The delta comes from the rolling 5-minute window in
  ~/.claude/statusline-state.json.

Colors:
  Dim   = idle (no recent cache activity).
  Dim   = active with delta ≤ 500 tokens (minor savings).
  Green = active with delta > 500 tokens (significant savings).

When it hides:
  Hidden when total cache tokens < 1000 (not enough data)."

SEG_DETAIL[context_depletion]="What it shows:
  At the current token-generation rate (rolling 10-min window), how many
  minutes until the context window fills up.
  Format: 'CTX full 37m' — compact in roughly 37 minutes.

How it's computed:
  The engine tracks tokens_used over time in the session state file. It
  computes a tokens-per-minute rate from the 10-min rolling window, then
  divides the remaining tokens (context_window - tokens_used) by that rate.

Thresholds / colors:
  RED    = < 30 minutes  → compact NOW or lose context.
  YELLOW = < 60 minutes  → plan to compact soon.
  DIM    = < 180 minutes → worth watching.
  Hidden = > 180 minutes (no urgency).

When it hides:
  Hidden when projected fill time exceeds 180 minutes, or when the token
  rate window is not yet populated (early in session)."

SEG_DETAIL[timeline]="What it shows:
  A horizontal bar spanning today's 24-hour window with filled/empty
  characters representing peak and off-peak periods. A dot marks 'now'.

  Example: '━━━━━━━━━━━━━━━━━━━●━━━━━━━━━━━━━━━━━━━━━━━━'

How it's computed:
  The peak window from the schedule is mapped onto a fixed-width bar (default
  48 characters). Each character represents 30 minutes. The position of the
  dot is current_hour × 2.

  Legend (shown to the right): '━ off-peak  ━ peak (3pm-9pm)' — the peak
  hours in your local timezone.

When it hides:
  Not shown on minimal or standard tiers. On full tier, hidden on weekends
  (when there are no peak hours) and when the schedule mode is 'normal'
  (all-day free usage, no peak defined)."

SEG_DETAIL[metrics]="What it shows:
  The combined spending + cache metrics line (full tier only).
  Groups burn_rate, context_depletion, and cache_hit into one display line.
  Example: '│ spending \$3.2/hr · ctx full ~47m · cache 82% │'

How it's computed:
  build_metrics_line() assembles the three sub-segments. Each sub-segment
  is only included if it has data to show. The surrounding box characters
  match the rate_limits line for visual alignment.

When it hides:
  Not shown on minimal or standard tiers. Hidden on full tier if all three
  sub-segments have no data."

SEG_DETAIL[banner]="What it shows:
  A broadcast message loaded from the remote schedule.json file.
  Example: 'Planned maintenance Fri 11pm-1am PT'.

How it's computed:
  The engine fetches the schedule.json URL (configurable in
  statusline-config.json, defaults to the GitHub raw URL). If the file
  contains a 'banner' key with a non-empty message and an expiry timestamp
  that has not passed, the message is shown.

When it hides:
  Hidden after the expiry date defined in schedule.json. Also hidden if the
  schedule fetch fails (no network, stale cache) and no cached banner exists."

SEG_DETAIL[narrator]="What it shows:
  Line 5 of the full tier: one or two short sentences in plain language
  explaining what's happening in your session right now. Dynamic — the
  content rotates based on which facts are most actionable at the moment.

Example outputs:
  'ⓘ Context fills in ~24m — compact now to keep history. · Burning \$18/hr — high.'
  'ⓘ Spending \$5.4/hr (10m) — moderate. · Cache active: saving ~19k tokens / 5 min.'
  'ⓘ Off-peak: full rate-limit headroom available.'

How it's computed:
  Scans the current ctx for insights, scores each by priority (critical ctx
  depletion > warning > info > off-peak fallback), and picks the top 2.
  Sources: rolling-window burn rate, cache delta, context-fill projection,
  peak/off-peak state, git state.

Colors:
  RED    — critical (context <30 min, burn >\$15/hr).
  YELLOW — warning (context <60 min, burn \$5-15/hr, peak hours).
  GREEN  — positive info (cache saving cost actively).
  DIM    — informational / off-peak fallback.

When it hides:
  Hidden if no insights trigger, or disabled via
  schedule.json 'features.show_narrator: false'."

# One-line purpose table (used by --explain with no arg)
declare -A SEG_ONELINER
SEG_ONELINER[peak_hours]="Visual indicator of peak-hour window (when Opus throttling kicks in)"
SEG_ONELINER[model]="Current model name (opus-4-7 / sonnet-4-6 / haiku-4-5)"
SEG_ONELINER[context]="Tokens used / total context window and percentage"
SEG_ONELINER[vim_mode]="Active Vim keybinding mode in Claude Code (NORMAL / INSERT)"
SEG_ONELINER[agent]="Sub-agent name when running inside a multi-agent task"
SEG_ONELINER[worktree]="Git worktree name when inside a linked worktree (wt:name)"
SEG_ONELINER[git_branch]="Currently checked-out git branch name"
SEG_ONELINER[git_dirty]="Working-tree status: 'clean', 'N unsaved', or 'M unpushed'"
SEG_ONELINER[cost]="Cumulative session cost in USD (e.g. \$15.83)"
SEG_ONELINER[effort]="Thinking-effort level from settings.json (e:LO / e:MED / e:HI)"
SEG_ONELINER[rate_limits]="5-hour and weekly rate-limit bars with reset timers"
SEG_ONELINER[env]="Execution environment: LOCAL (cyan) or REMOTE/SSH (magenta)"
SEG_ONELINER[burn_rate]="Spending rate over the last 10 min (e.g. \$6.3/hr); RED >\$50 projected"
SEG_ONELINER[cache_hit]="Cache hit ratio + recent cache-read delta (e.g. cache 96% ↑2.3k)"
SEG_ONELINER[context_depletion]="Minutes until context window fills at current rate (CTX full 37m)"
SEG_ONELINER[timeline]="Horizontal bar of today's peak/off-peak windows with 'now' marker"
SEG_ONELINER[metrics]="Combined spending + cache metrics line (full tier only)"
SEG_ONELINER[banner]="Broadcast message from remote schedule.json; hidden after expiry"
SEG_ONELINER[duration]="Wall-clock time elapsed since session start"
SEG_ONELINER[narrator]="Plain-language line (full tier) explaining what's happening right now"

# ── explain mode ─────────────────────────────────────────────────────────
do_explain() {
    local seg="${1:-}"
    if [[ -z "$seg" ]]; then
        # Print the full segment table
        printf '\n%bSegment Reference%b\n' "$BOLD" "$RST"
        printf '%s\n\n' "================="
        printf '%-22s %s\n' "SEGMENT" "PURPOSE"
        printf '%-22s %s\n' "──────────────────────" "──────────────────────────────────────────────────"
        local name
        for name in peak_hours model context vim_mode agent worktree git_branch git_dirty \
                    cost effort rate_limits env burn_rate cache_hit context_depletion \
                    timeline metrics banner duration; do
            local line="${SEG_ONELINER[$name]:-}"
            if [[ -n "$line" ]]; then
                printf '%-22s %s\n' "$name" "$line"
            fi
        done
        printf '\n%bTip:%b run '"'"'doctor.sh --explain <segment>'"'"' for a detailed breakdown.\n\n' "$BOLD" "$RST"
    else
        # Detailed explanation for a single segment
        if [[ -n "${SEG_DETAIL[$seg]:-}" ]]; then
            printf '\n%bSegment: %s%b\n' "$BOLD" "$seg" "$RST"
            printf '%s\n' "──────────────────────────────────────────────────"
            printf '%s\n\n' "${SEG_DETAIL[$seg]}"
        elif [[ -n "${SEG_ONELINER[$seg]:-}" ]]; then
            # Known segment but no long-form detail yet; show one-liner
            printf '\n%bSegment: %s%b\n' "$BOLD" "$seg" "$RST"
            printf '%s\n\n' "${SEG_ONELINER[$seg]}"
        else
            printf 'Unknown segment: %s\n' "$seg" >&2
            printf 'Run '"'"'doctor.sh --explain'"'"' (no arg) to list all segments.\n' >&2
        fi
    fi
    exit 0
}

# ── Flags ────────────────────────────────────────────────────────────────
MODE="report"   # report | json | fix
SEND_TELEMETRY=0
while [ $# -gt 0 ]; do
    case "$1" in
        --json)   MODE="json" ;;
        --fix)    MODE="fix" ;;
        --report) SEND_TELEMETRY=1 ;;
        --explain)
            # Colors must be set before do_explain; initialize them now.
            if [ ! -t 1 ]; then
                RST=""; DIM=""; BOLD=""; RED=""; YEL=""; GRN=""; CYA=""; MAG=""
            else
                RST=$'\033[0m'; DIM=$'\033[2m'; BOLD=$'\033[1m'
                RED=$'\033[31m'; YEL=$'\033[33m'; GRN=$'\033[32m'; CYA=$'\033[36m'; MAG=$'\033[35m'
            fi
            do_explain "${2:-}"
            ;;
        -h|--help)
            sed -n '3,18p' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *) echo "Unknown arg: $1" >&2; exit 0 ;;
    esac
    shift
done

# ── Paths & setup ────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CLAUDE_DIR="${CLAUDE_DIR:-$HOME/.claude}"
SETTINGS="$CLAUDE_DIR/settings.json"
CONFIG="$CLAUDE_DIR/statusline-config.json"

# Shared runtime resolver (handles WindowsApps stubs + portable locations).
# shellcheck source=../lib/resolve-runtime.sh
if [ -f "$REPO_ROOT/lib/resolve-runtime.sh" ]; then
    . "$REPO_ROOT/lib/resolve-runtime.sh"
else
    # Fallback: simple PATH lookup. Degrades gracefully if lib is missing.
    resolve_runtime() {
        local kind="$1"
        case "$kind" in
            python) for c in python3 python; do command -v "$c" 2>/dev/null && return 0; done ;;
            node)   command -v node 2>/dev/null && return 0 ;;
        esac
        return 1
    }
fi

# ── Colors (disabled for --json) ─────────────────────────────────────────
if [ "$MODE" = "json" ] || [ ! -t 1 ]; then
    RST=""; DIM=""; BOLD=""; RED=""; YEL=""; GRN=""; CYA=""; MAG=""
else
    RST=$'\033[0m'; DIM=$'\033[2m'; BOLD=$'\033[1m'
    RED=$'\033[31m'; YEL=$'\033[33m'; GRN=$'\033[32m'; CYA=$'\033[36m'; MAG=$'\033[35m'
fi

# Symbols (ASCII-safe; terminals without Unicode can still read the result)
OK="${GRN}\xe2\x9c\x93${RST}"     # ✓
WARN="${YEL}\xe2\x9a\xa0${RST}"   # ⚠
FAIL="${RED}\xe2\x9c\x97${RST}"   # ✗

# ── Result buffer ────────────────────────────────────────────────────────
# Each check appends a line: STATUS|ID|TITLE|DETAIL|FIXABLE|FIX_HINT
# Using | as delimiter keeps things readable; TITLE/DETAIL must not contain |.
RESULTS=()

add_result() {
    # $1=status(ok|warn|fail) $2=id $3=title $4=detail $5=fixable(0|1) $6=fix_hint
    RESULTS+=("$1|$2|$3|$4|$5|$6")
}

# ── OS detection ─────────────────────────────────────────────────────────
is_windows=0
case "$(uname -s 2>/dev/null)" in
    MINGW*|MSYS*|CYGWIN*) is_windows=1 ;;
esac
# Also treat native Windows (no uname) as Windows.
[ -n "${WINDIR:-}" ] && is_windows=1

# ── Helpers ──────────────────────────────────────────────────────────────
have_python() { resolve_runtime python; }
have_node()   { resolve_runtime node; }

# Extract a JSON field without requiring jq. Uses python when available,
# falls back to a minimal grep for the "statusLine".command string.
json_get_statusline_command() {
    local f="$1"
    local py
    py=$(have_python) || py=""
    if [ -n "$py" ] && [ -f "$f" ]; then
        "$py" - "$f" <<'PY' 2>/dev/null
import json, sys
try:
    with open(sys.argv[1], encoding="utf-8") as fh:
        data = json.load(fh)
    sl = data.get("statusLine") or {}
    print(sl.get("command", ""))
except Exception:
    pass
PY
        return
    fi
    # Fallback: naive grep. Works for single-line "command": "..." forms.
    grep -oE '"command"[[:space:]]*:[[:space:]]*"[^"]*"' "$f" 2>/dev/null \
        | head -1 | sed -E 's/.*"command"[[:space:]]*:[[:space:]]*"(.*)"/\1/'
}

# ── Check 1: settings.json statusLine present ───────────────────────────
check_settings() {
    if [ ! -f "$SETTINGS" ]; then
        add_result fail settings \
            "settings.json missing" \
            "$SETTINGS not found. Run install.sh to create it." \
            0 ""
        return
    fi
    local cmd
    cmd=$(json_get_statusline_command "$SETTINGS")
    if [ -z "$cmd" ]; then
        add_result fail settings \
            "No statusLine configured" \
            "settings.json has no statusLine stanza. Nothing will render." \
            1 "add-statusline"
        return
    fi
    add_result ok settings \
        "statusLine configured" \
        "$cmd" \
        0 ""
}

# ── Check 2: statusLine points at THIS project (not a hijack) ───────────
check_hijack() {
    local cmd
    cmd=$(json_get_statusline_command "$SETTINGS" 2>/dev/null)
    [ -z "$cmd" ] && return
    case "$cmd" in
        *token-optimizer*|*token_optimizer*)
            add_result fail hijack \
                "token-optimizer hijacked statusLine" \
                "Your statusLine command points to token-optimizer, not cc-2x-statusline. Installing token-optimizer overwrites the stanza silently." \
                1 "restore-statusline"
            ;;
        *claude-2x-statusline*|*cc-2x-statusline*|*statusline.sh*|*statusline.ps1*|*statusline-wrapper*)
            add_result ok hijack \
                "statusLine owned by cc-2x-statusline" \
                "" \
                0 ""
            ;;
        *)
            add_result warn hijack \
                "statusLine points elsewhere" \
                "Not cc-2x-statusline, not a known plugin. Intentional?" \
                0 ""
            ;;
    esac
}

# ── Check 3: Windows PATH-inline syntax (cmd.exe can't parse) ───────────
check_windows_path_inline() {
    [ "$is_windows" = "1" ] || return
    local cmd
    cmd=$(json_get_statusline_command "$SETTINGS" 2>/dev/null)
    [ -z "$cmd" ] && return
    # Pattern: starts with VAR=... before the real command, without wrapping
    # bash -c '...'. cmd.exe parses this as "find program named PATH=..." and
    # silently fails; the statusline just never appears.
    case "$cmd" in
        bash\ -c\ *) return ;;  # already wrapped, safe
        *=*\ bash\ *|*=*\ sh\ *)
            add_result fail windows_path_inline \
                "Windows: PATH=… inline env assignment won't run" \
                "cmd.exe can't parse bash-style 'VAR=val cmd'. Statusline silently fails. Switch to a wrapper script." \
                1 "wrap-command"
            ;;
    esac
}

# ── Check 4: statusline-config.json valid ────────────────────────────────
check_config() {
    if [ ! -f "$CONFIG" ]; then
        add_result warn config \
            "statusline-config.json missing" \
            "Engines will fall back to built-in defaults (tier=full, mode=full)." \
            1 "create-config"
        return
    fi
    local py tier=""
    py=$(have_python) || py=""
    if [ -n "$py" ]; then
        tier=$("$py" - "$CONFIG" <<'PY' 2>/dev/null
import json, sys
try:
    with open(sys.argv[1], encoding="utf-8") as f:
        d = json.load(f)
    print(d.get("tier", ""))
except Exception:
    sys.exit(2)
PY
)
        if [ $? -ne 0 ]; then
            add_result fail config \
                "statusline-config.json is invalid JSON" \
                "Engines will fall back to defaults, but you'll see errors in hooks." \
                0 ""
            return
        fi
    fi
    add_result ok config \
        "statusline-config.json present${tier:+ (tier=$tier)}" \
        "" 0 ""
}

# ── Check 5: runtime availability (python → node → bash) ─────────────────
check_runtime() {
    local py node
    py=$(have_python) || py=""
    node=$(have_node) || node=""

    if [ -n "$py" ]; then
        add_result ok runtime \
            "Python engine available" \
            "$py" 0 ""
    elif [ -n "$node" ]; then
        add_result warn runtime \
            "Python not found, using Node fallback" \
            "$node. Multi-line dashboard works on Node; some segments (vim_mode, agent) are Python-only." \
            0 ""
    else
        add_result warn runtime \
            "No Python or Node — bash fallback only" \
            "Bash engine renders single-line minimal tier only. Install Python 3.8+ or Node 18+ for the full dashboard." \
            0 ""
    fi
}

# ── Check 6: dry-run execution of statusLine command ────────────────────
check_execution() {
    local cmd
    cmd=$(json_get_statusline_command "$SETTINGS" 2>/dev/null)
    [ -z "$cmd" ] && return

    local fake_json='{"model":{"display_name":"Opus"},"workspace":{"current_dir":"'"$PWD"'"},"version":"2.1.0","output_style":{"name":"default"}}'
    local tmp_out tmp_err rc lines elapsed_start elapsed_end
    tmp_out=$(mktemp 2>/dev/null || echo "/tmp/sld.out.$$")
    tmp_err=$(mktemp 2>/dev/null || echo "/tmp/sld.err.$$")
    elapsed_start=$(date +%s%N 2>/dev/null || date +%s)

    # Run with a 10s wall-clock cap. GNU timeout / gtimeout / perl fallback.
    if command -v timeout >/dev/null 2>&1; then
        echo "$fake_json" | timeout 10 sh -c "$cmd" >"$tmp_out" 2>"$tmp_err"
        rc=$?
    elif command -v gtimeout >/dev/null 2>&1; then
        echo "$fake_json" | gtimeout 10 sh -c "$cmd" >"$tmp_out" 2>"$tmp_err"
        rc=$?
    else
        echo "$fake_json" | sh -c "$cmd" >"$tmp_out" 2>"$tmp_err"
        rc=$?
    fi

    elapsed_end=$(date +%s%N 2>/dev/null || date +%s)
    if [ "${#elapsed_end}" -gt 10 ]; then
        # nanoseconds available
        local ms=$(( (elapsed_end - elapsed_start) / 1000000 ))
    else
        local ms=$(( (elapsed_end - elapsed_start) * 1000 ))
    fi

    lines=$(wc -l <"$tmp_out" | tr -d ' ')
    # Strip ANSI for accurate emptiness detection
    local stripped
    stripped=$(sed -E 's/\x1b\[[0-9;]*[A-Za-z]//g' "$tmp_out" | tr -d '[:space:]')

    local detail="exit=$rc, ${lines} line(s), ${ms}ms"
    if [ -z "$stripped" ]; then
        add_result fail exec \
            "statusLine command produces no output" \
            "$detail. Claude Code will show a blank line. stderr: $(tr '\n' ' ' <"$tmp_err" | cut -c1-200)" \
            0 ""
    elif [ "$rc" -ne 0 ]; then
        add_result warn exec \
            "statusLine exit code $rc (output still rendered)" \
            "$detail. stderr: $(tr '\n' ' ' <"$tmp_err" | cut -c1-200)" \
            0 ""
    else
        add_result ok exec \
            "statusLine renders" \
            "$detail" 0 ""
    fi
    rm -f "$tmp_out" "$tmp_err"
}

# ── Check 7: git remote actually points at claude-2x-statusline ─────────
check_origin() {
    [ -d "$REPO_ROOT/.git" ] || return
    local url
    url=$(git -C "$REPO_ROOT" remote get-url origin 2>/dev/null) || return
    case "$url" in
        *claude-2x-statusline*)
            add_result ok origin \
                "local clone tracks claude-2x-statusline" \
                "$url" 0 ""
            ;;
        *)
            add_result warn origin \
                "local clone 'origin' points elsewhere" \
                "$url — auto-update would pull from this repo. Expected claude-2x-statusline." \
                0 ""
            ;;
    esac
}

# ── Check 8: redundant /statusline-* commands ────────────────────────────
check_redundant_commands() {
    local cmd_dir="$CLAUDE_DIR/commands"
    [ -d "$cmd_dir" ] || return
    local count
    count=$(ls "$cmd_dir"/statusline-*.md 2>/dev/null | wc -l | tr -d ' ')
    if [ "$count" -ge 3 ]; then
        add_result warn redundant_cmds \
            "$count /statusline-* commands installed" \
            "minimal/standard/full each duplicate most logic. Consider /statusline <tier>. (Cosmetic; not a fault.)" \
            0 ""
    fi
}

# ── Run all checks ───────────────────────────────────────────────────────
check_settings
check_hijack
check_windows_path_inline
check_config
check_runtime
check_execution
check_origin
check_redundant_commands

# ── Output ───────────────────────────────────────────────────────────────
count_ok=0; count_warn=0; count_fail=0; count_fixable=0
for r in "${RESULTS[@]}"; do
    s=${r%%|*}
    rest=${r#*|}
    fixable=$(echo "$rest" | awk -F'|' '{print $4}')
    case "$s" in
        ok)   count_ok=$((count_ok+1)) ;;
        warn) count_warn=$((count_warn+1)) ;;
        fail) count_fail=$((count_fail+1)) ;;
    esac
    [ "$fixable" = "1" ] && count_fixable=$((count_fixable+1))
done

if [ "$MODE" = "json" ]; then
    printf '{\n  "ok": %d, "warn": %d, "fail": %d, "fixable": %d,\n  "checks": [\n' \
        $count_ok $count_warn $count_fail $count_fixable
    local_i=0
    for r in "${RESULTS[@]}"; do
        status=${r%%|*}; rest=${r#*|}
        id=${rest%%|*}; rest=${rest#*|}
        title=${rest%%|*}; rest=${rest#*|}
        detail=${rest%%|*}; rest=${rest#*|}
        fixable=${rest%%|*}; rest=${rest#*|}
        hint=$rest
        esc() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'; }
        [ $local_i -gt 0 ] && printf ',\n'
        printf '    {"status":"%s","id":"%s","title":"%s","detail":"%s","fixable":%s,"fix":"%s"}' \
            "$status" "$(esc "$id")" "$(esc "$title")" "$(esc "$detail")" \
            "$([ "$fixable" = "1" ] && echo true || echo false)" \
            "$(esc "$hint")"
        local_i=$((local_i+1))
    done
    printf '\n  ]\n}\n'
else
    printf '\n%bClaude Code Statusline Doctor%b\n' "$BOLD" "$RST"
    printf '%s\n' "============================="
    for r in "${RESULTS[@]}"; do
        status=${r%%|*}; rest=${r#*|}
        id=${rest%%|*}; rest=${rest#*|}
        title=${rest%%|*}; rest=${rest#*|}
        detail=${rest%%|*}; rest=${rest#*|}
        case "$status" in
            ok)   printf "$OK %b%s%b\n" "$BOLD" "$title" "$RST" ;;
            warn) printf "$WARN %b%s%b\n" "$BOLD" "$title" "$RST" ;;
            fail) printf "$FAIL %b%s%b\n" "$BOLD" "$title" "$RST" ;;
        esac
        [ -n "$detail" ] && printf "  %b%s%b\n" "$DIM" "$detail" "$RST"
    done
    printf '\n%bSummary:%b %d ok, %d warn, %d fail' "$BOLD" "$RST" $count_ok $count_warn $count_fail
    [ $count_fixable -gt 0 ] && printf ' (%d fixable — re-run with --fix)' $count_fixable
    printf '\n\n'
fi

# ── Fix mode ─────────────────────────────────────────────────────────────
if [ "$MODE" = "fix" ]; then
    FIX_SCRIPT="$SCRIPT_DIR/fixes.sh"
    if [ ! -f "$FIX_SCRIPT" ]; then
        echo "Fix engine missing: $FIX_SCRIPT" >&2
        exit 0
    fi
    applied=0
    for r in "${RESULTS[@]}"; do
        status=${r%%|*}; rest=${r#*|}
        id=${rest%%|*}; rest=${rest#*|}
        title=${rest%%|*}; rest=${rest#*|}
        detail=${rest%%|*}; rest=${rest#*|}
        fixable=${rest%%|*}; rest=${rest#*|}
        hint=$rest
        [ "$fixable" = "1" ] || continue
        printf '\n%bFixable:%b %s\n' "$BOLD" "$RST" "$title"
        [ -n "$detail" ] && printf '  %s\n' "$detail"
        printf '  Proposed fix: %s\n' "$hint"
        printf '  Apply? [y/N] '
        read -r answer </dev/tty 2>/dev/null || answer="n"
        case "$answer" in
            y|Y|yes|YES)
                if bash "$FIX_SCRIPT" "$hint" "$SETTINGS" "$CONFIG" "$REPO_ROOT"; then
                    applied=$((applied+1))
                    printf '  %b%s%b applied.\n' "$GRN" "✓" "$RST"
                else
                    printf '  %b%s%b fix failed, skipping.\n' "$RED" "✗" "$RST"
                fi
                ;;
            *) printf '  skipped.\n' ;;
        esac
    done
    printf '\n%d fix(es) applied. Restart Claude Code for changes to take effect.\n' $applied
fi

# ── Telemetry (opt-in via --report only) ─────────────────────────────────
if [ "$SEND_TELEMETRY" = "1" ]; then
    # Anonymous: SHA256 of hostname+whoami truncated to 16 chars. No filenames,
    # no command contents, no tokens — only aggregate counts + check IDs + OS.
    ids_fail=""
    for r in "${RESULTS[@]}"; do
        status=${r%%|*}; rest=${r#*|}
        id=${rest%%|*}
        [ "$status" = "fail" ] && ids_fail="$ids_fail $id"
    done
    uid=$(printf '%s' "$(hostname 2>/dev/null):$(whoami 2>/dev/null)" | sha256sum 2>/dev/null | cut -c1-16)
    os=$(uname -s 2>/dev/null | tr A-Z a-z)
    payload=$(printf '{"id":"%s","v":"doctor-1","os":"%s","ok":%d,"warn":%d,"fail":%d,"failed_ids":"%s","event":"doctor"}' \
        "$uid" "$os" $count_ok $count_warn $count_fail "$(echo "$ids_fail" | sed 's/^ //')")
    if command -v curl >/dev/null 2>&1; then
        curl -s -o /dev/null --max-time 3 -X POST -H 'Content-Type: application/json' \
            -d "$payload" "https://statusline-telemetry.nadavf.workers.dev/ping" &
    fi
fi

exit 0
