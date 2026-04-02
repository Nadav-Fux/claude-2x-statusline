#!/usr/bin/env bash
# Claude Code statusline — pure bash fallback (minimal features only)
# No Python, no Node.js, no jq needed. Last resort.
# v2.1 — Peak hours with auto-timezone. Supports: peak_hours + git

RST='\033[0m'; BOLD='\033[1m'; DIM='\033[2m'
GREEN='\033[32m'; YELLOW='\033[33m'; CYAN='\033[36m'; MAGENTA='\033[35m'
BG_GREEN='\033[38;5;255;48;5;28m'; BG_YELLOW='\033[38;5;16;48;5;220m'
BG_RED='\033[38;5;255;48;5;124m'; BG_GRAY='\033[48;5;236m'
WHITE='\033[38;2;220;220;220m'

# ── Telemetry heartbeat (daily, fire-and-forget) ──
HEARTBEAT_FILE="$HOME/.claude/.statusline-heartbeat"
_today=$(date -u +%Y-%m-%d)
_do_ping=0
if [ ! -f "$HEARTBEAT_FILE" ]; then _do_ping=1
elif [ "$(cat "$HEARTBEAT_FILE" 2>/dev/null)" != "$_today" ]; then _do_ping=1
fi
if [ "$_do_ping" -eq 1 ]; then
    _uid=$(echo -n "$(hostname):$(whoami)" | sha256sum 2>/dev/null | cut -c1-16)
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

# ── Pacific Time DST calculation ──
utc_year=$(date -u +%Y)
utc_month=$(date -u +%-m 2>/dev/null || date -u +%m)
utc_day=$(date -u +%-d 2>/dev/null || date -u +%d)

# US DST: Second Sunday of March (8-14) to First Sunday of November (1-7)
if [ "$utc_month" -gt 3 ] && [ "$utc_month" -lt 11 ]; then
    pt_offset=-7  # PDT
elif [ "$utc_month" -eq 3 ] && [ "$utc_day" -ge 8 ]; then
    pt_offset=-7  # PDT (second Sunday is 8th at earliest)
elif [ "$utc_month" -eq 11 ] && [ "$utc_day" -le 7 ]; then
    pt_offset=-7  # PDT (first Sunday is 7th at latest)
else
    pt_offset=-8  # PST
fi

# ── Remote schedule (try cached, skip fetch in bash for speed) ──
SCHEDULE_CACHE="$HOME/.claude/statusline-schedule.json"
peak_start_h=5
peak_end_h=11
peak_tz="America/Los_Angeles"
peak_enabled=1

if [ -f "$SCHEDULE_CACHE" ]; then
    if command -v python3 >/dev/null 2>&1; then
        eval "$(python3 -c "
import json,sys
try:
    d=json.load(open('$SCHEDULE_CACHE'))
    p=d.get('peak',{})
    print(f'peak_start_h={p.get(\"start\",5)}')
    print(f'peak_end_h={p.get(\"end\",11)}')
    print(f'peak_tz={p.get(\"tz\",\"America/Los_Angeles\")}')
    print(f'peak_enabled={1 if p.get(\"enabled\",True) else 0}')
except: pass
" 2>/dev/null)"
    fi
fi

# ── Determine source timezone offset ──
if [ "$peak_tz" = "UTC" ] || [ "$peak_tz" = "Etc/UTC" ] || [ "$peak_tz" = "GMT" ]; then
    src_offset=0
else
    src_offset=$pt_offset
fi

# ── Convert peak hours to local time ──
peak_start_local=$(( (peak_start_h - src_offset + local_offset_hours) % 24 ))
[ "$peak_start_local" -lt 0 ] && peak_start_local=$(( peak_start_local + 24 ))
peak_end_local=$(( (peak_end_h - src_offset + local_offset_hours) % 24 ))
[ "$peak_end_local" -lt 0 ] && peak_end_local=$(( peak_end_local + 24 ))

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
[ "$dow" -ge 1 ] && [ "$dow" -le 5 ] && is_peak_day=1
[ "$prev_dow" -ge 1 ] && [ "$prev_dow" -le 5 ] && prev_peak_day=1

if [ "$is_peak_day" -eq 1 ] || [ "$prev_peak_day" -eq 1 ]; then
    if [ "$peak_e_mins" -gt "$peak_s_mins" ]; then
        # Normal case (no midnight crossing)
        if [ "$now_mins" -ge "$peak_s_mins" ] && [ "$now_mins" -lt "$peak_e_mins" ]; then
            is_peak=1
            mins_left=$(( peak_e_mins - now_mins ))
        elif [ "$now_mins" -lt "$peak_s_mins" ]; then
            mins_until=$(( peak_s_mins - now_mins ))
        else
            # After peak today, calculate to next weekday
            if [ "$dow" -lt 5 ]; then
                mins_until=$(( (1440 - now_mins) + peak_s_mins ))
            else
                # Friday after peak → Monday
                mins_until=$(( (1440 - now_mins) + 2 * 1440 + peak_s_mins ))
            fi
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
            fi
        fi
    fi
else
    # Weekend — find Monday
    if [ "$dow" -eq 6 ]; then
        mins_until=$(( (1440 - now_mins) + 1440 + peak_s_mins ))
    else  # Sunday
        mins_until=$(( (1440 - now_mins) + peak_s_mins ))
    fi
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
[ -n "$gitinfo" ] && parts="${parts} ${arrow} ${gitinfo}"
parts="${parts} ${arrow} ${envtag}"

printf "%b" "$parts"
