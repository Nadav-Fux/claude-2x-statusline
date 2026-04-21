#!/usr/bin/env python3
"""Claude Code statusline — modular Python engine.

Reads JSON from stdin (provided by Claude Code) + config file,
runs enabled segments, outputs ANSI-colored status line.

v2.1 — Peak hours awareness with auto-timezone and remote schedule.
"""
import sys
import json
import os
import subprocess
import hashlib
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Allow importing from project-root lib/ regardless of CWD
_LIB_DIR = str(Path(__file__).parent.parent / "lib")
if _LIB_DIR not in sys.path:
    sys.path.insert(0, _LIB_DIR)

from rolling_state import (
    append_sample as _rs_append,
    rolling_rate as _rs_rate,
    rolling_tokens_out as _rs_tokens,
    cache_delta as _rs_cache_delta,
)

DEBUG = os.environ.get("STATUSLINE_DEBUG") == "1"

def debug(msg):
    if DEBUG:
        print(f"[statusline] {msg}", file=sys.stderr)

# ══════════════════════════════════════════════════════════════════════════════
# ANSI COLORS
# ══════════════════════════════════════════════════════════════════════════════
RST = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
MAGENTA = "\033[35m"
CYAN = "\033[36m"
WHITE = "\033[38;2;220;220;220m"
BG_GREEN = "\033[38;5;255;48;5;28m"
BG_YELLOW = "\033[38;5;16;48;5;220m"
BG_RED = "\033[38;5;255;48;5;124m"
BG_GRAY = "\033[48;5;236m"
BG_BLUE = "\033[38;5;255;48;5;27m"

# ══════════════════════════════════════════════════════════════════════════════
# TIER PRESETS
# ══════════════════════════════════════════════════════════════════════════════
# "standard" and "full" share an identical segment list — this is intentional.
# Both tiers render the same line 1 segments. The difference is that "full" mode
# triggers 3 additional output lines in the render loop (see main(), ~lines 1110-1122):
#   line 2 — timeline bar       (build_timeline, guarded by show_timeline feature flag
#                                 and off-peak-day check)
#   line 3 — rate_limits bars   (build_rate_limits_line)
#   line 4 — burn/cache metrics (build_metrics_line)
# Do NOT alter the segment lists below; behaviour diverges only at render time.
TIER_PRESETS = {
    # Minimal: essentials only — peak, model, compact context, rate limit %, git
    "minimal": ["peak_hours", "model", "context", "git_branch", "git_dirty", "rate_limits", "env"],
    # Standard: clean line 1 + line 2 with rate limits (5h + weekly)
    "standard": ["peak_hours", "model", "context", "vim_mode", "agent", "git_branch", "git_dirty", "cost", "effort", "env"],
    # Full: clean line 1 + dashboard below with rate limits, spending, cache (with explanations)
    "full": ["peak_hours", "model", "context", "vim_mode", "agent", "git_branch", "git_dirty", "cost", "effort", "env"],
}

DEFAULT_CONFIG = {
    "tier": "standard",
    "segments": {},
    "timezone": "auto",
    "separator": " | ",
    "mode": "minimal",
    "full_mode_rate_limits": True,
    "full_mode_timeline": True,
    "schedule_url": "https://raw.githubusercontent.com/Nadav-Fux/claude-2x-statusline/main/schedule.json",
    "schedule_cache_hours": 3,
}


def load_local_version():
    package_path = Path(__file__).resolve().parent.parent / "package.json"
    try:
        return json.loads(package_path.read_text()).get("version", "")
    except Exception:
        return ""


CURRENT_VERSION = load_local_version()

# Default schedule (fallback when remote fetch fails and no cache exists)
DEFAULT_SCHEDULE = {
    "v": 2,
    "mode": "peak_hours",
    "default_tier": "full",
    "peak": {
        "enabled": True,
        "tz": "America/Los_Angeles",
        "days": [1, 2, 3, 4, 5],
        "start": 5,
        "end": 11,
        "label_peak": "Peak",
        "label_offpeak": "Off-Peak",
        "note": "Session limits consumed faster during peak hours",
    },
    "banner": {"text": "", "expires": "", "color": "yellow"},
    "release": {},
    "features": {"show_peak_segment": True, "show_rate_limits": True, "show_timeline": True},
}


