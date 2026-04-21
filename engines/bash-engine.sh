#!/usr/bin/env bash
# Claude Code statusline — pure bash fallback (minimal features only)
# No Python, no Node.js, no jq needed. Last resort.
# v2.1 — Peak hours with auto-timezone. Supports: peak_hours + git

RST='\033[0m'; BOLD='\033[1m'; DIM='\033[2m'
GREEN='\033[32m'; YELLOW='\033[33m'; CYAN='\033[36m'; MAGENTA='\033[35m'
BG_GREEN='\033[38;5;255;48;5;28m'; BG_YELLOW='\033[38;5;16;48;5;220m'
BG_RED='\033[38;5;255;48;5;124m'; BG_GRAY='\033[48;5;236m'
WHITE='\033[38;2;220;220;220m'

ENGINE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_ROOT="$(cd "$ENGINE_DIR/.." && pwd)"
PACKAGE_JSON="$INSTALL_ROOT/package.json"
TELEMETRY_ID_FILE="$HOME/.claude/.statusline-telemetry-id"

get_telemetry_id() {
    local id=""

    mkdir -p "$HOME/.claude" >/dev/null 2>&1 || true
    if [ -f "$TELEMETRY_ID_FILE" ]; then
        id=$(tr -d '\r\n' < "$TELEMETRY_ID_FILE" | tr '[:upper:]' '[:lower:]')
        if printf '%s' "$id" | grep -Eq '^[0-9a-f]{16}$'; then
            printf '%s' "$id"
            return 0
        fi
    fi

    if command -v python3 >/dev/null 2>&1; then
        id=$(python3 - <<'PY'
import secrets

print(secrets.token_hex(8))
PY
)
    elif command -v python >/dev/null 2>&1; then
        id=$(python - <<'PY'
import secrets

print(secrets.token_hex(8))
PY
)
    elif command -v openssl >/dev/null 2>&1; then
        id=$(openssl rand -hex 8 2>/dev/null | tr -d '\r\n')
    elif [ -r /dev/urandom ]; then
        id=$(od -An -N8 -tx1 /dev/urandom 2>/dev/null | tr -d ' \r\n')
    fi

    if printf '%s' "$id" | grep -Eq '^[0-9a-f]{16}$'; then
        umask 177
        printf '%s' "$id" > "$TELEMETRY_ID_FILE"
        chmod 600 "$TELEMETRY_ID_FILE" 2>/dev/null || true
        printf '%s' "$id"
        return 0
    fi

    return 1
}

# ── Telemetry heartbeat (daily, fire-and-forget) ──
HEARTBEAT_FILE="$HOME/.claude/.statusline-heartbeat"
_telemetry_opted_out=0
if [ "${STATUSLINE_DISABLE_TELEMETRY:-0}" = "1" ]; then
    _telemetry_opted_out=1
elif [ -f "$HOME/.claude/statusline-config.json" ]; then
    case "$(grep -o '"telemetry"[[:space:]]*:[[:space:]]*false' "$HOME/.claude/statusline-config.json" 2>/dev/null)" in
        *false*) _telemetry_opted_out=1 ;;
    esac
fi
_today=$(date -u +%Y-%m-%d)
_do_ping=0
if [ "$_telemetry_opted_out" -eq 0 ] && [ ! -f "$HEARTBEAT_FILE" ]; then _do_ping=1
elif [ "$_telemetry_opted_out" -eq 0 ] && [ "$(cat "$HEARTBEAT_FILE" 2>/dev/null)" != "$_today" ]; then _do_ping=1
fi
if [ "$_do_ping" -eq 1 ]; then
    _uid=$(get_telemetry_id 2>/dev/null || true)
    if [ -n "$_uid" ]; then
        echo "$_today" > "$HEARTBEAT_FILE"
        curl -s -o /dev/null --max-time 3 -X POST -H 'Content-Type: application/json' \
            -d "{\"id\":\"$_uid\",\"v\":\"2.1\",\"engine\":\"bash\",\"tier\":\"minimal\",\"os\":\"$(uname -s | tr A-Z a-z)\",\"event\":\"heartbeat\"}" \
            "https://statusline-telemetry.nadavf.workers.dev/ping" &
    fi
fi

# ── Local time & timezone offset ──
local_hour=$(date +%-H 2>/dev/null || date +%H)
local_min=$(date +%-M 2>/dev/null || date +%M)
dow=$(date +%u)  # 1=Mon, 7=Sun

