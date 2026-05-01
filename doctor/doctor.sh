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
        printf '\n%bNote:%b narrator is no longer a statusline segment — it runs as a SessionStart/UserPromptSubmit hook. Use '"'"'check_narrator_hook'"'"' or run doctor.sh to verify it is wired correctly.\n' "$BOLD" "$RST"
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
while [ $# -gt 0 ]; do
    case "$1" in
        --json)   MODE="json" ;;
        --fix)    MODE="fix" ;;
        --report) : ;; # No-op: telemetry is now always-on unless opted out via config
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

# ── 3-tier privacy / telemetry level ────────────────────────────────────
# Reads ~/.claude/statusline-config.json (same file used by engines).
# Decision tree:
#   telemetry == false           → TELEMETRY_LEVEL=off
#   diagnostics == "minimal"     → TELEMETRY_LEVEL=minimal
#   diagnostics == "full" or missing → TELEMETRY_LEVEL=full
_read_telemetry_level() {
    local cfg="$CONFIG"
    if [ ! -f "$cfg" ]; then
        echo "full"; return
    fi
    # Try python for reliable JSON parsing.
    # Probe candidates in order; skip WindowsApps stubs (exit 49 / "Microsoft Store").
    local py=""
    local _candidate _out _rc
    for _candidate in python3 python; do
        local _path
        _path=$(command -v "$_candidate" 2>/dev/null) || continue
        # Quick smoke-test: real Python prints a version; Store stubs exit non-zero.
        _out=$("$_path" -c "print('ok')" 2>/dev/null)
        _rc=$?
        if [ "$_rc" -eq 0 ] && [ "$_out" = "ok" ]; then
            py="$_path"; break
        fi
    done
    if [ -n "$py" ]; then
        local _result
        _result=$("$py" - "$cfg" <<'PY' 2>/dev/null
import json, sys
try:
    with open(sys.argv[1], encoding="utf-8") as fh:
        d = json.load(fh)
    tele = d.get("telemetry", True)
    if tele is False or str(tele).lower() == "false":
        print("off")
    elif d.get("diagnostics") == "minimal":
        print("minimal")
    else:
        print("full")
except Exception:
    print("full")
PY
)
        if [ -n "$_result" ]; then
            echo "$_result"; return
        fi
    fi
    # grep fallback (no working python available)
    if grep -q '"telemetry"[[:space:]]*:[[:space:]]*false' "$cfg" 2>/dev/null; then
        echo "off"
    elif grep -q '"diagnostics"[[:space:]]*:[[:space:]]*"minimal"' "$cfg" 2>/dev/null; then
        echo "minimal"
    else
        echo "full"
    fi
}
TELEMETRY_LEVEL=$(_read_telemetry_level)

# ── Stable per-machine diagnostic code ──────────────────────────────────
# sha256(hostname:user)[:8]  — anonymous, stable across runs.
_make_diag_code() {
    local raw
    raw="$(hostname 2>/dev/null):$(whoami 2>/dev/null)"
    if command -v sha256sum >/dev/null 2>&1; then
        printf '%s' "$raw" | sha256sum | cut -c1-8
    elif command -v shasum >/dev/null 2>&1; then
        printf '%s' "$raw" | shasum -a 256 | cut -c1-8
    else
        # python fallback — skip WindowsApps stubs
        local py="" _candidate _path _out _rc
        for _candidate in python3 python; do
            _path=$(command -v "$_candidate" 2>/dev/null) || continue
            _out=$("$_path" -c "print('ok')" 2>/dev/null); _rc=$?
            if [ "$_rc" -eq 0 ] && [ "$_out" = "ok" ]; then
                py="$_path"; break
            fi
        done
        if [ -n "$py" ]; then
            printf '%s' "$raw" | "$py" -c \
                "import sys,hashlib; print(hashlib.sha256(sys.stdin.read().encode()).hexdigest()[:8])"
        else
            printf '00000000'
        fi
    fi
}
DIAG_CODE=$(_make_diag_code)

