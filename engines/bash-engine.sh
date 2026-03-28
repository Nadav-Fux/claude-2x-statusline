#!/usr/bin/env bash
# Claude Code statusline — pure bash fallback (minimal features only)
# No Python, no Node.js, no jq needed. Last resort.
# v2.1 — Peak hours with auto-timezone. Supports: peak_hours + git

RST='\033[0m'; BOLD='\033[1m'; DIM='\033[2m'
GREEN='\033[32m'; YELLOW='\033[33m'; CYAN='\033[36m'; MAGENTA='\033[35m'
BG_GREEN='\033[38;5;255;48;5;28m'; BG_YELLOW='\033[38;5;16;48;5;220m'
BG_RED='\033[38;5;255;48;5;124m'; BG_GRAY='\033[48;5;236m'
WHITE='\033[38;2;220;220;220m'

# ── Local time & timezone offset ──
local_hour=$(date +%-H 2>/dev/null || date +%H)
local_min=$(date +%-M 2>/dev/null || date +%M)
dow=$(date +%u)  # 1=Mon, 7=Sun

# UTC offset in hours (handles DST automatically via system timezone)
utc_offset_sec=$(date +%z 2>/dev/null | sed 's/\(..\)\(..\)/\1*3600+\2*60/' | bc 2>/dev/null)
if [ -z "$utc_offset_sec" ]; then
    # Fallback: parse +HHMM format
    tz_str=$(date +%z)
    tz_sign="${tz_str:0:1}"
    tz_hh="${tz_str:1:2}"
    tz_mm="${tz_str:3:2}"
    # Remove leading zeros
    tz_hh=$((10#$tz_hh))
    tz_mm=$((10#$tz_mm))
    utc_offset_sec=$(( (tz_hh * 3600 + tz_mm * 60) ))
    [ "$tz_sign" = "-" ] && utc_offset_sec=$(( -utc_offset_sec ))
fi
local_offset_hours=$(( utc_offset_sec / 3600 ))

# ── Pacific Time DST calculation ──
utc_year=$(date -u +%Y)
utc_month=$(date -u +%-m 2>/dev/null || date -u +%m)
utc_day=$(date -u +%-d 2>/dev/null || date -u +%d)

# US DST: approx March 8-14 (second Sunday) to Nov 1-7 (first Sunday)
# Simplified: March 10 - Nov 3 as approximation
if [ "$utc_month" -gt 3 ] && [ "$utc_month" -lt 11 ]; then
    pt_offset=-7  # PDT
elif [ "$utc_month" -eq 3 ] && [ "$utc_day" -ge 10 ]; then
    pt_offset=-7  # PDT (approximate)
elif [ "$utc_month" -eq 11 ] && [ "$utc_day" -lt 3 ]; then
    pt_offset=-7  # PDT (approximate)
else
    pt_offset=-8  # PST
fi

# ── Remote schedule (try cached, skip fetch in bash for speed) ──
SCHEDULE_CACHE="$HOME/.claude/statusline-schedule.json"
peak_start_pt=5
peak_end_pt=11

if [ -f "$SCHEDULE_CACHE" ]; then
    # Try to parse with python if available, else use defaults
    if command -v python3 >/dev/null 2>&1; then
        eval "$(python3 -c "
import json,sys
try:
    d=json.load(open('$SCHEDULE_CACHE'))
    p=d.get('peak',{})
    print(f'peak_start_pt={p.get(\"start\",5)}')
    print(f'peak_end_pt={p.get(\"end\",11)}')
except: pass
" 2>/dev/null)"
    fi
fi

# ── Convert peak hours to local time ──
# peak_start_local = peak_start_pt - pt_offset + local_offset_hours (mod 24)
peak_start_local=$(( (peak_start_pt - pt_offset + local_offset_hours) % 24 ))
[ "$peak_start_local" -lt 0 ] && peak_start_local=$(( peak_start_local + 24 ))
peak_end_local=$(( (peak_end_pt - pt_offset + local_offset_hours) % 24 ))
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

# Only weekdays (1=Mon to 5=Fri)
if [ "$dow" -ge 1 ] && [ "$dow" -le 5 ]; then
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
        # Crosses midnight
        if [ "$now_mins" -ge "$peak_s_mins" ] || [ "$now_mins" -lt "$peak_e_mins" ]; then
            is_peak=1
            if [ "$now_mins" -ge "$peak_s_mins" ]; then
                mins_left=$(( (1440 - now_mins) + peak_e_mins ))
            else
                mins_left=$(( peak_e_mins - now_mins ))
            fi
        else
            if [ "$now_mins" -lt "$peak_s_mins" ]; then
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