# UTC offset in hours (handles DST automatically via system timezone)
# Parse +HHMM / -HHMM format from date +%z
tz_str=$(date +%z 2>/dev/null)
tz_sign="${tz_str:0:1}"
tz_hh="${tz_str:1:2}"
tz_mm="${tz_str:3:2}"
tz_hh=$((10#$tz_hh))
tz_mm=$((10#$tz_mm))
utc_offset_sec=$(( (tz_hh * 3600 + tz_mm * 60) ))
[ "$tz_sign" = "-" ] && utc_offset_sec=$(( -utc_offset_sec ))
local_offset_hours=$(( utc_offset_sec / 3600 ))

parse_offset_hours() {
    local tz_name="$1"
    local offset=""
    local sign hh

    if [ -n "$tz_name" ]; then
        offset=$(TZ="$tz_name" date +%z 2>/dev/null || true)
    else
        offset=$(date +%z 2>/dev/null || true)
    fi

    case "$offset" in
        [+-][0-9][0-9][0-9][0-9])
            sign=${offset:0:1}
            hh=${offset:1:2}
            hh=$((10#$hh))
            [ "$sign" = "-" ] && hh=$(( -hh ))
            printf '%s\n' "$hh"
            return 0
            ;;
    esac

    return 1
}

csv_has_day() {
    case ",$1," in
        *",$2,"*) return 0 ;;
        *) return 1 ;;
    esac
}

floor_div() {
    local num="$1" den="$2"
    if [ "$num" -ge 0 ]; then
        echo $(( num / den ))
    else
        echo $(( - (( -num + den - 1 ) / den ) ))
    fi
}

mod_positive() {
    local num="$1" den="$2" result
    result=$(( num % den ))
    [ "$result" -lt 0 ] && result=$(( result + den ))
    echo "$result"
}

shift_weekday() {
    local day="$1" delta="$2"
    echo $(( ((day - 1 + delta) % 7 + 7) % 7 + 1 ))
}

shift_days_csv() {
    local csv="$1" delta="$2" out="" day shifted
    local old_ifs="$IFS"
    IFS=',' read -r -a _days <<< "$csv"
    IFS="$old_ifs"
    for day in "${_days[@]}"; do
        [ -n "$day" ] || continue
        shifted=$(shift_weekday "$day" "$delta")
        out="${out}${out:+,}${shifted}"
    done
    printf '%s' "$out"
}

mins_until_next_peak() {
    local current_day="$1" current_mins="$2" start_mins="$3" days_csv="$4"
    local offset next_day
    for offset in 1 2 3 4 5 6 7; do
        next_day=$(( ((current_day - 1 + offset) % 7) + 1 ))
        if csv_has_day "$days_csv" "$next_day"; then
            echo $(( (1440 - current_mins) + (offset - 1) * 1440 + start_mins ))
            return 0
        fi
    done
    echo 0
}

# ── Remote schedule (try cached, skip fetch in bash for speed) ──
SCHEDULE_CACHE="$HOME/.claude/statusline-schedule.json"
peak_start_h=5
peak_end_h=11
peak_tz="America/Los_Angeles"
peak_enabled=1
peak_days_csv="1,2,3,4,5"

if [ -f "$SCHEDULE_CACHE" ]; then
    if command -v python3 >/dev/null 2>&1; then
        _sched_out="$(SCHEDULE_CACHE_PATH="$SCHEDULE_CACHE" python3 -c "
import json, os
try:
    with open(os.environ['SCHEDULE_CACHE_PATH'], encoding='utf-8') as handle:
        d=json.load(handle)
    p=d.get('peak',{})
    print(p.get('start',5))
    print(p.get('end',11))
    print(p.get('tz','America/Los_Angeles'))
    print(1 if p.get('enabled',True) else 0)
    print(','.join(str(int(x)) for x in p.get('days',[1,2,3,4,5])))
except: pass
" 2>/dev/null)"
        # Read exactly 5 lines; validate each before assigning
        {
            IFS= read -r _v_start
            IFS= read -r _v_end
            IFS= read -r _v_tz
            IFS= read -r _v_enabled
            IFS= read -r _v_days
        } <<< "$_sched_out"
        # Only assign if values look sane (integers / safe string)
        [[ "$_v_start"   =~ ^[0-9]+$ ]]          && peak_start_h="$_v_start"
        [[ "$_v_end"     =~ ^[0-9]+$ ]]          && peak_end_h="$_v_end"
        [[ "$_v_tz"      =~ ^[A-Za-z/_+-]+$ ]]   && peak_tz="$_v_tz"
        [[ "$_v_enabled" =~ ^[01]$ ]]            && peak_enabled="$_v_enabled"
        [[ "$_v_days"    =~ ^[0-9,]+$ ]]         && peak_days_csv="$_v_days"
        unset _sched_out _v_start _v_end _v_tz _v_enabled _v_days
    else
        _days_csv=$(grep -o '"days"[[:space:]]*:[[:space:]]*\[[^]]*\]' "$SCHEDULE_CACHE" 2>/dev/null | head -1 | sed -E 's/.*\[([^]]*)\].*/\1/' | tr -d ' \r\n')
        [[ "$_days_csv" =~ ^[0-9,]+$ ]] && peak_days_csv="$_days_csv"
        unset _days_csv
    fi
fi

extract_json_string() {
    local key="$1"
    local file="$2"
    [ -f "$file" ] || return 0
    grep -o '"'"$key"'"[[:space:]]*:[[:space:]]*"[^"]*"' "$file" 2>/dev/null | head -1 | sed -E 's/.*"([^"]*)"/\1/'
}

version_lt() {
    local left="$1"
    local right="$2"
    local IFS=.
    local -a left_parts=() right_parts=()
    local max_len=0
    local index left_part right_part

    [ -n "$left" ] || return 1
    [ -n "$right" ] || return 1
    [ "$left" != "$right" ] || return 1

    read -r -a left_parts <<< "$left"
    read -r -a right_parts <<< "$right"
    max_len=${#left_parts[@]}
    [ ${#right_parts[@]} -gt "$max_len" ] && max_len=${#right_parts[@]}

    for ((index = 0; index < max_len; index++)); do
        left_part="${left_parts[index]:-0}"
        right_part="${right_parts[index]:-0}"
        left_part="${left_part//[^0-9]/}"
        right_part="${right_part//[^0-9]/}"
        [ -n "$left_part" ] || left_part=0
        [ -n "$right_part" ] || right_part=0
        if [ "$left_part" -lt "$right_part" ]; then
            return 0
        fi
        if [ "$left_part" -gt "$right_part" ]; then
            return 1
        fi
    done

    return 1
}

local_version="$(extract_json_string version "$PACKAGE_JSON")"
latest_version="$(extract_json_string latest_version "$SCHEDULE_CACHE")"
minimum_version="$(extract_json_string minimum_version "$SCHEDULE_CACHE")"
release_notice=""

if version_lt "$local_version" "$minimum_version"; then
    release_target="$latest_version"
    [ -n "$release_target" ] || release_target="$minimum_version"
    release_notice="${BG_RED} Update required v${release_target} ${RST}"
elif version_lt "$local_version" "$latest_version"; then
    release_notice="${BG_YELLOW} Update available v${latest_version} ${RST}"
fi

# ── Determine source timezone offset ──
if [ "$peak_tz" = "UTC" ] || [ "$peak_tz" = "Etc/UTC" ] || [ "$peak_tz" = "GMT" ]; then
    src_offset=0
else
    src_offset=$(parse_offset_hours "$peak_tz" 2>/dev/null || echo -8)
fi

# ── Convert peak hours to local time ──
raw_start_local=$(( peak_start_h - src_offset + local_offset_hours ))
peak_day_offset=$(floor_div "$raw_start_local" 24)
peak_start_local=$(mod_positive "$raw_start_local" 24)
peak_end_local=$(mod_positive $(( peak_end_h - src_offset + local_offset_hours )) 24)
effective_peak_days_csv=$(shift_days_csv "$peak_days_csv" "$peak_day_offset")

# ── Format hours for display ──
fmt_hour() {
    local h=$(( $1 % 24 ))
    local ampm="am"
    [ "$h" -ge 12 ] && ampm="pm"
    local dh=$(( h % 12 ))
    [ "$dh" -eq 0 ] && dh=12
    echo "${dh}${ampm}"
}

# ── Peak hours check ──
is_peak=0
now_mins=$(( local_hour * 60 + local_min ))
peak_s_mins=$(( peak_start_local * 60 ))
peak_e_mins=$(( peak_end_local * 60 ))

# Check if today or previous day (for midnight spillover) is a peak day
prev_dow=$(( dow == 1 ? 7 : dow - 1 ))
is_peak_day=0; prev_peak_day=0
csv_has_day "$effective_peak_days_csv" "$dow" && is_peak_day=1
csv_has_day "$effective_peak_days_csv" "$prev_dow" && prev_peak_day=1

# A previous peak day only matters when the peak actually crosses midnight
# AND we're still inside the spillover window. Otherwise Saturday morning
# (Fri peak ended hours ago) would incorrectly enter the weekday branch and
# fall through without setting mins_until → "Off-Peak" with no countdown.
in_spillover=0
if [ "$prev_peak_day" -eq 1 ] && [ "$peak_e_mins" -lt "$peak_s_mins" ] && [ "$now_mins" -lt "$peak_e_mins" ]; then
    in_spillover=1
fi

if [ "$is_peak_day" -eq 1 ] || [ "$in_spillover" -eq 1 ]; then
    if [ "$peak_e_mins" -gt "$peak_s_mins" ]; then
        # Normal case (no midnight crossing)
        if [ "$now_mins" -ge "$peak_s_mins" ] && [ "$now_mins" -lt "$peak_e_mins" ]; then
            is_peak=1
            mins_left=$(( peak_e_mins - now_mins ))
        elif [ "$now_mins" -lt "$peak_s_mins" ]; then
            mins_until=$(( peak_s_mins - now_mins ))
        else
            mins_until=$(mins_until_next_peak "$dow" "$now_mins" "$peak_s_mins" "$effective_peak_days_csv")
        fi
    else
        # Crosses midnight — check spillover from previous day
        if [ "$is_peak_day" -eq 1 ] && [ "$now_mins" -ge "$peak_s_mins" ]; then
            is_peak=1
            mins_left=$(( (1440 - now_mins) + peak_e_mins ))
        elif [ "$prev_peak_day" -eq 1 ] && [ "$now_mins" -lt "$peak_e_mins" ]; then
            is_peak=1
            mins_left=$(( peak_e_mins - now_mins ))
        else
            if [ "$is_peak_day" -eq 1 ] && [ "$now_mins" -lt "$peak_s_mins" ]; then
                mins_until=$(( peak_s_mins - now_mins ))
            else
                mins_until=$(mins_until_next_peak "$dow" "$now_mins" "$peak_s_mins" "$effective_peak_days_csv")
            fi
        fi
    fi
else
    mins_until=$(mins_until_next_peak "$dow" "$now_mins" "$peak_s_mins" "$effective_peak_days_csv")
fi

# ── Build status display ──
if [ "$is_peak" -eq 1 ]; then
    h=$(( mins_left / 60 )); m=$(( mins_left % 60 ))
    [ "$h" -gt 0 ] && t="${h}h $(printf '%02d' $m)m" || t="${m}m"

    if [ "$mins_left" -le 30 ]; then bg="$BG_GREEN"
    elif [ "$mins_left" -le 120 ]; then bg="$BG_YELLOW"
    else bg="$BG_RED"; fi

    ps_display=$(fmt_hour $peak_start_local)
    pe_display=$(fmt_hour $peak_end_local)
    status="${bg} Peak${RST} ${WHITE}→ ends in ${t}${RST} ${DIM}${ps_display}-${pe_display}${RST}"
else
    if [ -n "$mins_until" ] && [ "$mins_until" -gt 0 ]; then
        h=$(( mins_until / 60 )); m=$(( mins_until % 60 ))
        [ "$h" -gt 0 ] && t="${h}h $(printf '%02d' $m)m" || t="${m}m"
        status="${BG_GREEN} Off-Peak${RST} ${DIM}peak in ${t}${RST}"
    else
        status="${BG_GREEN} Off-Peak${RST}"
    fi
fi

# ── Env ──
if [ -n "$SSH_CLIENT" ] || [ -n "$SSH_TTY" ] || [ -n "$SSH_CONNECTION" ]; then
    envtag="${MAGENTA}REMOTE${RST}"
else
    envtag="${CYAN}LOCAL${RST}"
fi

# ── Git ──
gitinfo=""
branch=$(git branch --show-current 2>/dev/null)
if [ -n "$branch" ]; then
    uncommitted=$(git status --porcelain 2>/dev/null | wc -l | tr -d ' ')
    gitinfo="${DIM}${branch}${RST}"
    if [ "$uncommitted" -gt 0 ]; then
        gitinfo+=" ${YELLOW}${uncommitted} unsaved${RST}"
    else
        gitinfo+=" ${GREEN}saved${RST}"
    fi
fi

# ── Output (Flow design) ──
[ "$is_peak" -eq 1 ] && arrow="${YELLOW}▸${RST}" || arrow="${GREEN}▸${RST}"

parts="${status}"
[ -n "$release_notice" ] && parts="${release_notice} ${arrow} ${parts}"
[ -n "$gitinfo" ] && parts="${parts} ${arrow} ${gitinfo}"
parts="${parts} ${arrow} ${envtag}"

printf "%b" "$parts"