# ── Sanitization ─────────────────────────────────────────────────────────
# sanitize_report <string> → stdout
# Replaces home paths and real hostname/username with placeholders so no
# personally identifying paths are sent in the full diagnostic report.
sanitize_report() {
    local input="$1"
    local _home _user _host

    _home="$HOME"
    _user="$(whoami 2>/dev/null)"
    _host="$(hostname 2>/dev/null)"

    # 1. Literal $HOME value  → ~/
    if [ -n "$_home" ]; then
        input="${input//$_home/\~}"
    fi

    # 2. Windows-style /c/Users/NAME/ (Git Bash MINGW path) → ~/
    if [ -n "$_user" ]; then
        input=$(printf '%s' "$input" | sed "s|/[a-zA-Z]/[Uu]sers/$_user/|~/|g")
    fi

    # 3. Remaining ~/ sequences — already canonical; nothing to do.

    # 4. Actual username occurrences (case-insensitive)
    if [ -n "$_user" ]; then
        input=$(printf '%s' "$input" | sed "s|$_user|<user>|gI" 2>/dev/null \
                || printf '%s' "$input" | sed "s|$_user|<user>|g")
    fi

    # 5. Actual hostname occurrences
    if [ -n "$_host" ]; then
        input=$(printf '%s' "$input" | sed "s|$_host|<host>|g")
    fi

    printf '%s' "$input"
}

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
#
# Hijack = another plugin overwrote our statusLine stanza without asking.
# Logic:
#   1. If it points at us (cc-2x-statusline / statusline.sh / wrapper) → ok.
#   2. If a *known* statusline-hijacker plugin pattern → fail + offer restore.
#   3. If our install marker exists AND statusLine now points elsewhere →
#      definitely a hijack (we were installed, now we're not) → fail + restore.
#   4. Otherwise (unknown command, no marker) → warn. User may have a
#      custom statusline on purpose.
check_hijack() {
    local cmd
    cmd=$(json_get_statusline_command "$SETTINGS" 2>/dev/null)
    [ -z "$cmd" ] && return

    # 1. Known-us patterns
    case "$cmd" in
        *claude-2x-statusline*|*cc-2x-statusline*|*statusline.sh*|*statusline.ps1*|*statusline-wrapper*)
            add_result ok hijack \
                "statusLine owned by cc-2x-statusline" \
                "" \
                0 ""
            return
            ;;
    esac

    # 2. Known-bad patterns. Extend this list when new hijackers are observed.
    local hijacker_pattern=""
    case "$cmd" in
        *token-optimizer*|*token_optimizer*)
            hijacker_pattern="token-optimizer"
            ;;
        *claude-goblin*)
            hijacker_pattern="claude-goblin"
            ;;
        *ccstatusline*|*cc-statusline*)
            hijacker_pattern="ccstatusline (another statusline plugin)"
            ;;
    esac
    if [ -n "$hijacker_pattern" ]; then
        add_result fail hijack \
            "$hijacker_pattern hijacked statusLine" \
            "Your statusLine command points to $hijacker_pattern, not cc-2x-statusline. Installing another statusline plugin overwrites the stanza silently. Run with --fix to restore." \
            1 "restore-statusline"
        return
    fi

    # 3. Marker-based detection: we were installed but are no longer wired.
    local install_marker="$HOME/.claude/cc-2x-statusline"
    if [ -d "$install_marker" ]; then
        add_result fail hijack \
            "Unknown plugin hijacked statusLine" \
            "cc-2x-statusline is installed at ~/.claude/cc-2x-statusline but settings.json points elsewhere: $cmd. Something else overwrote the stanza. Run with --fix to restore." \
            1 "restore-statusline"
        return
    fi

    # 4. Otherwise — unknown command, no install marker → possibly intentional
    add_result warn hijack \
        "statusLine points elsewhere" \
        "Points to: $cmd. Not cc-2x-statusline, no known-hijacker signature, no install marker. If this is a custom statusline on purpose — fine. Otherwise, run with --fix to reclaim." \
        0 ""
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

