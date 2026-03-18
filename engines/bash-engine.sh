#!/usr/bin/env bash
# Claude Code statusline — pure bash fallback (minimal features only)
# No Python, no Node.js, no jq needed. Last resort.
# Supports: 2x promo + git

RST='\033[0m'; BOLD='\033[1m'; DIM='\033[2m'
GREEN='\033[32m'; YELLOW='\033[33m'
BG_GREEN='\033[38;5;255;48;5;28m'; BG_YELLOW='\033[38;5;16;48;5;220m'
BG_RED='\033[38;5;255;48;5;124m'; BG_GRAY='\033[48;5;236m'
WHITE='\033[38;2;220;220;220m'

# ── Israel time (use TZ if available, fallback to manual) ──
if TZ=Asia/Jerusalem date +%H >/dev/null 2>&1; then
    il_hour=$(TZ=Asia/Jerusalem date +%-H 2>/dev/null || TZ=Asia/Jerusalem date +%H)
    il_min=$(TZ=Asia/Jerusalem date +%-M 2>/dev/null || TZ=Asia/Jerusalem date +%M)
    il_date=$(TZ=Asia/Jerusalem date +%Y%m%d)
    dow=$(TZ=Asia/Jerusalem date +%u)
else
    utc_hour=$(date -u +%-H 2>/dev/null || date -u +%H)
    utc_min=$(date -u +%-M 2>/dev/null || date -u +%M)
    utc_month=$(date -u +%-m 2>/dev/null || date -u +%m)
    utc_day=$(date -u +%-d 2>/dev/null || date -u +%d)
    utc_year=$(date -u +%Y)

    if { [ "$utc_month" -gt 3 ] || { [ "$utc_month" -eq 3 ] && [ "$utc_day" -ge 27 ]; }; } && \
       { [ "$utc_month" -lt 10 ] || { [ "$utc_month" -eq 10 ] && [ "$utc_day" -lt 25 ]; }; }; then
        offset=3
    else
        offset=2
    fi

    il_total_hour=$(( utc_hour + offset ))
    il_hour=$(( il_total_hour % 24 ))
    il_min=$utc_min

    # Handle date rollover
    if [ "$il_total_hour" -ge 24 ]; then
        il_date=$(date -u -d "+1 day" +%Y%m%d 2>/dev/null || printf "%04d%02d%02d" "$utc_year" "$utc_month" "$(( utc_day + 1 ))")
    else
        il_date=$(printf "%04d%02d%02d" "$utc_year" "$utc_month" "$utc_day")
    fi
    dow=$(date -u +%u)
    # Adjust DOW for Israel day rollover
    if [ "$il_total_hour" -ge 24 ]; then
        dow=$(( (dow % 7) + 1 ))
    fi
fi

# ── Promo check ──
promo_start=20260313
promo_end=20260327

doubled=0
if [ "$il_date" -lt "$promo_start" ] || [ "$il_date" -gt "$promo_end" ]; then
    status="${DIM}Promo ended${RST}"
else
    now_mins=$(( il_hour * 60 + il_min ))
    # Peak hours in Israel local time
    peak_s=$(( 14 * 60 ))
    peak_e=$(( 20 * 60 ))

    mins_left=0

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

    # Days left (use date arithmetic if available, fallback to integer diff)
    if command -v python3 >/dev/null 2>&1 || command -v python >/dev/null 2>&1; then
        PY_CMD=$(command -v python3 2>/dev/null || command -v python 2>/dev/null)
        days_left=$("$PY_CMD" -c "from datetime import date;e=$promo_end;t=$il_date;print((date(e//10000,(e%10000)//100,e%100)-date(t//10000,(t%10000)//100,t%100)).days)" 2>/dev/null || echo $(( promo_end - il_date )))
    else
        days_left=$(( promo_end - il_date ))
    fi
    [ "$days_left" -gt 0 ] && [ "$days_left" -le 14 ] && days_tag=" ${DIM}${days_left}d left${RST}" || days_tag=""

    if [ "$doubled" -eq 1 ]; then
        h=$(( mins_left / 60 )); m=$(( mins_left % 60 ))
        [ "$h" -gt 0 ] && t="${h}h $(printf '%02d' $m)m" || t="${m}m"

        if [ "$mins_left" -gt 180 ]; then bg="$BG_GREEN"
        elif [ "$mins_left" -gt 60 ]; then bg="$BG_YELLOW"
        else bg="$BG_RED"; fi

        status="${bg} 2x ACTIVE ${RST} ${WHITE}${t} left${RST}${days_tag}"
    else
        mins_until=$(( peak_e - now_mins ))
        h=$(( mins_until / 60 )); m=$(( mins_until % 60 ))
        [ "$h" -gt 0 ] && t="${h}h $(printf '%02d' $m)m" || t="${m}m"
        status="${BG_GRAY} PEAK ${RST} ${DIM}→ 2x in ${t}${RST}${days_tag}"
    fi
fi

# ── Git ──
gitinfo=""
branch=$(git branch --show-current 2>/dev/null)
if [ -n "$branch" ]; then
    uncommitted=$(git status --porcelain 2>/dev/null | wc -l | tr -d ' ')
    gitinfo="${DIM}${branch}${RST}"
    [ "$uncommitted" -gt 0 ] && gitinfo+=" ${YELLOW}${uncommitted} unsaved${RST}"
fi

# ── Output (Flow design) ──
[ "$doubled" -eq 1 ] && arrow="${GREEN}▸${RST}" || arrow="${YELLOW}▸${RST}"

parts="${status}"
[ -n "$gitinfo" ] && parts="${parts} ${arrow} ${gitinfo}"

printf "%b" "$parts"
