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
#
# Exit: 0 always. Non-zero exit would block Claude Code session hooks.

set -u

# ── Flags ────────────────────────────────────────────────────────────────
MODE="report"   # report | json | fix
SEND_TELEMETRY=0
while [ $# -gt 0 ]; do
    case "$1" in
        --json)   MODE="json" ;;
        --fix)    MODE="fix" ;;
        --report) SEND_TELEMETRY=1 ;;
        -h|--help)
            sed -n '3,16p' "$0" | sed 's/^# \{0,1\}//'
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