# ── Check 9: narrator hooks installed + wired ────────────────────────────
check_narrator_hook() {
    local hooks_dir="$CLAUDE_DIR/cc-2x-statusline/hooks"
    local hook_ss="$hooks_dir/narrator-session-start.sh"
    local hook_ps="$hooks_dir/narrator-prompt-submit.sh"
    local memory_file="$CLAUDE_DIR/narrator-memory.json"

    # 1. Session-start hook: must exist and be executable
    if [ ! -f "$hook_ss" ]; then
        add_result fail narrator_hook \
            "Narrator: narrator-session-start.sh not installed" \
            "$hook_ss missing. Re-run install.sh to install narrator hooks." \
            0 ""
        return
    fi
    if [ ! -x "$hook_ss" ]; then
        add_result warn narrator_hook \
            "Narrator: narrator-session-start.sh not executable" \
            "Run: chmod +x $hook_ss" \
            0 ""
        return
    fi

    # 2. Prompt-submit hook: must exist
    if [ ! -f "$hook_ps" ]; then
        add_result warn narrator_hook \
            "Narrator: narrator-prompt-submit.sh not installed" \
            "$hook_ps missing. Re-run install.sh." \
            0 ""
        return
    fi

    # 3. Narrator hooks wired into settings.json
    local wired=0
    local py
    py=$(have_python) || py=""
    if [ -n "$py" ] && [ -f "$SETTINGS" ]; then
        # Read settings.json via shell redirect (stdin) instead of passing the path
        # as argv. This avoids MSYS-vs-Windows path translation when the bundled
        # python is a Windows-native interpreter on Git Bash (where /c/... is not
        # a valid path to a Windows process).
        wired=$("$py" -c '
import json, sys
try:
    s = json.load(sys.stdin)
    hooks = s.get("hooks", {})
    want = {sys.argv[1], sys.argv[2]}
    found = set()
    # Claude Code stores hooks as { event: [ { matcher, hooks: [ { type, command } ] } ] }.
    # Older / flatter shapes are handled too for backwards compatibility.
    for entries in hooks.values():
        if not isinstance(entries, list):
            continue
        for e in entries:
            if isinstance(e, str):
                found.add(e)
            elif isinstance(e, dict):
                if "command" in e and isinstance(e["command"], str):
                    found.add(e["command"])
                inner = e.get("hooks", [])
                if isinstance(inner, list):
                    for h in inner:
                        if isinstance(h, dict) and isinstance(h.get("command"), str):
                            found.add(h["command"])
                        elif isinstance(h, str):
                            found.add(h)
    import re
    def normalize(s):
        # Strip optional `bash ` invocation prefix.
        if s.startswith("bash "):
            s = s.split(" ", 1)[1]
        # Normalize Git Bash MSYS path (/c/Users/...) to Windows-style (C:/Users/...).
        # MSYS auto-translates argv on Windows, but JSON values are stored verbatim,
        # so the two sides need to be brought into the same canonical form.
        m = re.match(r"^/([a-zA-Z])/(.*)$", s)
        if m:
            s = m.group(1).upper() + ":/" + m.group(2)
        # Case-insensitive on Windows drive letters.
        return s.replace("\\", "/").lower()
    found_norm = {normalize(c) for c in found}
    want_norm = {normalize(c) for c in want}
    print("1" if want_norm.issubset(found_norm) else "0")
except Exception:
    print("0")
' "$hook_ss" "$hook_ps" < "$SETTINGS" 2>/dev/null)
    fi
    if [ "${wired:-0}" != "1" ]; then
        add_result warn narrator_hook \
            "Narrator hooks not wired in settings.json" \
            "Re-run install.sh to wire SessionStart + UserPromptSubmit hooks." \
            0 ""
        return
    fi

    # 4. Memory file writable (file itself, or parent dir)
    local mem_ok=0
    if [ -f "$memory_file" ]; then
        [ -w "$memory_file" ] && mem_ok=1
    else
        [ -w "$(dirname "$memory_file")" ] && mem_ok=1
    fi
    if [ "$mem_ok" = "0" ]; then
        add_result warn narrator_hook \
            "Narrator memory file not writable" \
            "$memory_file (or its parent dir) is not writable. Narrator will not persist state." \
            0 ""
        return
    fi

    add_result ok narrator_hook \
        "Narrator hooks installed and wired" \
        "$hook_ss + $hook_ps → settings.json hooks" \
        0 ""
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
check_narrator_hook

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

# ── Telemetry footer line ────────────────────────────────────────────────
# Always print unless MODE=json (the diagnostic code line goes to stdout).
if [ "$MODE" != "json" ]; then
    if [ "$TELEMETRY_LEVEL" = "off" ]; then
        printf 'Telemetry: off — no diagnostics sent.\n\n'
    else
        printf 'Diagnostic code: %s (telemetry: %s — see README to change privacy)\n\n' \
            "$DIAG_CODE" "$TELEMETRY_LEVEL"
    fi
fi

# ── Network helper ───────────────────────────────────────────────────────
# _http_post <url> <json_payload>
# Tries curl, then wget, then python. Runs in background; caller does not wait.
_http_post() {
    local url="$1"
    local data="$2"
    if command -v curl >/dev/null 2>&1; then
        curl -s -o /dev/null --max-time 5 -X POST \
            -H 'Content-Type: application/json' \
            -d "$data" "$url" &
    elif command -v wget >/dev/null 2>&1; then
        wget -q -O /dev/null --timeout=5 \
            --post-data="$data" \
            --header='Content-Type: application/json' \
            "$url" &
    else
        # python fallback — skip WindowsApps stubs
        local py="" _candidate _path _out _rc
        for _candidate in python3 python; do
            _path=$(command -v "$_candidate" 2>/dev/null) || continue
            _out=$("$_path" -c "print('ok')" 2>/dev/null); _rc=$?
            if [ "$_rc" -eq 0 ] && [ "$_out" = "ok" ]; then
                py="$_path"; break
            fi
        done
        if [ -n "$py" ]; then
            "$py" - "$url" "$data" <<'PY' &
import sys, urllib.request, json as _json
try:
    req = urllib.request.Request(
        sys.argv[1],
        data=sys.argv[2].encode(),
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    urllib.request.urlopen(req, timeout=5)
except Exception:
    pass
PY
        fi
    fi
}

# ── Summary ping (minimal + full) ────────────────────────────────────────
# Sends aggregate counts + failed check IDs. Same as the old --report ping,
# now triggered automatically whenever TELEMETRY_LEVEL != off.
_send_summary_ping() {
    local ids_fail=""
    for r in "${RESULTS[@]}"; do
        local _s=${r%%|*}; local _rest=${r#*|}
        local _id=${_rest%%|*}
        [ "$_s" = "fail" ] && ids_fail="$ids_fail $_id"
    done
    ids_fail=$(printf '%s' "$ids_fail" | sed 's/^ //')
    local os
    os=$(uname -s 2>/dev/null | tr A-Z a-z)
    local payload
    payload=$(printf '{"id":"%s","v":"doctor-1","os":"%s","ok":%d,"warn":%d,"fail":%d,"failed_ids":"%s","event":"doctor"}' \
        "$DIAG_CODE" "$os" "$count_ok" "$count_warn" "$count_fail" "$ids_fail")
    _http_post "https://statusline-telemetry.nadavf.workers.dev/ping" "$payload"
}

# ── Full diagnostic upload (full level, failures only) ───────────────────
_send_full_report() {
    # Build checks array for JSON
    local checks_json="["
    local first=1
    for r in "${RESULTS[@]}"; do
        local _status=${r%%|*}; local _rest=${r#*|}
        local _id=${_rest%%|*}; _rest=${_rest#*|}
        local _title=${_rest%%|*}; _rest=${_rest#*|}
        local _detail=${_rest%%|*}
        _detail=$(sanitize_report "$_detail")
        # Escape for JSON
        _id=$(printf '%s' "$_id" | sed 's/\\/\\\\/g; s/"/\\"/g')
        _title=$(printf '%s' "$_title" | sed 's/\\/\\\\/g; s/"/\\"/g')
        _detail=$(printf '%s' "$_detail" | sed 's/\\/\\\\/g; s/"/\\"/g')
        [ "$first" = "1" ] || checks_json="$checks_json,"
        if [ "$_status" = "fail" ]; then
            checks_json="${checks_json}{\"id\":\"$_id\",\"status\":\"$_status\",\"message\":\"$_title — $_detail\"}"
        else
            checks_json="${checks_json}{\"id\":\"$_id\",\"status\":\"$_status\"}"
        fi
        first=0
    done
    checks_json="$checks_json]"

    # Build full text report (sanitized)
    local report_text
    report_text=$(sanitize_report "$(
        for r in "${RESULTS[@]}"; do
            local _s=${r%%|*}; local _rest=${r#*|}
            local _id=${_rest%%|*}; _rest=${_rest#*|}
            local _title=${_rest%%|*}; _rest=${_rest#*|}
            local _detail=${_rest%%|*}
            printf '%s %s: %s\n' "$_s" "$_id" "$_title"
            [ -n "$_detail" ] && printf '  %s\n' "$_detail"
        done
        printf '\nenv: os=%s diag=%s\n' "$(uname -s 2>/dev/null)" "$DIAG_CODE"
    )")

    # Escape report_text for JSON embedding
    report_text=$(printf '%s' "$report_text" | sed 's/\\/\\\\/g; s/"/\\"/g; s/$/\\n/' | tr -d '\n')
    report_text="${report_text%\\n}"  # trim trailing \n

    local os plugin_version
    os=$(uname -s 2>/dev/null | tr A-Z a-z)
    plugin_version="2.2.0"

    # Determine active runtime label
    local runtime="bash"
    if command -v python3 >/dev/null 2>&1 || command -v python >/dev/null 2>&1; then
        runtime="python"
    elif command -v node >/dev/null 2>&1; then
        runtime="node"
    fi

    local payload
    payload=$(printf '{"code":"%s","v":"doctor-2","os":"%s","report":"%s","checks":%s,"meta":{"plugin_version":"%s","runtime":"%s","tier":"full"}}' \
        "$DIAG_CODE" "$os" "$report_text" "$checks_json" "$plugin_version" "$runtime")

    _http_post "https://statusline-telemetry.nadavf.workers.dev/doctor/submit" "$payload"
}

# ── Dispatch telemetry based on level ────────────────────────────────────
if [ "$TELEMETRY_LEVEL" != "off" ]; then
    _send_summary_ping
    if [ "$TELEMETRY_LEVEL" = "full" ] && [ "$count_fail" -gt 0 ]; then
        _send_full_report
    fi
fi

exit 0
