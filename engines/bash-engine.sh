#!/usr/bin/env bash
# Claude Code statusline — pure bash fallback (minimal features only)
# No Python, no Node.js, no jq needed. Last resort.
# Supports: time + 2x promo + git branch/dirty

RST='\033[0m'; BOLD='\033[1m'; DIM='\033[2m'; CYAN='\033[36m'
BG_GREEN='\033[38;5;16;48;5;46m'; BG_YELLOW='\033[38;5;16;48;5;220m'
BG_RED='\033[38;5;255;48;5;124m'; BG_GRAY='\033[48;5;236m'

# ── UTC time (portable) ──
utc_hour=$(date -u +%-H 2>/dev/null || date -u +%H)
utc_min=$(date -u +%-M 2>/dev/null || date -u +%M)
utc_month=$(date -u +%-m 2>/dev/null || date -u +%m)
utc_day=$(date -u +%-d 2>/dev/null || date -u +%d)

# Israel DST offset
if { [ "$utc_month" -gt 3 ] || { [ "$utc_month" -eq 3 ] && [ "$utc_day" -ge 27 ]; }; } && \
   { [ "$utc_month" -lt 10 ] || { [ "$utc_month" -eq 10 ] && [ "$utc_day" -lt 25 ]; }; }; then
    offset=3
else
    offset=2
fi

il_hour=$(( (utc_hour + offset) % 24 ))
il_min=$utc_min
il_date=$(printf "%04d%02d%02d" "$(date -u +%Y)" "$utc_month" "$utc_day")
il_time=$(printf "%02d:%02d" "$il_hour" "$il_min")

# ── Promo check ──
promo_start=20260313
promo_end=20260327

if [ "$il_date" -lt "$promo_start" ] || [ "$il_date" -gt "$promo_end" ]; then
    status="${DIM}Promo ended${RST}"
else
    now_mins=$(( il_hour * 60 + il_min ))
    peak_s=$(( (12 + offset) * 60 ))
    peak_e=$(( (18 + offset) * 60 ))
    dow=$(date -u +%u)  # 1=Mon, 7=Sun

    doubled=0; mins_left=0

    if [ "$dow" -eq 6 ] && [ "$now_mins" -ge 540 ]; then
        doubled=1; mins_left=$(( (1440 - now_mins) + 1440 + 540 ))
    elif [ "$dow" -eq 7 ]; then
        doubled=1; mins_left=$(( (1440 - now_mins) + 540 ))
    elif [ "$dow" -eq 1 ] && [ "$now_mins" -lt 540 ]; then
        doubled=1; mins_left=$(( 540 - now_mins ))
    elif [ "$now_mins" -ge "$peak_e" ]; then
        doubled=1; mins_left=$(( (1440 - now_mins) + peak_s ))
    elif [ "$now_mins" -lt "$peak_s" ]; then
        doubled=1; mins_left=$(( peak_s - now_mins ))
    fi

    if [ "$doubled" -eq 1 ]; then
        h=$(( mins_left / 60 )); m=$(( mins_left % 60 ))
        [ "$h" -gt 0 ] && t="${h}h $(printf '%02d' $m)m" || t="${m}m"

        if [ "$mins_left" -gt 180 ]; then bg="$BG_GREEN"
        elif [ "$mins_left" -gt 60 ]; then bg="$BG_YELLOW"
        else bg="$BG_RED"; fi

        status="${bg}${BOLD} 2x ACTIVE ${RST} ${bg} ${t} left ${RST}"
    else
        mins_until=$(( peak_e - now_mins ))
        h=$(( mins_until / 60 )); m=$(( mins_until % 60 ))
        [ "$h" -gt 0 ] && t="${h}h $(printf '%02d' $m)m" || t="${m}m"
        status="${DIM}${BG_GRAY} PEAK ${RST} ${CYAN}2x returns in ${t}${RST}"
    fi
fi

# ── Git ──
gitinfo=""
branch=$(git branch --show-current 2>/dev/null)
if [ -n "$branch" ]; then
    dirty=$(git status --porcelain 2>/dev/null | wc -l | tr -d ' ')
    gitinfo=" ${DIM}|${RST} ${DIM}${branch}${RST}"
    [ "$dirty" -gt 0 ] && gitinfo+="${DIM} +${dirty}${RST}"
fi

printf "${DIM}${il_time}${RST} ${status}${gitinfo}"