def parse_version(value):
    core = str(value or "").split("-", 1)[0].split("+", 1)[0]
    parts = []
    for token in core.split("."):
        digits = "".join(ch for ch in token if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return parts


def compare_versions(left, right):
    left_parts = parse_version(left)
    right_parts = parse_version(right)
    length = max(len(left_parts), len(right_parts))
    left_parts.extend([0] * (length - len(left_parts)))
    right_parts.extend([0] * (length - len(right_parts)))
    if left_parts < right_parts:
        return -1
    if left_parts > right_parts:
        return 1
    return 0


def build_release_notice(schedule):
    release = schedule.get("release", {})
    latest_version = str(release.get("latest_version", "")).strip()
    minimum_version = str(release.get("minimum_version", "")).strip()
    if not CURRENT_VERSION or (not latest_version and not minimum_version):
        return ""

    command = str(release.get("command", "/statusline-update")).strip() or "/statusline-update"
    target_version = latest_version or minimum_version

    if minimum_version and compare_versions(CURRENT_VERSION, minimum_version) < 0:
        text = release.get("required_text") or f"Update required v{target_version} via {command}"
        return f"{BG_RED} {text} {RST}"

    if latest_version and compare_versions(CURRENT_VERSION, latest_version) < 0:
        text = release.get("available_text") or f"Update available v{latest_version} via {command}"
        return f"{BG_YELLOW} {text} {RST}"

    return ""

# ══════════════════════════════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════════════════════════════
def load_config():
    config_path = Path.home() / ".claude" / "statusline-config.json"
    config = dict(DEFAULT_CONFIG)
    if config_path.exists():
        try:
            with open(config_path) as f:
                user = json.load(f)
            config.update(user)
        except Exception:
            pass
    return config


def apply_remote_defaults(config, schedule):
    """Apply remote schedule defaults (only if user hasn't explicitly set them)."""
    config_path = Path.home() / ".claude" / "statusline-config.json"
    user_keys = set()
    if config_path.exists():
        try:
            user_keys = set(json.loads(config_path.read_text()).keys())
        except Exception:
            pass

    # Remote default_tier only applies if user hasn't set tier in their config
    if "tier" not in user_keys:
        remote_tier = schedule.get("default_tier")
        if remote_tier:
            config["tier"] = remote_tier


def get_enabled_segments(config, schedule):
    """Get enabled segments, respecting remote feature flags."""
    features = schedule.get("features", {})

    tier = config.get("tier", "standard")
    if tier == "custom":
        segs = config.get("segments", {})
        enabled = []
        for k, v in segs.items():
            if v:
                enabled.append("peak_hours" if k == "promo_2x" else k)
        return enabled
    preset = TIER_PRESETS.get(tier, TIER_PRESETS["standard"])
    enabled = list(preset)

    # Remote feature flags can hide segments
    if not features.get("show_peak_segment", True):
        enabled = [s for s in enabled if s not in ("peak_hours", "promo_2x")]
    if not features.get("show_rate_limits", True):
        enabled = [s for s in enabled if s != "rate_limits"]

    return enabled


# ══════════════════════════════════════════════════════════════════════════════
# REMOTE SCHEDULE
# ══════════════════════════════════════════════════════════════════════════════
def load_schedule(config):
    """Load peak hours schedule: remote (cached) → local cache → default."""
    cache_path = Path.home() / ".claude" / "statusline-schedule.json"
    cache_hours = config.get("schedule_cache_hours", 3)
    schedule_url = config.get("schedule_url", DEFAULT_CONFIG["schedule_url"])

    # Check cache
    if cache_path.exists():
        try:
            age_hours = (time.time() - cache_path.stat().st_mtime) / 3600
            cached = json.loads(cache_path.read_text())
            # Remote schedule can override cache TTL
            remote_ttl = cached.get("cache_hours")
            effective_ttl = remote_ttl if remote_ttl else cache_hours
            if age_hours < effective_ttl:
                debug(f"schedule: using cache (age {age_hours:.1f}h)")
                return cached
        except Exception:
            pass

    # Fetch remote
    if schedule_url:
        try:
            import urllib.request
            req = urllib.request.Request(
                schedule_url,
                headers={"User-Agent": "claude-statusline/2.1", "Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
                cache_path.write_text(json.dumps(data, indent=2))
                debug("schedule: fetched remote")
                return data
        except Exception as e:
            debug(f"schedule: remote fetch failed: {e}")

    # Fallback to stale cache
    if cache_path.exists():
        try:
            return json.loads(cache_path.read_text())
        except Exception:
            pass

    # Last resort: hardcoded default
    debug("schedule: using hardcoded default")
    return DEFAULT_SCHEDULE


# ══════════════════════════════════════════════════════════════════════════════
# TIMEZONE
# ══════════════════════════════════════════════════════════════════════════════
def get_local_time():
    """Get current local time with timezone info. Returns (datetime, tz_name, utc_offset_hours)."""
    try:
        from zoneinfo import ZoneInfo
        local_tz = datetime.now().astimezone().tzinfo
        now = datetime.now(local_tz)
        tz_name = str(local_tz)
        offset = now.utcoffset().total_seconds() / 3600
        return now, tz_name, offset
    except Exception:
        pass

    # Fallback: use system timezone
    try:
        now = datetime.now().astimezone()
        offset = now.utcoffset().total_seconds() / 3600
        tz_name = now.tzname() or f"UTC{offset:+.0f}"
        return now, tz_name, offset
    except Exception:
        pass

    # Fallback: parse system UTC offset from time module
    try:
        import time as _time
        offset = -_time.timezone / 3600
        if _time.daylight and _time.localtime().tm_isdst:
            offset = -_time.altzone / 3600
        now = datetime.now()
        tz_name = _time.tzname[_time.localtime().tm_isdst] or f"UTC{offset:+.0f}"
        return now, tz_name, offset
    except Exception:
        pass

    # Last resort: UTC
    now = datetime.now(timezone.utc)
    return now, "UTC", 0


def get_tz_offset(tz_name, ref_time=None):
    """Get UTC offset for a named timezone at a given time (handles DST)."""
    # Handle UTC explicitly (no zoneinfo needed)
    if tz_name in ("UTC", "Etc/UTC", "GMT"):
        return 0

    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(tz_name)
        dt = (ref_time or datetime.now(timezone.utc)).astimezone(tz)
        return dt.utcoffset().total_seconds() / 3600
    except Exception:
        pass

    # Fallback for America/Los_Angeles: manual US DST
    if tz_name == "America/Los_Angeles":
        return _us_pacific_offset(ref_time or datetime.now(timezone.utc))

    return None


def _us_pacific_offset(utc_dt):
    """Calculate Pacific Time offset: PDT=-7, PST=-8.
    US DST: Second Sunday of March 2:00 AM → First Sunday of November 2:00 AM."""
    year = utc_dt.year
    # Second Sunday of March
    mar1 = datetime(year, 3, 1, tzinfo=timezone.utc)
    dst_start = mar1 + timedelta(days=(6 - mar1.weekday()) % 7 + 7)  # Second Sunday
    dst_start = dst_start.replace(hour=10)  # 2 AM PST = 10:00 UTC

    # First Sunday of November
    nov1 = datetime(year, 11, 1, tzinfo=timezone.utc)
    dst_end = nov1 + timedelta(days=(6 - nov1.weekday()) % 7)  # First Sunday
    dst_end = dst_end.replace(hour=9)  # 2 AM PDT = 09:00 UTC

    if dst_start <= utc_dt.replace(tzinfo=timezone.utc) < dst_end:
        return -7  # PDT
    return -8  # PST


def peak_hours_to_local(schedule, local_offset):
    """Convert peak hours from schedule timezone to local time.

    Returns (local_start_hour_float, local_end_hour_float, duration_hours,
             peak_day_offset).

    `peak_day_offset` is the number of days the LOCAL peak window is shifted
    FORWARD from the schedule-timezone's peak day. For example, a schedule
    of peak=22 UTC on Saturday, observed by a UTC+3 user, starts at local
    01:00 on SUNDAY — so peak_day_offset=1. The caller uses this to check
    `peak_days` against the correct effective local weekday.
    """
    peak = schedule.get("peak", {})
    peak_tz = peak.get("tz", "America/Los_Angeles")
    start_h = peak.get("start", 5)
    end_h = peak.get("end", 11)

    # Get the source timezone offset
    utc_now = datetime.now(timezone.utc)
    src_offset = get_tz_offset(peak_tz, utc_now)
    if src_offset is None:
        src_offset = _us_pacific_offset(utc_now)

    # Raw start hour in local time (without mod) — lets us detect if the
    # conversion pushed the peak window into the next local day (>= 24) or
    # back into the previous local day (< 0).
    raw_start_local = start_h - src_offset + local_offset
    peak_day_offset = int(raw_start_local // 24)

    start_local = raw_start_local % 24
    end_utc = end_h - src_offset
    end_local = (end_utc + local_offset) % 24

    duration = end_h - start_h  # Duration doesn't change across timezones
    return start_local, end_local, duration, peak_day_offset


# ══════════════════════════════════════════════════════════════════════════════
# STDIN JSON
# ══════════════════════════════════════════════════════════════════════════════
def read_stdin():
    try:
        if not sys.stdin.isatty():
            data = sys.stdin.read().strip()
            if data:
                parsed = json.loads(data)
                debug(f"stdin: {list(parsed.keys())}")
                return parsed
    except Exception as e:
        debug(f"stdin error: {e}")
    return {}


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════
def fmt_duration(total_mins):
    h, m = divmod(total_mins, 60)
    return f"{h}h {m:02d}m" if h > 0 else f"{m}m"


def fmt_seconds(secs):
    h = secs // 3600
    m = (secs % 3600) // 60
    s = secs % 60
    if h > 0:
        return f"{h}h{m:02d}m"
    elif m > 0:
        return f"{m}m{s:02d}s"
    return f"{s}s"


def color_for_pct(pct):
    if pct >= 80:
        return RED
    elif pct >= 50:
        return YELLOW
    return GREEN


def build_usage_bar(pct, width=10):
    pct = max(0, min(100, pct))
    filled = pct * width // 100
    empty = width - filled
    color = color_for_pct(pct)
    filled_chars = "\u25b0" * filled
    empty_chars = "\u25b1" * empty
    return f"{color}{filled_chars}{DIM}{empty_chars}{RST}"


def git_cmd(*args, timeout=2):
    try:
        r = subprocess.run(
            ["git"] + list(args),
            capture_output=True, text=True, timeout=timeout
        )
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def fmt_hour(h):
    """Format a float hour (e.g. 15.0) as '3:00pm'."""
    h = h % 24
    h_int = int(h)
    m_int = int((h - h_int) * 60)
    ampm = "am" if h_int < 12 else "pm"
    display_h = h_int % 12 or 12
    if m_int:
        return f"{display_h}:{m_int:02d}{ampm}"
    return f"{display_h}{ampm}"


# ══════════════════════════════════════════════════════════════════════════════
# SEGMENTS
# ══════════════════════════════════════════════════════════════════════════════

def seg_time(ctx):
    now = ctx["local_time"]
    return f"{WHITE}{BOLD}{now.strftime('%H:%M')}{RST}"


def seg_banner(ctx):
    """Show a remote-controlled banner message (with optional expiry)."""
    schedule = ctx["schedule"]
    badges = []

    release_notice = build_release_notice(schedule)
    if release_notice:
        badges.append(release_notice)

    banner = schedule.get("banner", {})
    text = banner.get("text", "")
    if text:
        expires = banner.get("expires", "")
        show_banner = True
        if expires:
            try:
                exp_date = datetime.strptime(expires, "%Y-%m-%d").date()
                if ctx["local_time"].date() > exp_date:
                    show_banner = False
            except Exception:
                pass

        if show_banner:
            color_map = {"yellow": BG_YELLOW, "red": BG_RED, "green": BG_GREEN, "blue": BG_BLUE, "gray": BG_GRAY}
            bg = color_map.get(banner.get("color", "yellow"), BG_YELLOW)
            badges.append(f"{bg} {text} {RST}")

    return " ".join(badges)


def seg_peak_hours(ctx):
    """Show peak/off-peak status with countdown. Returns '' when mode=normal.

    Note: Returns empty when schedule.mode == 'normal'. Render loop (Workstream C)
    is responsible for suppressing the timeline line on off-peak days.
    """
    schedule = ctx["schedule"]

    # If mode is "normal" (no restrictions), hide this segment entirely
    if schedule.get("mode") == "normal":
        return ""

    peak_cfg = schedule.get("peak", {})

    if not peak_cfg.get("enabled", True):
        return f"{GREEN}OFF-PEAK{RST}"

    now = ctx["local_time"]
    local_offset = ctx["local_offset"]
    hour = now.hour + now.minute / 60.0
    weekday = now.isoweekday()  # 1=Mon, 7=Sun

    peak_days = peak_cfg.get("days", [1, 2, 3, 4, 5])
    start_local, end_local, duration, peak_day_offset = peak_hours_to_local(schedule, local_offset)

    # Shift peak_days into LOCAL semantics: if timezone conversion pushed
    # the peak window forward a local day (e.g. UTC Sat 22:00 → local Sun
    # 01:00 for UTC+3), a schedule-day "Saturday" maps to local-day "Sunday".
    def _shift_wd(wd, delta):
        return ((wd - 1 + delta) % 7) + 1

    effective_peak_days = [_shift_wd(d, peak_day_offset) for d in peak_days]

    # Store for timeline
    ctx["peak_start_local"] = start_local
    ctx["peak_end_local"] = end_local
    ctx["peak_days"] = effective_peak_days

    is_peak_day = weekday in effective_peak_days
    prev_weekday = 7 if weekday == 1 else weekday - 1
    prev_was_peak = prev_weekday in effective_peak_days
    is_peak = False
    mins_left = 0
    mins_until = 0

    if is_peak_day or prev_was_peak:
        # Handle case where peak hours cross midnight in local time
        if end_local > start_local:
            # Normal case: e.g. 15:00-21:00
            if is_peak_day:
                is_peak = start_local <= hour < end_local
            if is_peak:
                mins_left = int((end_local - hour) * 60)
            else:
                if is_peak_day and hour < start_local:
                    mins_until = int((start_local - hour) * 60)
                elif is_peak_day:
                    mins_until = _mins_until_next_peak(now, peak_days, start_local)
                else:
                    mins_until = _mins_until_next_peak(now, peak_days, start_local)
        else:
            # Crosses midnight: e.g. 22:00-04:00
            # Peak if today is peak day and past start, OR previous day was peak and before end
            if is_peak_day and hour >= start_local:
                is_peak = True
            elif prev_was_peak and hour < end_local:
                is_peak = True
            if is_peak:
                if hour >= start_local:
                    mins_left = int((24 - hour + end_local) * 60)
                else:
                    mins_left = int((end_local - hour) * 60)
            else:
                if hour < start_local:
                    mins_until = int((start_local - hour) * 60)
                else:
                    mins_until = _mins_until_next_peak(now, peak_days, start_local)
    else:
        mins_until = _mins_until_next_peak(now, peak_days, start_local)

    ctx["is_peak"] = is_peak
    ctx["is_offpeak"] = not is_peak

    label_peak = peak_cfg.get("label_peak", "Peak")
    label_offpeak = peak_cfg.get("label_offpeak", "Off-Peak")

    if is_peak:
        t = fmt_duration(mins_left)
        if mins_left <= 30:
            bg = BG_GREEN  # Almost over = good news
        elif mins_left <= 120:
            bg = BG_YELLOW
        else:
            bg = BG_RED
        time_range = f"{DIM}{fmt_hour(start_local)}-{fmt_hour(end_local)}{RST}"
        return f"{bg} {label_peak} {RST} {WHITE}\u2192 ends in {t}{RST} {time_range}"
    else:
        if mins_until > 0:
            t = fmt_duration(mins_until)
            return f"{BG_GREEN} {label_offpeak} {RST} {DIM}peak in {t}{RST}"
        else:
            return f"{BG_GREEN} {label_offpeak} {RST}"


def _mins_until_next_peak(now, peak_days, start_local_hour):
    """Calculate minutes until the next peak window."""
    hour = now.hour + now.minute / 60.0
    weekday = now.isoweekday()

    for day_offset in range(1, 8):
        next_day = ((weekday - 1 + day_offset) % 7) + 1
        if next_day in peak_days:
            # Minutes until midnight + remaining full days + start hour
            mins = int((24 - hour) * 60) + (day_offset - 1) * 1440 + int(start_local_hour * 60)
            return mins
    return 0


# Backward compat: old name maps to new function
seg_promo_2x = seg_peak_hours


def seg_model(ctx):
    name = ctx["stdin"].get("model", {}).get("display_name", "")
    if not name:
        return ""
    short = name.split("(")[0].strip()
    return f"{BLUE}{short}{RST}"


def _fmt_tokens(n):
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n // 1_000}K"
    return str(n)

def seg_context(ctx):
    cw = ctx["stdin"].get("context_window", {})
    size = cw.get("context_window_size", 0)
    if not size:
        return ""
    usage = cw.get("current_usage", {})
    current = (
        usage.get("input_tokens", 0)
        + usage.get("cache_creation_input_tokens", 0)
        + usage.get("cache_read_input_tokens", 0)
    )
    pct = current * 100 // size if size > 0 else 0
    color = color_for_pct(pct)
    tier = ctx.get("config", {}).get("tier", "standard")
    if tier == "minimal":
        return f"{DIM}CTX{RST} {color}{pct}%{RST}"
    return f"{color}{_fmt_tokens(current)}/{_fmt_tokens(size)}{RST} {color}{pct}%{RST}"


def seg_git_branch(ctx):
    branch = git_cmd("branch", "--show-current")
    if not branch:
        return ""
    ctx["git_branch"] = branch
    return f"{DIM}{branch}{RST}"


def seg_git_dirty(ctx):
    branch = ctx.get("git_branch", "")
    porcelain = git_cmd("status", "--porcelain")
    uncommitted = len(porcelain.splitlines()) if porcelain else 0
    unpushed = 0
    if branch:
        ahead = git_cmd("rev-list", "--count", "@{u}..HEAD")
        if ahead and ahead != "0":
            unpushed = int(ahead)

    if not uncommitted and not unpushed:
        return f"{GREEN}clean{RST}"

    if uncommitted and unpushed:
        return f"{YELLOW}{uncommitted} changed, {unpushed} unpushed{RST}"
    elif uncommitted:
        return f"{YELLOW}{uncommitted} unsaved{RST}"
    else:
        return f"{YELLOW}{unpushed} unpushed{RST}"


def seg_git_ahead_behind(ctx):
    branch = ctx.get("git_branch", "")
    if not branch:
        return ""
    ahead = git_cmd("rev-list", "--count", f"@{{u}}..HEAD")
    behind = git_cmd("rev-list", "--count", f"HEAD..@{{u}}")
    parts = []
    if ahead and ahead != "0":
        parts.append(f"\u2191{ahead}")
    if behind and behind != "0":
        parts.append(f"\u2193{behind}")
    if not parts:
        return ""
    return f"{DIM}{''.join(parts)}{RST}"


def seg_cost(ctx):
    cost = ctx["stdin"].get("cost", {}).get("total_cost_usd")
    if cost is None:
        return f"{DIM}$?{RST}"
    return f"{MAGENTA}${cost:.2f}{RST}"


def seg_duration(ctx):
    ms = ctx["stdin"].get("cost", {}).get("total_duration_ms")
    if not ms:
        return ""
    secs = int(ms) // 1000
    return f"{BLUE}{fmt_seconds(secs)}{RST}"


def seg_lines(ctx):
    added = ctx["stdin"].get("cost", {}).get("total_lines_added", 0)
    removed = ctx["stdin"].get("cost", {}).get("total_lines_removed", 0)
    if not added and not removed:
        return ""
    return f"{GREEN}+{added}{RST}/{RED}-{removed}{RST}"


def seg_ts_errors(ctx):
    cwd = ctx["stdin"].get("cwd", "")
    if not cwd:
        return ""
    import tempfile as _tf
    h = hashlib.sha256(cwd.encode()).hexdigest()[:16]
    cache = Path(_tf.gettempdir()) / f"tsc-errors-{h}.txt"
    if not cache.exists():
        return ""
    try:
        age = time.time() - cache.stat().st_mtime
        if age > 300:
            return ""
        count = int(cache.read_text().strip().split()[0])
        if count > 0:
            return f"{RED}TS:{count}{RST}"
    except Exception:
        pass
    return ""


def seg_effort(ctx):
    """Show thinking effort level from settings.json."""
    try:
        settings_path = Path.home() / ".claude" / "settings.json"
        if settings_path.exists():
            settings = json.loads(settings_path.read_text())
            level = settings.get("effortLevel", "")
            if level:
                label = {"low": "e:LO", "medium": "e:MED", "high": "e:HI"}.get(level, "e:" + level.upper())
                color = {"low": DIM, "medium": YELLOW, "high": GREEN}.get(level, DIM)
                return f"{color}{label}{RST}"
    except Exception:
        pass
    return ""


def seg_env(ctx):
    """Show LOCAL or REMOTE based on SSH session detection."""
    if os.environ.get("SSH_CLIENT") or os.environ.get("SSH_TTY") or os.environ.get("SSH_CONNECTION"):
        return f"{MAGENTA}REMOTE{RST}"
    return f"{CYAN}LOCAL{RST}"


def seg_burn_rate(ctx):
    """Show $/hr burn rate and context depletion estimate."""
    cost_data = ctx["stdin"].get("cost", {})
    cost = cost_data.get("total_cost_usd")
    duration_ms = cost_data.get("total_duration_ms")
    if not cost or not duration_ms or float(duration_ms) < 60000:
        return f"{DIM}$?/hr{RST}"  # Need at least 1 min of data

    # Append a rolling-state sample so the 10-min window stays fresh
    cw_raw = ctx["stdin"].get("context_window", {})
    usage_raw = cw_raw.get("current_usage", {})
    _rs_append(
        cost=float(cost),
        tokens_in=usage_raw.get("input_tokens", 0),
        tokens_out=usage_raw.get("output_tokens", 0),
        cache_read=usage_raw.get("cache_read_input_tokens", 0),
        cache_creation=usage_raw.get("cache_creation_input_tokens", 0),
    )

    # Prefer rolling 10-min rate; fall back to lifetime rate so the user
    # always sees a number (labelled so they know which window it is).
    rate = _rs_rate(10)
    window_label = "10m"
    if rate is None or rate < 0.01:
        hours = float(duration_ms) / 3600000
        rate = float(cost) / hours if hours > 0 else 0
        window_label = "session"

    if rate < 0.01:
        return f"{DIM}$?/hr{RST}"

    rate_color = RED if rate >= 10 else YELLOW if rate >= 5 else MAGENTA
    if rate >= 10:
        sev_word = "high"
    elif rate >= 5:
        sev_word = "moderate"
    else:
        sev_word = "low"
    parts = [f"{DIM}spending{RST} {rate_color}${rate:.1f}/hr {sev_word} ({window_label}){RST}"]

    # Context depletion estimate using rolling tokens-out rate
    cw = ctx["stdin"].get("context_window", {})
    size = cw.get("context_window_size", 0)
    usage = cw.get("current_usage", {})
    current = (
        usage.get("input_tokens", 0)
        + usage.get("cache_creation_input_tokens", 0)
        + usage.get("cache_read_input_tokens", 0)
    )
    if size > 0 and current > 0:
        tokens_out_delta = _rs_tokens(10)
        if tokens_out_delta is not None and tokens_out_delta > 0:
            tokens_per_min = tokens_out_delta / 10
            remaining = size - current
            if remaining > 0:
                mins_left = int(remaining / tokens_per_min)
                if mins_left < 180:
                    color = RED if mins_left < 30 else YELLOW if mins_left < 60 else DIM
                    parts.append(f"{color}ctx full ~{fmt_duration(mins_left)}{RST}")

    return " ".join(parts)


def seg_cache_hit(ctx):
    """Show cache efficiency ratio with optional rolling delta."""
    cw = ctx["stdin"].get("context_window", {})
    usage = cw.get("current_usage", {})
    cache_read = usage.get("cache_read_input_tokens", 0)
    cache_create = usage.get("cache_creation_input_tokens", 0)
    total_cache = cache_read + cache_create
    if total_cache < 1000:
        return ""  # Not enough cache data to be meaningful
    hit_pct = cache_read * 100 // total_cache if total_cache > 0 else 0

    # Cache "savings %": reused tokens cost ~10% of fresh input, so
    # effective cost reduction ≈ hit_ratio × 0.90. Clamp to 0-90.
    savings_pct = max(0, min(90, int(hit_pct * 0.9)))

    delta = _rs_cache_delta(5)
    if delta is not None and delta > 0:
        delta_str = f"{delta / 1000:.1f}k" if delta >= 1000 else str(delta)
        pct_color = GREEN if delta > 500 else DIM
        # Active: ratio + delta + "saving X% cost" so user sees the money impact
        return (f"{DIM}cache reuse{RST} {pct_color}{hit_pct}% "
                f"\u2191{delta_str} saving ~{savings_pct}% cost{RST}")

    # Idle: still show the savings the cache unlocks when active
    return (f"{DIM}cache reuse{RST} {DIM}{hit_pct}% idle "
            f"(saves ~{savings_pct}% when active){RST}")


def seg_vim_mode(ctx):
    """Show vim mode (NORMAL/INSERT) when vim mode is active."""
    vim = ctx["stdin"].get("vim", {})
    mode = vim.get("mode", "")
    if not mode:
        return ""
    label = mode.upper()
    color = BLUE if mode == "normal" else GREEN
    return f"{color}{label}{RST}"


def seg_agent(ctx):
    """Show agent name and/or worktree when active."""
    parts = []
    agent = ctx["stdin"].get("agent", {})
    agent_name = agent.get("name", "")
    if agent_name:
        parts.append(f"{CYAN}{agent_name}{RST}")

    wt = ctx["stdin"].get("worktree", {})
    wt_name = wt.get("name", "")
    if wt_name:
        parts.append(f"{DIM}wt:{wt_name}{RST}")

    return " ".join(parts) if parts else ""


def seg_rate_limits(ctx):
    """Fetch rate limits from Claude OAuth API (cached 60s)."""
    cache_dir = Path.home() / ".claude"
    cache_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    cache_file = cache_dir / "statusline-usage-cache.json"

    usage_data = None
    now = time.time()

    # Check cache
    if cache_file.exists():
        try:
            age = now - cache_file.stat().st_mtime
            if age < 60:
                usage_data = json.loads(cache_file.read_text())
        except Exception:
            pass

    # Refresh if needed
    if usage_data is None:
        token = _get_oauth_token()
        if token:
            try:
                import urllib.request
                req = urllib.request.Request(
                    "https://api.anthropic.com/api/oauth/usage",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                        "anthropic-beta": "oauth-2025-04-20",
                        "User-Agent": "claude-code/2.1.34",
                    },
                )
                with urllib.request.urlopen(req, timeout=5) as resp:
                    usage_data = json.loads(resp.read())
                    cache_file.write_text(json.dumps(usage_data))
                    try:
                        os.chmod(cache_file, 0o600)
                    except Exception:
                        pass
            except Exception:
                pass

        # Fallback to stale cache
        if usage_data is None and cache_file.exists():
            try:
                usage_data = json.loads(cache_file.read_text())
            except Exception:
                pass

    if not usage_data:
        return ""

    # Store for full mode
    ctx["usage_data"] = usage_data

    # Build compact display for line 1
    fh = usage_data.get("five_hour", {})
    fh_pct = int(fh.get("utilization", 0))
    tier = ctx.get("config", {}).get("tier", "standard")

    # Add peak indicator to rate limit display
    peak_tag = ""
    if ctx.get("is_peak"):
        peak_tag = f" {YELLOW}\u26a1{RST}"

    if tier == "minimal":
        return f"{color_for_pct(fh_pct)}{fh_pct}%{RST} {DIM}5H{RST}{peak_tag}"
    return f"{build_usage_bar(fh_pct)} {color_for_pct(fh_pct)}{fh_pct}%{RST}{peak_tag}"


def _get_oauth_token():
    """Try to find Claude OAuth token."""
    token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "")
    if token:
        return token

    creds = Path.home() / ".claude" / ".credentials.json"
    if creds.exists():
        try:
            data = json.loads(creds.read_text())
            token = data.get("claudeAiOauth", {}).get("accessToken", "")
            if token:
                return token
        except Exception:
            pass

    try:
        r = subprocess.run(
            ["security", "find-generic-password", "-s", "Claude Code-credentials", "-w"],
            capture_output=True, text=True, timeout=3,
        )
        if r.returncode == 0 and r.stdout.strip():
            data = json.loads(r.stdout.strip())
            token = data.get("claudeAiOauth", {}).get("accessToken", "")
            if token:
                return token
    except Exception:
        pass

    return ""


# ══════════════════════════════════════════════════════════════════════════════
# FULL MODE — TIMELINE + RATE LIMITS
# ══════════════════════════════════════════════════════════════════════════════

def build_timeline(ctx):
    now = ctx["local_time"]
    hour, minute = now.hour, now.minute
    weekday = now.isoweekday()

    peak_start = ctx.get("peak_start_local", 15)
    peak_end = ctx.get("peak_end_local", 21)
    peak_days = ctx.get("peak_days", [1, 2, 3, 4, 5])
    is_peak_day = weekday in peak_days

    cursor_pos = hour * 2 + (1 if minute >= 30 else 0)

    bar = ""
    for i in range(48):
        h = i / 2.0
        if i == cursor_pos:
            bar += f"{WHITE}{BOLD}\u25cf{RST}"
        elif not is_peak_day:
            bar += f"{GREEN}\u2501{RST}"
        else:
            # Check if this half-hour is in peak
            in_peak = False
            if peak_end > peak_start:
                in_peak = peak_start <= h < peak_end
            else:
                in_peak = h >= peak_start or h < peak_end
            bar += f"{YELLOW}\u2501{RST}" if in_peak else f"{GREEN}\u2501{RST}"

    if not is_peak_day:
        return f"{DIM}\u2502{RST} {bar} {DIM}\u2502{RST}  {GREEN}\u2501 Off-Peak all day \u2714{RST}"

    # Show local peak hours range
    return (
        f"{DIM}\u2502{RST} {bar} {DIM}\u2502{RST}  "
        f"{GREEN}\u2501{RST}{DIM} off-peak{RST} "
        f"{YELLOW}\u2501{RST}{DIM} peak ({fmt_hour(peak_start)}-{fmt_hour(peak_end)}){RST}"
    )


def build_rate_limits_line(ctx):
    usage_data = ctx.get("usage_data")
    if not usage_data:
        return ""

    bw = 10

    fh = usage_data.get("five_hour", {})
    fh_pct = int(fh.get("utilization", 0))
    fh_reset = fh.get("resets_at", "")
    fh_bar = build_usage_bar(fh_pct, bw)
    fh_color = color_for_pct(fh_pct)

    sd = usage_data.get("seven_day", {})
    sd_pct = int(sd.get("utilization", 0))
    sd_reset = sd.get("resets_at", "")
    sd_bar = build_usage_bar(sd_pct, bw)
    sd_color = color_for_pct(sd_pct)

    # Peak indicator instead of 2x
    peak_tag = f" {YELLOW}\u26a1 peak{RST}" if ctx.get("is_peak") else f" {GREEN}\u2713{RST}"

    fh_time = _format_reset(fh_reset, "time")
    sd_time = _format_reset(sd_reset, "datetime")

    # Use remote labels if available
    schedule = ctx.get("schedule", {})
    labels = schedule.get("labels", {})
    fh_label = labels.get("five_hour", "5h")
    wk_label = labels.get("weekly", "weekly")

    current = f"{DIM}\u2502{RST} {GREEN}\u25b8{RST} {WHITE}{fh_label}{RST} {fh_bar} {fh_color}{fh_pct:3d}%{RST} {DIM}\u27f3{RST} {WHITE}{fh_time}{RST}"
    weekly = f"{WHITE}{wk_label}{RST} {sd_bar} {sd_color}{sd_pct:3d}%{RST} {DIM}\u27f3{RST} {WHITE}{sd_time}{RST}"

    return f"{current}{peak_tag} {DIM}\u00b7{RST} {weekly} {DIM}\u2502{RST}"


def _format_reset(iso_str, style="time"):
    if not iso_str or iso_str == "null":
        return ""
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        local = dt.astimezone()
        h = local.hour % 12 or 12
        ampm = 'am' if local.hour < 12 else 'pm'
        if style == "time":
            return f"{h}:{local.minute:02d}{ampm}"
        else:
            return f"{local.day}/{local.month} {h}:{local.minute:02d}{ampm}"
    except Exception:
        return ""


def build_metrics_line(ctx):
    """Line 4: spending + cache metrics. Delegates to seg_burn_rate +
    seg_cache_hit so the rolling-window logic is the single source of truth."""
    parts = []

    burn = seg_burn_rate(ctx)
    if burn:
        parts.append(f"{GREEN}\u25b8{RST} {burn}")

    cache = seg_cache_hit(ctx)
    if cache:
        parts.append(cache)

    if ctx.get("is_peak"):
        parts.append(f"{YELLOW}\u26a1 peak = limits drain faster{RST}")

    if not parts:
        return ""

    inner = f" {DIM}\u00b7{RST} ".join(parts)
    return f"{DIM}\u2502{RST} {inner} {DIM}\u2502{RST}"


# ══════════════════════════════════════════════════════════════════════════════
# SEGMENT REGISTRY
# ══════════════════════════════════════════════════════════════════════════════
SEGMENTS = {
    "time": seg_time,
    "banner": seg_banner,
    "peak_hours": seg_peak_hours,
    "promo_2x": seg_peak_hours,  # backward compat
    "model": seg_model,
    "context": seg_context,
    "cache_hit": seg_cache_hit,
    "burn_rate": seg_burn_rate,
    "vim_mode": seg_vim_mode,
    "agent": seg_agent,
    "git_branch": seg_git_branch,
    "git_dirty": seg_git_dirty,
    "git_ahead_behind": seg_git_ahead_behind,
    "cost": seg_cost,
    "duration": seg_duration,
    "lines": seg_lines,
    "ts_errors": seg_ts_errors,
    "rate_limits": seg_rate_limits,
    "effort": seg_effort,
    "env": seg_env,
}


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════
def main():
    config = load_config()
    maybe_heartbeat(config)
    debug(f"config: tier={config.get('tier')}")
    stdin_data = read_stdin()

    # Mode from args or config
    mode = config.get("mode", "minimal")
    for arg in sys.argv[1:]:
        if arg == "--full":
            mode = "full"
        elif arg == "--minimal":
            mode = "minimal"
        elif arg.startswith("--tier="):
            t = arg.split("=", 1)[1]
            config["tier"] = t
            if t != "full":
                mode = "minimal"

    # Get local time (auto-detect timezone)
    local_time, tz_name, local_offset = get_local_time()
    debug(f"timezone: {tz_name} (UTC{local_offset:+.0f})")

    # Load schedule (remote or cached)
    schedule = load_schedule(config)
    debug(f"schedule: mode={schedule.get('mode')} v={schedule.get('v')}")

    # Apply remote defaults (e.g., default tier) if user hasn't overridden
    apply_remote_defaults(config, schedule)

    ctx = {
        "config": config,
        "stdin": stdin_data,
        "mode": mode,
        "local_time": local_time,
        "local_offset": local_offset,
        "tz_name": tz_name,
        "schedule": schedule,
        "is_peak": False,
        "is_offpeak": True,
    }

    enabled = get_enabled_segments(config, schedule)

    # Inject banner at the start if present
    if "banner" not in enabled:
        enabled.insert(0, "banner")

    tier = config.get("tier", "standard")
    is_full_tier = tier == "full" or mode == "full"
    is_standard_tier = tier == "standard"
    # Standard and Full both need rate limits data for their extra lines
    if is_full_tier or is_standard_tier:
        seg_rate_limits(ctx)  # populates ctx["usage_data"]

    # Build line 1
    parts = []
    git_parts = []
    for name in enabled:
        if name in ("git_branch", "git_dirty", "git_ahead_behind"):
            fn = SEGMENTS.get(name)
            if fn:
                r = fn(ctx)
                if r:
                    git_parts.append(r)
        else:
            fn = SEGMENTS.get(name)
            if fn:
                r = fn(ctx)
                if r:
                    parts.append(r)

    if git_parts:
        parts.append(" ".join(git_parts))

    # Flow design: colored arrows (green=off-peak, yellow=peak)
    arrow_color = YELLOW if ctx.get("is_peak") else GREEN
    arrow = f" {arrow_color}\u25b8{RST} "
    line1 = arrow.join(parts)
    print(line1, end="")

    # Standard tier: line 2 = rate limits only
    if is_standard_tier and not is_full_tier:
        rate_line = build_rate_limits_line(ctx)
        if rate_line:
            print(f"\n{rate_line}", end="")

    # Full tier: additional lines (line 2, 3, 4)
    if is_full_tier:
        features = schedule.get("features", {})

        # full mode: line 2 — visual 24h timeline. Always rendered (even on
        # off-peak days) so the bar is a consistent anchor; a day with no
        # peak window is a legitimate visual state, not a broken statusline.
        if features.get("show_timeline", True):
            timeline = build_timeline(ctx)
            if timeline:
                print(f"\n\n{timeline}", end="")

        # full mode: line 3 — rate limit bars (5h window + weekly)
        rate_line = build_rate_limits_line(ctx)
        if rate_line:
            print(f"\n{rate_line}", end="")

        # full mode: line 4 — burn rate, cache hit ratio, session metrics
        metrics = build_metrics_line(ctx)
        if metrics:
            print(f"\n{metrics}", end="")


TELEMETRY_URL = "https://statusline-telemetry.nadavf.workers.dev/ping"
HEARTBEAT_PATH = Path.home() / ".claude" / ".statusline-heartbeat"
TELEMETRY_ID_PATH = Path.home() / ".claude" / ".statusline-telemetry-id"


def _get_telemetry_id():
    try:
        TELEMETRY_ID_PATH.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if TELEMETRY_ID_PATH.exists():
            existing = TELEMETRY_ID_PATH.read_text().strip().lower()
            if len(existing) == 16 and all(ch in "0123456789abcdef" for ch in existing):
                return existing

        import secrets

        uid = secrets.token_hex(8)
        TELEMETRY_ID_PATH.write_text(uid)
        try:
            os.chmod(TELEMETRY_ID_PATH, 0o600)
        except Exception:
            pass
        return uid
    except Exception:
        return ""

def _telemetry_disabled(config):
    return config.get("telemetry") is False or os.getenv("STATUSLINE_DISABLE_TELEMETRY") == "1"

def maybe_heartbeat(config):
    """Send a daily heartbeat. Fire-and-forget, never blocks."""
    if _telemetry_disabled(config):
        return
    try:
        uid = _get_telemetry_id()
        if not uid:
            return
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # ── Daily heartbeat ──────────────────────────────────────────────────
        if HEARTBEAT_PATH.exists():
            mtime = datetime.fromtimestamp(HEARTBEAT_PATH.stat().st_mtime, tz=timezone.utc)
            if mtime.strftime("%Y-%m-%d") == today:
                return
        payload = json.dumps({
            "id": uid, "v": "2.1", "engine": "python",
            "tier": config.get("tier", "standard"),
            "os": sys.platform, "event": "heartbeat",
        })
        HEARTBEAT_PATH.write_text(today)
        subprocess.Popen(
            ["curl", "-s", "-o", os.devnull, "--max-time", "3",
             "-X", "POST", "-H", "Content-Type: application/json",
             "-d", payload, TELEMETRY_URL],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


if __name__ == "__main__":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    main()
