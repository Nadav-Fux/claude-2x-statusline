#!/usr/bin/env bash
# claude-2x-statusline — Israel-timezone 2X promotion tracker for Claude Code
# https://github.com/Nadav-Fux/claude-2x-statusline
#
# Shows a color-coded status line with:
#   - Current Israel time (auto-detects DST)
#   - 2X promotion status with urgency-based countdown
#   - Git branch + dirty file count
#
# Inspired by:
#   - https://github.com/alonw0/cc-promotion-statusline (Alon Wolenitz)
#   - https://isclaude2x.com/ (Mehul Mohan)

PY=$(command -v python3 2>/dev/null || command -v python 2>/dev/null)
if [ -z "$PY" ]; then echo "2x promo | no python"; exit 0; fi
exec "$PY" -u - << 'PYEOF'
from datetime import datetime, timezone, timedelta

# ── Israel timezone (auto DST) ──────────────────────────────────────────────
utc = datetime.now(timezone.utc)
m, d = utc.month, utc.day
# Israel DST: last Friday before April 2 → last Sunday before October 25
if (m > 3 or (m == 3 and d >= 27)) and (m < 10 or (m == 10 and d < 25)):
    il_offset = 3   # IDT (summer)
else:
    il_offset = 2   # IST (winter)
il = utc + timedelta(hours=il_offset)

hour, minute = il.hour, il.minute
weekday = il.isoweekday()          # 1=Mon … 7=Sun
il_date = il.strftime("%Y%m%d")
il_time = il.strftime("%H:%M")

# ── Promotion window ────────────────────────────────────────────────────────
# Claude March 2026 promotion: 2X usage outside peak hours & all weekend
# Peak = 8 AM–2 PM EDT = 12:00–18:00 UTC
# Update these dates for future promotions:
PROMO_START = 20260313
PROMO_END   = 20260327

promo_active = PROMO_START <= int(il_date) <= PROMO_END

peak_start = 12 + il_offset        # peak start in Israel time
peak_end   = 18 + il_offset        # peak end in Israel time
now_mins   = hour * 60 + minute

# ── Determine 2X status ─────────────────────────────────────────────────────
doubled, reason, mins_left, mins_until = False, "", 0, 0

if promo_active:
    # Weekend: Friday 9:00 IL → Monday 9:00 IL
    if weekday == 6 and now_mins >= 540:
        doubled, reason, mins_left = True, "weekend", (1440 - now_mins) + 1440 + 540
    elif weekday == 7:
        doubled, reason, mins_left = True, "weekend", (1440 - now_mins) + 540
    elif weekday == 1 and now_mins < 540:
        doubled, reason, mins_left = True, "weekend", 540 - now_mins
    # Off-peak weekday hours
    elif now_mins >= peak_end * 60:
        doubled, reason, mins_left = True, "off-peak", (1440 - now_mins) + peak_start * 60
    elif now_mins < peak_start * 60:
        doubled, reason, mins_left = True, "off-peak", peak_start * 60 - now_mins

if not doubled and promo_active:
    mins_until = peak_end * 60 - now_mins

# ── Format helpers ───────────────────────────────────────────────────────────
def fmt(m):
    h, rm = divmod(m, 60)
    return f"{h}h {rm:02d}m" if h > 0 else f"{rm}m"

RST, BOLD, DIM = "\033[0m", "\033[1m", "\033[2m"

# ── Build status string ─────────────────────────────────────────────────────
if not promo_active:
    status = f"{DIM}Promotion ended{RST}"
elif doubled:
    t = fmt(mins_left)
    # Color by urgency: green (>3h) → yellow (>1h) → red (<1h)
    if mins_left > 180:
        bg = "\033[38;5;16;48;5;46m"       # bright green
    elif mins_left > 60:
        bg = "\033[38;5;16;48;5;220m"      # yellow
    else:
        bg = "\033[38;5;255;48;5;124m"     # red
    wknd = f" {DIM}weekend{RST}" if reason == "weekend" else ""
    status = f"{bg}{BOLD} 2x ACTIVE {RST} {bg} {t} left {RST}{wknd}"
else:
    t = fmt(mins_until)
    status = f"{DIM}\033[48;5;236m PEAK {RST} \033[38;5;87m2x returns in {t}{RST}"

# ── Git info ─────────────────────────────────────────────────────────────────
git = ""
try:
    import subprocess
    branch = subprocess.run(
        ["git", "branch", "--show-current"],
        capture_output=True, text=True, timeout=2
    ).stdout.strip()
    if branch:
        dirty = len(subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, timeout=2
        ).stdout.strip().splitlines())
        git = f" {DIM}|{RST} {DIM}{branch}{RST}"
        if dirty:
            git += f"{DIM} +{dirty}{RST}"
except Exception:
    pass

print(f"{DIM}{il_time}{RST} {status}{git}")
PYEOF
