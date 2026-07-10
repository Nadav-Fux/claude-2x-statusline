#!/usr/bin/env python3
"""Claude Code statusline — modular Python engine.

Reads JSON from stdin (provided by Claude Code) + config file,
runs enabled segments, outputs ANSI-colored status line.

v2.2 — Peak hours awareness with auto-timezone and remote schedule.
"""
import sys
import json
import os
import re
import subprocess
import hashlib
import time
import unicodedata
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
    set_session_id as _rs_set_session_id,
)
from workflows import (
    detect_live_workflows as _wf_detect_live,
    find_session_dir as _wf_find_session_dir,
    read_completed_workflows as _wf_read_completed,
    workflow_cache_key as _wf_cache_key,
)
import usage_providers as _usage_providers
import gateway as _gateway
import session_cockpit as _session_cockpit
import job_monitor as _job_monitor

DEBUG = os.environ.get("STATUSLINE_DEBUG") == "1"
_WF_CACHE = {}

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
# Truecolor purple — owner-requested addition to the palette (session-quality
# line: the ⚒ tool-call counter and the eff efficiency dots).
PURPLE = "\033[38;2;178;148;255m"
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
TIER_PRESETS = {
    # Minimal: essentials only — model, compact context, rate limit %, git.
    # workflows is included so an active/idle workflow spend never vanishes on a
    # tier switch (the segment self-hides when there's nothing to report).
    "minimal": ["model", "context", "workflows", "tasks", "git_branch", "git_dirty", "rate_limits", "env"],
    # Standard: clean line 1 + line 2 with rate limits (5h + weekly)
    "standard": ["model", "context", "vim_mode", "agent", "workflows", "tasks", "git_branch", "git_dirty", "cost", "effort", "env"],
    # Full: clean line 1 + dashboard below with rate limits, spending, cache (with explanations)
    "full": ["model", "context", "vim_mode", "agent", "workflows", "tasks", "git_branch", "git_dirty", "cost", "usage_credits", "effort", "env"],
    # Line 1 stays clean: model, context, cost, effort, LOCAL, git. The Claude
    # rate-limit dashboard + external provider rows + metrics render below in
    # full mode; the promo banner is moved to the very last line (see main()).
    "multi-cli": ["model", "context", "cost", "effort", "env", "git_branch", "git_dirty"],
}

DEFAULT_CONFIG = {
    "tier": "standard",
    "segments": {},
    "timezone": "auto",
    "separator": " | ",
    "mode": "minimal",
    "full_mode_rate_limits": True,
    "full_mode_timeline": True,
    "gateway_awareness": True,
    # fork note: override via schedule_url in config
    "schedule_url": "https://raw.githubusercontent.com/Nadav-Fux/claude-2x-statusline/main/schedule.json",
    "schedule_cache_hours": 3,
    "external_providers": {
        "enabled": False,
        "codex": {"enabled": True},
        "glm": {"enabled": True, "base_url": "https://api.z.ai", "api_key": ""},
        "droid": {"enabled": False},
        "antigravity": {"enabled": False},
    },
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


def normalize_schedule(value):
    if not isinstance(value, dict):
        return None

    schedule = dict(DEFAULT_SCHEDULE)
    schedule.update(value)

    peak = schedule.get("peak")
    if isinstance(peak, dict):
        merged_peak = dict(DEFAULT_SCHEDULE["peak"])
        merged_peak.update(peak)
        schedule["peak"] = merged_peak
    else:
        schedule["peak"] = dict(DEFAULT_SCHEDULE["peak"])

    for key in ("features", "banner", "release", "labels"):
        if not isinstance(schedule.get(key), dict):
            schedule[key] = dict(DEFAULT_SCHEDULE.get(key, {}))

    return schedule


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
# Canonical external-provider render order (claude is the rate-limit line, not
# an external row, so it is not in this tuple).
_EXTERNAL_PROVIDER_ORDER = ("codex", "glm", "droid", "antigravity", "copilot")


def migrate_providers(config):
    """Ensure an in-memory ``providers`` selection block exists.

    Pure and idempotent. When a user config already carries a
    ``providers.selected`` array it is left untouched. When absent (every
    existing install pre-Phase-1), a block is derived from the legacy
    ``external_providers`` enabled flags:

        selected = ["claude"] + [p for p in <order> if external_providers[p].enabled is True]

    so an existing cockpit renders exactly the same providers it did before.

    IMPORTANT: this only mutates the passed dict in memory and NEVER writes the
    config file. The render path must stay read-only; persisting a selection is
    the onboarding writer's job (lib/onboarding.apply_selection).
    """
    if not isinstance(config, dict):
        return config
    providers = config.get("providers")
    if isinstance(providers, dict) and isinstance(providers.get("selected"), list):
        return config
    external = config.get("external_providers")
    external = external if isinstance(external, dict) else {}
    selected = ["claude"]
    for provider in _EXTERNAL_PROVIDER_ORDER:
        pc = external.get(provider)
        if isinstance(pc, dict) and pc.get("enabled") is True:
            selected.append(provider)
    config["providers"] = {"schema_version": 1, "selected": selected}
    return config


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
    migrate_providers(config)
    return config


def load_claude_settings():
    settings_path = Path.home() / ".claude" / "settings.json"
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


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
            cached = normalize_schedule(json.loads(cache_path.read_text()))
            if cached is None:
                raise ValueError("invalid schedule cache")
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
                data = normalize_schedule(json.loads(resp.read()))
                if data is None:
                    raise ValueError("invalid schedule payload")
                cache_path.write_text(json.dumps(data, indent=2))
                debug("schedule: fetched remote")
                return data
        except Exception as e:
            debug(f"schedule: remote fetch failed: {e}")

    # Fallback to stale cache
    if cache_path.exists():
        try:
            cached = normalize_schedule(json.loads(cache_path.read_text()))
            if cached is not None:
                return cached
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


_HOUR_WINDOW_RE = re.compile(r"^\d+h$")


def _is_long_window_label(label):
    """Window-duration rule for usage-bar color thresholds (see color_for_pct).

    A label naming a sub-day window ('5h', '12h', ...) is SHORT. Every other
    label -- '7d'/'30d' (Codex/Antigravity), 'weekly'/'wk' (Claude/Antigravity),
    GLM's token-quota 'tok', Copilot's monthly meter -- is LONG: it covers a
    week/month/token-quota, not hours, so it should warn earlier. Mirrors the
    existing 5h-vs-longer split used for reset-clock formatting
    (_reset_style_for_label in lib/usage_providers). An unlabeled/unrecognized
    bar defaults to SHORT (today's thresholds) rather than guessing.
    """
    text = str(label or "").strip().lower()
    if not text:
        return False
    return not _HOUR_WINDOW_RE.match(text)


def color_for_pct(pct, long_window=False):
    """Usage-bar color thresholds.

    Windows longer than a day (weekly/monthly/token-quota) warn earlier --
    red >=75 / yellow >=45 -- than sub-day windows like the Claude 5h bucket,
    which keep the tighter red >=80 / yellow >=50. Pass long_window=True for
    any weekly-or-longer bar; see _is_long_window_label for the label rule
    that decides this at the call site.
    """
    if long_window:
        if pct >= 75:
            return RED
        elif pct >= 45:
            return YELLOW
        return GREEN
    if pct >= 80:
        return RED
    elif pct >= 50:
        return YELLOW
    return GREEN


def _as_float(value, default=0.0):
    """Coerce possibly-null/garbage cache values to float (None → default)."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def build_usage_bar(pct, width=10, long_window=False):
    pct = max(0, min(100, pct))
    filled = pct * width // 100
    empty = width - filled
    color = color_for_pct(pct, long_window)
    filled_chars = "\u25b0" * filled
    empty_chars = "\u25b1" * empty
    return f"{color}{filled_chars}{DIM}{empty_chars}{RST}"


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_TASK_NAME_RE = re.compile(r"^\d+\.json$")  # numeric task files in ~/.claude/tasks/<sid>/
# A tool-use content block inside a transcript JSONL line, e.g.
# {"type":"tool_use","id":"toolu_...",...}. Matched as raw text (not parsed
# JSON) so a multi-MB transcript is one regex scan, not N json.loads calls —
# same tradeoff as workflows.py's _USAGE_PATTERN.
_TOOL_USE_RE = re.compile(r'"type"\s*:\s*"tool_use"')


def visible_width(s):
    """Display columns of a string: strips ANSI SGR codes, counts wide chars as 2."""
    plain = _ANSI_RE.sub("", s)
    w = 0
    for ch in plain:
        w += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return w


def resolve_render_width(config):
    """Target line width for reflow, or 0 to disable wrapping.

    Claude Code exports COLUMNS = the terminal width before running the
    statusline (v2.1.153+); that makes the bar responsive to the window. An
    explicit config "max_width" caps it (useful for keeping lines short on wide
    terminals); config "reflow": false turns wrapping off entirely.
    """
    if config.get("reflow") is False:
        return 0
    try:
        cols = int(os.environ.get("COLUMNS", "0") or 0)
    except (TypeError, ValueError):
        cols = 0
    try:
        cap = int(config.get("max_width", 0) or 0)
    except (TypeError, ValueError):
        cap = 0
    if cols > 0 and cap > 0:
        return min(cols, cap)
    return cols or cap


def reflow_parts(parts, sep, width):
    """Pack parts onto lines, wrapping to a new line when the next part would
    exceed width. Keeps at least one part per line (never truncates content)."""
    lines, cur, cur_w = [], [], 0
    sep_w = visible_width(sep)
    for p in parts:
        pw = visible_width(p)
        add = pw if not cur else pw + sep_w
        if cur and cur_w + add > width:
            lines.append(sep.join(cur))
            cur, cur_w = [p], pw
        else:
            cur.append(p)
            cur_w += add
    if cur:
        lines.append(sep.join(cur))
    return lines


def render_dashboard_line(parts, width, trailing=""):
    """Render bordered dashboard parts as one row (│ ▸ a · b · c │) on wide
    terminals, or wrap to several rows when narrow. Every row carries the │
    border on both sides (leading row keeps the ▸ marker; trailing goes on the
    last row before the closing border), matching the single-row form."""
    if not parts:
        return ""
    border = f"{DIM}│{RST}"
    head = f"{border} {GREEN}▸{RST} "
    cont = f"{border}   "
    sep = f" {DIM}·{RST} "
    one_line = f"{head}{sep.join(parts)}{trailing} {border}"
    if width <= 0 or visible_width(one_line) <= width:
        return one_line
    # Reserve columns for the prefix and the closing " │" so rows stay <= width.
    avail = max(1, width - visible_width(head) - 2)
    rows = reflow_parts(parts, sep, avail)
    last = len(rows) - 1
    out = []
    for i, row in enumerate(rows):
        prefix = head if i == 0 else cont
        tail = trailing if i == last else ""
        out.append(f"{prefix}{row}{tail} {border}")
    return "\n".join(out)


def git_cmd(*args, timeout=2):
    try:
        r = subprocess.run(
            ["git"] + list(args),
            capture_output=True, text=True, timeout=timeout
        )
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def parse_git_shortstat(text):
    text = str(text or "")

    def read(pattern):
        match = re.search(pattern, text)
        return int(match.group(1)) if match else 0

    return {
        "insertions": read(r"(\d+)\s+insertions?\(\+\)"),
        "deletions": read(r"(\d+)\s+deletions?\(-\)"),
        "files": read(r"(\d+)\s+files?\s+changed"),
    }


def _repo_cwd(ctx):
    stdin = (ctx or {}).get("stdin") or {}
    workspace = stdin.get("workspace") if isinstance(stdin.get("workspace"), dict) else {}
    return str(stdin.get("cwd") or workspace.get("current_dir") or os.getcwd())


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

    banner_list = schedule.get("banners", [])
    if not isinstance(banner_list, list):
        banner_list = []
    if not banner_list:
        banner = schedule.get("banner", {})
        if isinstance(banner, dict) and banner.get("text"):
            banner_list = [banner]

    color_map = {"yellow": BG_YELLOW, "red": BG_RED, "green": BG_GREEN, "blue": BG_BLUE, "gray": BG_GRAY}
    for banner in banner_list:
        if not isinstance(banner, dict):
            continue
        text = banner.get("text", "")
        if not text:
            continue
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


def seg_gateway(ctx):
    text = _gateway.gateway_badge_text(ctx.get("gateway"))
    return f"{DIM}{CYAN}{text}{RST}" if text else ""


def _fmt_tokens(n):
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n // 1_000}K"
    return str(n)

def _model_window_from_name(name):
    """Context window encoded in a model name: '[1m]' -> 1_000_000,
    '(500k context)' -> 500_000. Only matches a number+unit in brackets/parens
    or next to a context/token word, so version numbers never false-match.
    Mirrors the narrator's resolver so statusline and narrator agree. Returns
    tokens, or 0 when the name encodes no window."""
    if not name:
        return 0
    for rx in (
        re.compile(r"[\[(]\s*(\d+(?:\.\d+)?)\s*([mk])\b", re.I),
        re.compile(r"(\d+(?:\.\d+)?)\s*([mk])\s*(?:context|tokens?|ctx|window)", re.I),
    ):
        m = rx.search(name)
        if m:
            n = float(m.group(1))
            return int(n * (1_000_000 if m.group(2).lower() == "m" else 1_000))
    return 0


def _resolve_ctx_window(ctx):
    """True context window size. Claude Code can report context_window_size=200000
    on stdin even for a [1m] session, which mis-scales the % ~5x and fires false
    'context full' pressure at ~16% of a 1M window. A window encoded in the model
    name (e.g. 'Opus 4.8 (1M context)', id 'claude-opus-4-8[1m]') is authoritative
    and overrides the (wrong) stdin size."""
    stdin = ctx.get("stdin", {}) or {}
    model = stdin.get("model", {}) or {}
    win = _model_window_from_name(f"{model.get('display_name', '')} {model.get('id', '')}")
    if win:
        return win
    return int((stdin.get("context_window", {}) or {}).get("context_window_size", 0) or 0)


def seg_context(ctx):
    size = _resolve_ctx_window(ctx)
    cw = ctx["stdin"].get("context_window", {})
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
        return f"{GREEN}saved{RST}"

    if uncommitted and unpushed:
        return f"{YELLOW}{uncommitted} changed, {unpushed} unpushed{RST}"
    elif uncommitted:
        return f"{YELLOW}{uncommitted} unsaved{RST}"
    else:
        return f"{YELLOW}{unpushed} unpushed{RST}"


def seg_churn(ctx):
    stats = parse_git_shortstat(git_cmd("-C", _repo_cwd(ctx), "diff", "--shortstat", "HEAD"))
    if not stats["files"] and not stats["insertions"] and not stats["deletions"]:
        return ""
    return f"{DIM}{BLUE}\u0394 +{stats['insertions']} \u2212{stats['deletions']} \u00b7 {stats['files']}f{RST}"


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
    if ctx.get("gateway", {}).get("foreign"):
        return ""
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
        settings = ctx.get("settings") or load_claude_settings()
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
    if ctx.get("gateway", {}).get("foreign"):
        return ""
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
    size = _resolve_ctx_window(ctx)
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
            # Only project "ctx full" once the window is genuinely filling
            # (>= 70%). A fast burn at 30-54% extrapolates a scary countdown
            # while there is still huge headroom — a false "full" alarm.
            if remaining > 0 and current * 100 / size >= 70:
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
    # Stashed for seg_eff, which turns this same ratio into purple dots on the
    # session-quality line instead of recomputing it.
    ctx["cache_hit_pct"] = hit_pct

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


def seg_eff(ctx):
    """Efficiency dots: the cache-reuse ratio seg_cache_hit already computed,
    mapped 0-100% -> 0-5 filled purple dots (round half up). No letters, no
    "grade" wording -- just dots. Self-hides whenever seg_cache_hit did (not
    enough cache data yet), so it never shows a score with nothing behind it."""
    hit_pct = ctx.get("cache_hit_pct")
    if hit_pct is None:
        return ""
    filled = max(0, min(5, int(hit_pct / 100 * 5 + 0.5)))
    filled_dots = "●" * filled
    empty_dots = "○" * (5 - filled)
    return f"{DIM}eff{RST} {PURPLE}{filled_dots}{DIM}{empty_dots}{RST}"


def seg_tool_count(ctx):
    """This session's tool-call count: literal '"type":"tool_use"' occurrences
    in the transcript JSONL named by stdin's transcript_path. Cached by
    session_id + transcript mtime under $TMPDIR/claude/ (never under
    ~/.claude/ -- this is a throwaway render cache, not user config/state).
    A missing/unreadable transcript omits the whole segment; it never renders
    a placeholder."""
    stdin = ctx.get("stdin", {}) or {}
    session_id = stdin.get("session_id", "")
    transcript_path = stdin.get("transcript_path", "")
    if not session_id or not transcript_path:
        return ""
    try:
        mtime = os.path.getmtime(transcript_path)
    except OSError:
        return ""

    import tempfile as _tf

    h = hashlib.sha256(session_id.encode()).hexdigest()[:16]
    cache_dir = Path(_tf.gettempdir()) / "claude"
    cache_file = cache_dir / f"statusline-toolcount-{h}.json"

    count = None
    try:
        cached = json.loads(cache_file.read_text(encoding="utf-8"))
        if cached.get("mtime") == mtime:
            count = int(cached.get("count", 0))
    except Exception:
        count = None

    if count is None:
        try:
            text = Path(transcript_path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
        count = len(_TOOL_USE_RE.findall(text))
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
            tmp = cache_file.with_name(f"{cache_file.name}.{os.getpid()}.tmp")
            tmp.write_text(json.dumps({"mtime": mtime, "count": count}), encoding="utf-8")
            os.replace(str(tmp), str(cache_file))
        except Exception:
            pass

    return f"{PURPLE}⚒{RST} {DIM}{count}{RST}"


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


def _wf_peak_path(session_dir):
    return session_dir / ".statusline-wf-peak.json"


def _wf_load_peak(session_dir):
    """Session high-water-mark of workflow tokens/runs (survives idle + tier switch)."""
    try:
        data = json.loads(_wf_peak_path(session_dir).read_text(encoding="utf-8"))
        return {"peak_tokens": int(data.get("peak_tokens", 0)), "peak_runs": int(data.get("peak_runs", 0))}
    except Exception:
        return {"peak_tokens": 0, "peak_runs": 0}


def _wf_save_peak(session_dir, tokens, runs):
    try:
        p = _wf_peak_path(session_dir)
        tmp = p.with_name(f"{p.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps({"peak_tokens": int(tokens), "peak_runs": int(runs)}), encoding="utf-8")
        os.replace(str(tmp), str(p))
    except Exception:
        pass


def seg_workflows(ctx):
    """Workflow agent context footprint: live, or the persistent session total.

    Tracks a per-session high-water-mark of cumulative workflow tokens/runs so the
    spend never silently vanishes \u2014 not when the workflow finishes, not when a run
    is interrupted without a completion manifest, and not on a tier switch.
    """
    session_dir = _wf_find_session_dir(ctx.get("stdin", {}))
    if not session_dir:
        ctx["_wf_live"] = []
        ctx["_wf_completed"] = {}
        return ""

    cache_key = _wf_cache_key(session_dir)
    if _WF_CACHE.get("key") == cache_key:
        cached = _WF_CACHE.get("payload", {})
        ctx["_wf_live"] = cached.get("live", [])
        ctx["_wf_completed"] = cached.get("completed", {})
        return _WF_CACHE.get("result", "")

    live = _wf_detect_live(session_dir)
    completed = _wf_read_completed(session_dir)
    live_agents = sum(item["agents"] for item in live)
    live_tokens = sum(item["tokens"] for item in live)

    # Update the session high-water-mark (cumulative = completed + current live).
    session_tokens = completed["total_tokens"] + live_tokens
    session_runs = completed["run_count"] + len(live)
    peak = _wf_load_peak(session_dir)
    peak_tokens = max(peak["peak_tokens"], session_tokens)
    peak_runs = max(peak["peak_runs"], session_runs)
    if peak_tokens != peak["peak_tokens"] or peak_runs != peak["peak_runs"]:
        _wf_save_peak(session_dir, peak_tokens, peak_runs)

    if live:
        result = f"{CYAN}\u2699 {live_agents} agents ctx \u03a3 {_fmt_tokens(live_tokens)}{RST}"
    elif peak_tokens > 0:
        result = (
            f"{DIM}wf idle \u00b7 \u03a3 {RST}{WHITE}{_fmt_tokens(peak_tokens)}{RST}"
            f"{DIM} \u00b7 {peak_runs} runs{RST}"
        )
    else:
        result = ""

    ctx["_wf_live"] = live
    ctx["_wf_completed"] = completed
    _WF_CACHE.update({"key": cache_key, "result": result, "payload": {"live": live, "completed": completed}})
    return result


def seg_rate_limits(ctx):
    """Fetch rate limits from Claude OAuth API (cached 60s)."""
    if ctx.get("gateway", {}).get("foreign"):
        return ""
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
    # Record cache age so downstream rows can flag frozen data: a healthy fetch
    # rewrites the cache every render (age < 60s TTL), while a failing OAuth
    # fetch falls back to the stale cache above without updating mtime, so the
    # age keeps climbing. Without this the fallback is silent for hours.
    try:
        ctx["usage_cache_age"] = time.time() - cache_file.stat().st_mtime
    except Exception:
        ctx["usage_cache_age"] = None

    # Build compact display for line 1
    fh = usage_data.get("five_hour", {})
    fh_pct = int(fh.get("utilization", 0))
    tier = ctx.get("config", {}).get("tier", "standard")

    if tier == "minimal":
        return f"{color_for_pct(fh_pct)}{fh_pct}%{RST} {DIM}5H{RST}"
    return f"{build_usage_bar(fh_pct)} {color_for_pct(fh_pct)}{fh_pct}%{RST}"


def seg_usage_credits(ctx):
    """Show extra_usage / SDK-credit overflow status from usage cache."""
    usage_data = ctx.get("usage_data")
    if not usage_data:
        return ""

    extra = usage_data.get("extra_usage", {})
    if not isinstance(extra, dict) or not extra:
        return ""

    enabled = bool(extra.get("enabled", False))
    consumed = _as_float(extra.get("consumed_usd"))
    limit = _as_float(extra.get("limit_usd"))

    if not enabled and consumed == 0:
        return ""

    if not enabled:
        return f"{DIM}overflow: off{RST}"

    if limit > 0:
        pct = int(consumed * 100 / limit)
        bar = build_usage_bar(pct, 8)
        color = color_for_pct(pct)
        return f"{DIM}overflow{RST} {bar} {color}${consumed:.2f}/${limit:.0f}{RST}"

    return f"{DIM}overflow{RST} {YELLOW}${consumed:.2f}{RST}"


def seg_auth_mode(ctx):
    """Warn on exported API key; otherwise show detected Claude auth mode."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    oauth_token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "")

    if api_key:
        return f"{BG_RED} API-KEY EXPORTED - claude -p bills API acct {RST}"

    if oauth_token:
        if oauth_token.startswith("sk-ant-oat01-"):
            return f"{DIM}auth:setup-token{RST}"
        return f"{DIM}auth:oauth{RST}"

    creds_path = Path.home() / ".claude" / ".credentials.json"
    if creds_path.exists():
        try:
            data = json.loads(creds_path.read_text(encoding="utf-8"))
            if data.get("claudeAiOauth", {}).get("accessToken"):
                return f"{DIM}auth:oauth{RST}"
        except Exception:
            pass

    return f"{DIM}auth:?{RST}"


def _sdk_exhaustion_suffix(ctx, pct):
    """BLOCKED / overflow-ON indicator once the SDK credit pool is exhausted."""
    if pct < 100:
        return ""
    extra = (ctx.get("usage_data") or {}).get("extra_usage")
    overflow_enabled = isinstance(extra, dict) and bool(extra.get("enabled", False))
    if overflow_enabled:
        return f" {YELLOW}overflow ON{RST}"
    return f" {BG_RED} BLOCKED {RST}"


def seg_sdk_meter(ctx):
    """Show month-to-date SDK credit burn vs plan ceiling."""
    sdk_direct = (ctx.get("usage_data") or {}).get("sdk_credit")
    if isinstance(sdk_direct, dict) and sdk_direct.get("remaining_usd") is not None:
        limit = _as_float(sdk_direct.get("limit_usd"))
        remaining = _as_float(sdk_direct.get("remaining_usd"))
        consumed = max(0.0, limit - remaining)
        if limit <= 0 or consumed == 0:
            return ""
        pct = int(consumed * 100 / limit)
        suffix = _sdk_exhaustion_suffix(ctx, pct)
        return f"{DIM}sdk{RST} {build_usage_bar(pct, 8)} {color_for_pct(pct)}${consumed:.2f}/${limit:.0f}{RST}{suffix}"

    # The ledger is externally fed (no official SDK-credit endpoint yet);
    # render it only when stamped for the current month so stale data is
    # never presented as live.
    ledger_path = Path.home() / ".claude" / "statusline-sdk-ledger.json"
    if not ledger_path.exists():
        return ""

    try:
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    except Exception:
        return ""
    if not isinstance(ledger, dict):
        return ""

    current_month = datetime.now().strftime("%Y-%m")
    if str(ledger.get("month", "")) != current_month:
        return ""

    consumed = _as_float(ledger.get("month_total_usd"))
    ceiling = _as_float(ledger.get("plan_ceiling_usd"), 20.0)
    if consumed == 0:
        return ""

    pct = int(consumed * 100 / ceiling) if ceiling > 0 else 0
    color = color_for_pct(pct)
    bar = build_usage_bar(pct, 8)
    suffix = _sdk_exhaustion_suffix(ctx, pct)

    return f"{DIM}sdk{RST} {bar} {color}${consumed:.2f}/${ceiling:.0f}{RST}{DIM} ~per-machine approx{RST}{suffix}"


_KEYCHAIN_SERVICE = "Claude Code-credentials"


def _claude_token_from_json(raw):
    """Pull claudeAiOauth.accessToken out of a credentials blob, or '' if the
    blob is something else (e.g. an mcpOAuth item stored under the same name)."""
    try:
        return json.loads(raw).get("claudeAiOauth", {}).get("accessToken", "") or ""
    except Exception:
        return ""


def _keychain_read(args):
    try:
        r = subprocess.run(
            ["security", "find-generic-password", "-s", _KEYCHAIN_SERVICE, *args, "-w"],
            capture_output=True, text=True, timeout=3,
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except Exception:
        pass
    return ""


def _keychain_accounts_for_service(dump):
    """Extract accounts belonging to _KEYCHAIN_SERVICE from `security
    dump-keychain` output. Handles both the quoted string form
    (`"acct"<blob>="name"`) and the hex-blob form (`"acct"<blob>=0x...`) macOS
    emits for non-ASCII accounts. Associates each account with its own item's
    service so a foreign block can't leak in on a loose substring match."""
    accounts = []
    svc_ok = False
    acct = None

    def _flush():
        if svc_ok and acct and acct not in accounts:
            accounts.append(acct)

    for line in dump.splitlines():
        if line.startswith("keychain:"):
            _flush()
            svc_ok, acct = False, None
        s = line.strip()
        if s.startswith('"svce"<blob>=') and f'"{_KEYCHAIN_SERVICE}"' in s:
            svc_ok = True
        elif s.startswith('"acct"<blob>=0x'):
            hexpart = s[len('"acct"<blob>=0x'):].split(" ", 1)[0]
            try:
                acct = bytes.fromhex(hexpart).decode("utf-8", "replace")
            except Exception:
                acct = None
        elif s.startswith('"acct"<blob>="'):
            m = re.match(r'"acct"<blob>="(.*)"$', s)
            acct = m.group(1) if m else None
    _flush()
    return accounts


def _keychain_claude_token():
    """Read the Claude OAuth token from the macOS keychain, tolerant of multiple
    items sharing the 'Claude Code-credentials' service name.

    Claude Code stores MCP-server OAuth tokens under the SAME service name but a
    different account, and `security find-generic-password -s ... -w` returns
    only the FIRST match — which may be an MCP item whose claudeAiOauth block is
    empty. Resolution order, cheapest first:
      1. First match already carries the token.
      2. Account == the OS username (the common case) — avoids scanning the
         whole keychain, and sidesteps the security/perf cost of dump-keychain.
      3. Last resort: enumerate accounts under the service via dump-keychain,
         skipping accounts already tried, under a hard wall-clock budget so a
         keychain full of same-named MCP items can't stall the render.
    """
    # 1. Fast path: the first match already carries the Claude token.
    token = _claude_token_from_json(_keychain_read([]))
    if token:
        return token

    tried = set()

    # 2. Common case: the account name is the OS username.
    try:
        import getpass
        user = getpass.getuser()
    except Exception:
        user = os.environ.get("USER", "")
    if user:
        tried.add(user)
        token = _claude_token_from_json(_keychain_read(["-a", user]))
        if token:
            return token

    # 3. Last resort: enumerate accounts (bounded), skipping ones already tried.
    try:
        dump = subprocess.run(
            ["security", "dump-keychain"], capture_output=True, text=True, timeout=4
        ).stdout
    except Exception:
        return ""

    deadline = time.time() + 2.0
    for acct in _keychain_accounts_for_service(dump):
        if acct in tried or time.time() > deadline:
            continue
        tried.add(acct)
        token = _claude_token_from_json(_keychain_read(["-a", acct]))
        if token:
            return token
    return ""


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

    return _keychain_claude_token()


# ══════════════════════════════════════════════════════════════════════════════
# FULL MODE — TIMELINE + RATE LIMITS
# ══════════════════════════════════════════════════════════════════════════════

def build_timeline(ctx):
    # mode=normal (no peak restrictions): no peak/off-peak legend to draw —
    # hide the timeline entirely (same gate as seg_peak_hours).
    schedule = ctx.get("schedule") or {}
    if schedule.get("mode") == "normal":
        return ""

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
        timeline = f"{DIM}\u2502{RST} {bar} {DIM}\u2502{RST}  {GREEN}\u2501 Off-Peak all day \u2714{RST}"
    else:
        # Show local peak hours range
        timeline = (
            f"{DIM}\u2502{RST} {bar} {DIM}\u2502{RST}  "
            f"{GREEN}\u2501{RST}{DIM} off-peak{RST} "
            f"{YELLOW}\u2501{RST}{DIM} peak ({fmt_hour(peak_start)}-{fmt_hour(peak_end)}){RST}"
        )

    # Responsive guard: a 48-slot bar is ~48 visible columns plus legend text.
    # On narrow terminals it overflows and wraps mid-bar, which is worse than
    # no timeline at all.  Hide when the rendered string won't fit.
    render_width = ctx.get("render_width", 0)
    if render_width > 0 and visible_width(timeline) > render_width:
        return ""
    return timeline


def _usage_stale_marker(ctx):
    """Dim '·stale <age>' marker when the Claude usage cache is far older than
    its 60s fetch TTL — i.e. the OAuth usage fetch has been failing and the
    5h/weekly numbers are frozen on stale-cache fallback. Surfaces silently
    frozen data so it can't masquerade as live for hours."""
    age = ctx.get("usage_cache_age")
    # 600s (10 min): comfortably above the render cadence + a short idle gap, so
    # an idle terminal doesn't cry wolf, yet far below a real multi-hour freeze.
    if age is None or age <= 600:
        return ""
    if age >= 3600:
        h, m = int(age // 3600), int((age % 3600) // 60)
        age_txt = f"{h}h {m}m" if m else f"{h}h"
    else:
        age_txt = f"{int(age // 60)}m"
    return f" {DIM}·stale {age_txt}{RST}"


def build_rate_limits_line(ctx):
    if ctx.get("gateway", {}).get("foreign"):
        label = _gateway.gateway_note_label(ctx.get("gateway"))
        return render_dashboard_line([f"{DIM}rate limits n/a on gateway (via {label}){RST}"], ctx.get("render_width", 0))

    usage_data = ctx.get("usage_data")
    if not usage_data:
        return ""

    bw = 10

    fh = usage_data.get("five_hour", {})
    fh_pct = int(fh.get("utilization", 0))
    fh_reset = fh.get("resets_at", "")
    fh_bar = build_usage_bar(fh_pct, bw)
    fh_color = color_for_pct(fh_pct)

    sd = usage_data.get("seven_day") or {}
    sd_pct = int(sd.get("utilization", 0))
    sd_reset = sd.get("resets_at", "")
    # Weekly window: longer than a day -> earlier warning thresholds.
    sd_bar = build_usage_bar(sd_pct, bw, long_window=True)
    sd_color = color_for_pct(sd_pct, long_window=True)

    sds = usage_data.get("seven_day_sonnet") or {}
    sds_pct = int(sds.get("utilization", 0))

    fh_time = _format_reset(fh_reset, "time")
    sd_time = _format_reset(sd_reset, "datetime")

    # Use remote labels if available
    schedule = ctx.get("schedule", {})
    labels = schedule.get("labels", {})
    fh_label = labels.get("five_hour", "5h")
    wk_label = labels.get("weekly", "weekly")

    current = f"{WHITE}{fh_label}{RST} {fh_bar} {fh_color}{fh_pct:3d}%{RST} {DIM}\u27f3{RST} {WHITE}{fh_time}{RST}"
    weekly = f"{WHITE}{wk_label}{RST} {sd_bar} {sd_color}{sd_pct:3d}%{RST} {DIM}\u27f3{RST} {WHITE}{sd_time}{RST}"

    offloop = _check_offloop_drain(ctx, usage_data)
    stale = _usage_stale_marker(ctx)
    line = render_dashboard_line([current, weekly], ctx.get("render_width", 0), trailing=offloop + stale)

    # The sonnet weekly window resets on the same clock as the weekly window, so
    # drop the redundant \u27f3 stamp and give it its own continuation row below
    # instead of pushing it off to the right of the 5h/weekly row.
    if sds_pct > 0:
        # Sonnet sub-window resets on the same weekly clock -> also long.
        sds_bar = build_usage_bar(sds_pct, bw, long_window=True)
        sds_color = color_for_pct(sds_pct, long_window=True)
        sonnet = f"{DIM}sonnet{RST} {sds_bar} {sds_color}{sds_pct:3d}%{RST}"
        line += f"\n{DIM}\u2502{RST}   {sonnet} {DIM}\u2502{RST}"
    return line


# Display labels for a degraded (no-data) provider row. Mirrors the live
# labels: Antigravity renders as "AGY" when it has data, so its degraded row
# matches. Kept in sync with lib/usage_providers.py PROVIDERS.
_PROVIDER_DEGRADED_LABELS = {
    "codex": "Codex",
    "glm": "GLM",
    "droid": "Droid",
    "antigravity": "AGY",
    "copilot": "Copilot",
}


def _provider_degraded_label(provider):
    return _PROVIDER_DEGRADED_LABELS.get(provider, (str(provider or "").title() or "provider"))


def _render_degraded_provider_row(provider, label_width, render_width):
    """A dim/yellow single-line row for a SELECTED provider that returned no
    usable data — so it visibly needs attention instead of silently vanishing.
    Reuses render_dashboard_line so it shares the cockpit border/marker."""
    label = _provider_degraded_label(provider)
    padded = label + (" " * max(0, int(label_width) - len(label)))
    body = f"{YELLOW}{DIM}{padded}  no data — /statusline-onboarding{RST}"
    return render_dashboard_line([body], render_width)


def _render_external_provider_parts(row):
    if row and row.get("display") == "compact":
        label_part = next((part for part in row.get("parts") or [] if part.get("kind") == "label"), {})
        plan = f"{DIM} {label_part.get('plan')}{RST}" if label_part.get("plan") else ""
        label = f"{WHITE}{label_part.get('label', '')}{RST}{plan}"
        metrics = []
        for part in row.get("parts") or []:
            if part.get("kind") != "metric":
                continue
            try:
                pct = max(0, min(100, int(round(float(part.get("pct") or 0)))))
            except (TypeError, ValueError):
                pct = 0
            long_window = _is_long_window_label(part.get("label"))
            metrics.append(f"{WHITE}{part.get('label')}{RST} {color_for_pct(pct, long_window)}{pct}%{RST}")
        if not metrics:
            return ""
        sep = f" {DIM}\u00b7{RST} "
        reset = f" {DIM}{row.get('reset_text')}{RST}" if row.get("reset_text") else ""
        stale = f"{DIM}{row.get('stale_text')}{RST}" if row.get("stale_text") else ""
        return f"{label}  {sep.join(metrics)}{reset}{stale}"

    chunks = []
    for part in row.get("parts") or []:
        kind = part.get("kind")
        if kind == "label":
            plan = f"{DIM} {part.get('plan')}{RST}" if part.get("plan") else ""
            chunks.append(f"{WHITE}{part.get('label', '')}{RST}{plan}")
        elif kind == "window":
            pct = int(part.get("pct") or 0)
            long_window = _is_long_window_label(part.get("label"))
            reset = f" {DIM}{part.get('reset_text')}{RST}" if part.get("reset_text") else ""
            chunks.append(f"{WHITE}{part.get('label')}{RST} {build_usage_bar(pct, long_window=long_window)} {color_for_pct(pct, long_window)}{pct:3d}%{RST}{reset}")
        elif kind == "tokens":
            chunks.append(f"{DIM}tokens{RST} {WHITE}{_fmt_tokens(int(part.get('total') or 0))}{RST}")
    stale = f"{DIM}{row.get('stale_text')}{RST}" if row.get("stale_text") else ""
    return f"{'  '.join(chunks)}{stale}"


def _effective_external_usage_config(config, is_multi_cli=False):
    if not is_multi_cli:
        return config or {}

    source = config.get("external_providers") if isinstance(config, dict) else None
    if not isinstance(source, dict):
        source = {}

    external = dict(source)
    external["enabled"] = True

    defaults = DEFAULT_CONFIG.get("external_providers", {})
    # Codex + GLM are forced on by default in multi-cli.
    for provider in ("codex", "glm"):
        raw = source.get(provider)
        provider_config = raw if isinstance(raw, dict) else {}
        merged = dict(defaults.get(provider, {}))
        merged.update(provider_config)
        merged["enabled"] = not (raw is False or provider_config.get("enabled") is False)
        external[provider] = merged

    # Droid only ever showed a cumulative token count (confusing), so it is
    # opt-in like Antigravity now: it appears only when explicitly enabled.
    # Copilot is opt-in too (its data comes from a background billing-API refresh).
    for provider in ("droid", "antigravity", "copilot"):
        raw = source.get(provider)
        provider_config = raw if isinstance(raw, dict) else {}
        merged = dict(defaults.get(provider, {}))
        merged.update(provider_config)
        merged["enabled"] = raw is True or provider_config.get("enabled") is True
        external[provider] = merged

    effective = dict(config or {})
    effective["external_providers"] = external
    return effective


def _selected_external_providers(config):
    """Ordered list of external providers to render.

    Resolution order:
      1. When a ``providers.selected`` block exists it is the single source of
         truth — return it minus ``claude`` (that is the Claude rate-limit line,
         not an external row), keeping only known external providers in the
         user's chosen order. The legacy ``multi-cli`` force-on of codex+glm is
         intentionally NOT applied here: selection is authoritative.
      2. Otherwise fall back to the legacy behavior — the enabled externals from
         the ``external_providers`` block, in canonical order.
    """
    providers = config.get("providers") if isinstance(config, dict) else None
    if isinstance(providers, dict) and isinstance(providers.get("selected"), list):
        return [
            p for p in providers["selected"] if p != "claude" and p in _EXTERNAL_PROVIDER_ORDER
        ]
    external = config.get("external_providers") if isinstance(config, dict) else None
    external = external if isinstance(external, dict) else {}
    return [
        p
        for p in _EXTERNAL_PROVIDER_ORDER
        if isinstance(external.get(p), dict) and external.get(p).get("enabled") is True
    ]


def build_external_usage_lines(ctx):
    raw_config = ctx.get("config") or {}
    is_multi_cli = bool(ctx.get("is_multi_cli"))
    is_full = bool(ctx.get("is_full"))

    providers_block = raw_config.get("providers") if isinstance(raw_config, dict) else None
    has_selection = isinstance(providers_block, dict) and isinstance(providers_block.get("selected"), list)

    if has_selection:
        # Selection is authoritative. Gating (whether external rows appear at
        # all) is unchanged: multi-cli always, full only when external enabled.
        config = raw_config
        external = config.get("external_providers")
        if not (
            is_multi_cli
            or (is_full and isinstance(external, dict) and external.get("enabled") is True)
        ):
            return ""
        only = _selected_external_providers(config)
        if not only:
            return ""
        try:
            records = _usage_providers.collect_external_usage(config, only=only)
        except Exception:
            return ""
    else:
        # Legacy path — bit-for-bit unchanged (no providers block present).
        config = _effective_external_usage_config(raw_config, is_multi_cli)
        external = config.get("external_providers")
        if not (
            is_multi_cli
            or (is_full and isinstance(external, dict) and external.get("enabled") is True)
        ):
            return ""
        try:
            records = _usage_providers.collect_external_usage(config)
        except Exception:
            return ""

    now_sec = time.time()

    # External records carry resets_at as epoch seconds; convert to the engine's
    # _format_reset so the row shows an absolute end-time (⟳ 12:00pm /
    # ⟳ 4/7 5:00am) exactly like the Claude rate-limit line above.
    def _format_clock(epoch_sec, style):
        try:
            iso = datetime.fromtimestamp(float(epoch_sec), tz=timezone.utc).isoformat()
        except (TypeError, ValueError, OSError, OverflowError):
            return ""
        return _format_reset(iso, style)

    candidates = []
    for record in records:
        try:
            row = _usage_providers.format_provider_row_parts(record, now_sec)
            if row:
                candidates.append((record, row.get("label") or ""))
        except Exception:
            pass

    def _render_available(record, label_width):
        out = []
        row = _usage_providers.format_provider_row_parts(
            record, now_sec, label_width=label_width, format_duration=fmt_duration, format_clock=_format_clock
        )
        if not row:
            return out
        sub_rows = row.get("sub_rows") if isinstance(row.get("sub_rows"), list) and row.get("sub_rows") else [row]
        for sub in sub_rows:
            out.append(render_dashboard_line([_render_external_provider_parts(sub)], ctx.get("render_width", 0)))
        return out

    if has_selection:
        # Selection path: render every selected provider IN ORDER. A selected
        # provider whose reader returns no usable row becomes a dim degraded
        # row ("no data — /statusline-onboarding") instead of vanishing —
        # unless providers.show_unavailable is explicitly False (default ON).
        # NOTE (parity TODO): the node/bash engines don't draw degraded rows yet
        # — this is python-first, like the narrator.
        record_by_provider = {}
        for record in records:
            if isinstance(record, dict):
                record_by_provider.setdefault(record.get("provider"), record)
        available_providers = {rec.get("provider") for rec, _ in candidates}
        show_unavailable = not (
            isinstance(providers_block, dict) and providers_block.get("show_unavailable") is False
        )
        degraded = [p for p in only if p not in available_providers]
        label_width = max(
            [len(label) for _, label in candidates]
            + [len(_provider_degraded_label(p)) for p in degraded],
            default=0,
        )
        lines = []
        for provider in only:
            record = record_by_provider.get(provider)
            rendered = []
            if record is not None:
                try:
                    rendered = _render_available(record, label_width)
                except Exception:
                    rendered = []
            if rendered:
                lines.extend(rendered)
            elif show_unavailable:
                lines.append(
                    _render_degraded_provider_row(provider, label_width, ctx.get("render_width", 0))
                )
        return "\n".join(lines)

    # Legacy path — byte-for-byte unchanged (no providers block present).
    label_width = max((len(label) for _, label in candidates), default=0)
    lines = []
    for record, _ in candidates:
        try:
            row = _usage_providers.format_provider_row_parts(
                record, now_sec, label_width=label_width, format_duration=fmt_duration, format_clock=_format_clock
            )
            if not row:
                continue
            sub_rows = row.get("sub_rows") if isinstance(row.get("sub_rows"), list) and row.get("sub_rows") else [row]
            for sub in sub_rows:
                lines.append(render_dashboard_line([_render_external_provider_parts(sub)], ctx.get("render_width", 0)))
        except Exception:
            pass
    return "\n".join(lines)


# Off-loop drain state must survive across renders (each render is a fresh
# process), so it lives in a tiny JSON file shared with the node engine.
# Keep the filename and the field names ("utilization", "session_cost", "t")
# exactly in sync with engines/node-engine.js.
OFFLOOP_STATE_FILE = "statusline-offloop-state.json"


def _offloop_state_path():
    return Path.home() / ".claude" / OFFLOOP_STATE_FILE


def _read_offloop_state(state_path):
    """Read the previous reading; missing/corrupt file means no prior."""
    try:
        prev = json.loads(state_path.read_text(encoding="utf-8"))
        if isinstance(prev, dict):
            return prev
    except Exception:
        pass
    return None


def _write_offloop_state(state_path, fh_pct, session_cost, now):
    """Atomic write (tmp + os.replace), same pattern as _write_vscode_context."""
    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"utilization": fh_pct, "session_cost": session_cost, "t": now}
        tmp_path = state_path.with_name(f"{state_path.name}.{os.getpid()}.tmp")
        tmp_path.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(str(tmp_path), str(state_path))
    except Exception:
        pass


def _check_offloop_drain(ctx, usage_data):
    """Warn if account quota is rising faster than this session's spend."""
    fh_pct = _as_float((usage_data.get("five_hour") or {}).get("utilization", 0))
    session_cost = _as_float(
        (ctx.get("stdin") or {}).get("cost", {}).get("total_cost_usd", 0.0)
    )
    now = time.time()
    state_path = _offloop_state_path()

    prev = _read_offloop_state(state_path)
    prev_fh_pct = _as_float(prev.get("utilization"), None) if prev else None
    prev_time = _as_float(prev.get("t"), now) if prev else now

    if prev_fh_pct is None:
        _write_offloop_state(state_path, fh_pct, session_cost, now)
        return ""

    elapsed_min = (now - prev_time) / 60.0
    if elapsed_min < 2:
        # Keep the prior reading as the anchor: renders happen every few
        # seconds, so rewriting each tick would make a >=2min delta impossible.
        return ""

    # Window elapsed: re-anchor for the next check before evaluating.
    _write_offloop_state(state_path, fh_pct, session_cost, now)

    fh_delta_pct = fh_pct - prev_fh_pct
    if fh_delta_pct <= 0:
        return ""

    session_rate = _rs_rate(10)
    if session_rate is None:
        return ""

    expected_pct_per_hr = session_rate / 0.80
    actual_pct_per_hr = fh_delta_pct / elapsed_min * 60
    if actual_pct_per_hr > expected_pct_per_hr * 2.5 and fh_delta_pct > 3:
        return f" {YELLOW}\u26a0 off-loop drain{RST}"
    return ""


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
    """Line 4 (session-quality line): spending + cache metrics + efficiency
    dots + tool-call count. Delegates to seg_burn_rate + seg_cache_hit so the
    rolling-window logic is the single source of truth. seg_eff runs after
    seg_cache_hit so it can read the cache-reuse ratio the latter stashes on
    ctx["cache_hit_pct"] instead of recomputing it."""
    parts = []

    burn = seg_burn_rate(ctx)
    if burn:
        parts.append(burn)

    cache = seg_cache_hit(ctx)
    if cache:
        parts.append(cache)

    eff = seg_eff(ctx)
    if eff:
        parts.append(eff)

    tools = seg_tool_count(ctx)
    if tools:
        parts.append(tools)

    wf = seg_workflows(ctx)
    if wf:
        parts.append(wf)

    if not parts:
        return ""

    return render_dashboard_line(parts, ctx.get("render_width", 0))


def seg_tasks(ctx):
    r"""Show task progress from ~/.claude/tasks/<session_id>/<N>.json.

    Counts numeric task files (^\d+\.json$) and reports done/total.
    Self-hides when there is no session_id, no tasks dir, or no task files.
    """
    session_id = ctx.get("stdin", {}).get("session_id", "")
    if not session_id:
        return ""

    tasks_dir = Path.home() / ".claude" / "tasks" / session_id
    if not tasks_dir.is_dir():
        return ""

    total = 0
    done = 0
    try:
        for entry in tasks_dir.iterdir():
            if not _TASK_NAME_RE.match(entry.name):
                continue
            total += 1
            try:
                data = json.loads(entry.read_text(encoding="utf-8"))
                if data.get("status") == "completed":
                    done += 1
            except Exception:
                pass  # unreadable/corrupt task file — ignore
    except Exception:
        return ""

    if total == 0:
        return ""

    if done == total:
        return f"{GREEN}✓ {done}/{total} tasks{RST}"
    return f"{CYAN}◔ {done}/{total} tasks{RST}"


def seg_sessions(ctx):
    text = _session_cockpit.render_session_summary(_session_cockpit.collect_session_counts())
    return f"{CYAN}{text}{RST}" if text else ""


def seg_jobs(ctx):
    text = _job_monitor.render_jobs_summary(_job_monitor.collect_active_jobs())
    return f"{CYAN}{text}{RST}" if text else ""


# ══════════════════════════════════════════════════════════════════════════════
# SEGMENT REGISTRY
# ══════════════════════════════════════════════════════════════════════════════
SEGMENTS = {
    "time": seg_time,
    "banner": seg_banner,
    "peak_hours": seg_peak_hours,
    "promo_2x": seg_peak_hours,  # backward compat
    "model": seg_model,
    "gateway": seg_gateway,
    "context": seg_context,
    "cache_hit": seg_cache_hit,
    "eff": seg_eff,
    "tool_count": seg_tool_count,
    "burn_rate": seg_burn_rate,
    "vim_mode": seg_vim_mode,
    "agent": seg_agent,
    "sessions": seg_sessions,
    "jobs": seg_jobs,
    "workflows": seg_workflows,
    "tasks": seg_tasks,
    "git_branch": seg_git_branch,
    "git_dirty": seg_git_dirty,
    "churn": seg_churn,
    "git_ahead_behind": seg_git_ahead_behind,
    "cost": seg_cost,
    "duration": seg_duration,
    "lines": seg_lines,
    "ts_errors": seg_ts_errors,
    "rate_limits": seg_rate_limits,
    "usage_credits": seg_usage_credits,
    "auth_mode": seg_auth_mode,
    "sdk_meter": seg_sdk_meter,
    "effort": seg_effort,
    "env": seg_env,
}


def _run_segment(name, fn, ctx):
    """Run one segment; no single segment may ever kill the statusline
    (matches the node engine's per-segment guard)."""
    try:
        return fn(ctx)
    except Exception as exc:
        debug(f"segment {name} failed: {exc!r}")
        return ""


def _render_clock(ctx):
    """Subtle end-of-line-1 render-time stamp (HH:MM, local time), multi-cli
    only. Distinct from seg_time (bold white, opt-in via a custom tier's
    segment list) -- this one is dim and wired specifically into multi-cli's
    line 1 tail. See get_local_time() for the timezone resolution it reuses."""
    now = ctx.get("local_time")
    if not now:
        return ""
    return f"{DIM}{now.strftime('%H:%M')}{RST}"


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════
def main():
    config = load_config()
    maybe_heartbeat(config)
    settings = load_claude_settings()
    debug(f"config: tier={config.get('tier')}")
    stdin_data = read_stdin()

    # Scope rolling state to this session to prevent cross-session contamination
    _sid = stdin_data.get("session_id", "")
    if _sid:
        _rs_set_session_id(_sid)

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

    tier = config.get("tier", "standard")
    is_multi_cli = tier == "multi-cli"
    is_full_tier = is_multi_cli or tier == "full" or mode == "full"
    is_standard_tier = tier == "standard"

    ctx = {
        "config": config,
        "stdin": stdin_data,
        "settings": settings,
        "mode": mode,
        "local_time": local_time,
        "local_offset": local_offset,
        "tz_name": tz_name,
        "schedule": schedule,
        "gateway": _gateway.gateway_info(settings=settings, config=config) if is_multi_cli else {"foreign": False},
        "is_peak": False,
        "is_offpeak": True,
        # Responsive render width (COLUMNS-aware); used by line 1 reflow and the
        # bordered dashboard lines so nothing overflows a narrow terminal.
        "render_width": resolve_render_width(config),
    }

    enabled = get_enabled_segments(config, schedule)

    # Inject banner at the start if present. In multi-cli the banner moves to the
    # very last line of output (rendered after the metrics line below); every
    # other tier keeps it on line 1.
    if not is_multi_cli and "banner" not in enabled:
        enabled.insert(0, "banner")
    if os.environ.get("ANTHROPIC_API_KEY") and "auth_mode" not in enabled:
        insert_at = 1 if enabled and enabled[0] == "banner" else 0
        enabled.insert(insert_at, "auth_mode")

    ctx["is_full"] = is_full_tier
    ctx["is_multi_cli"] = is_multi_cli
    # Standard and Full both need rate limits data for their extra lines
    if is_full_tier or is_standard_tier:
        _run_segment("rate_limits", seg_rate_limits, ctx)  # populates ctx["usage_data"]

    # Build line 1
    parts = []
    git_parts = []
    for name in enabled:
        fn = SEGMENTS.get(name)
        if not fn:
            continue
        r = _run_segment(name, fn, ctx)
        if r:
            if name in ("git_branch", "git_dirty", "git_ahead_behind", "churn"):
                git_parts.append(r)
            else:
                parts.append(r)

    if git_parts:
        parts.append(" ".join(git_parts))

    # multi-cli only: a subtle render-time stamp at the tail of line 1. Not the
    # Claude Code version (owner rejected that) -- just HH:MM, dim, so a stale
    # statusline render is visible at a glance. Every other tier stays as-is.
    if is_multi_cli:
        clock = _render_clock(ctx)
        if clock:
            parts.append(clock)

    # Flow design: colored arrows (green=off-peak, yellow=peak)
    arrow_color = YELLOW if ctx.get("is_peak") else GREEN
    arrow = f" {arrow_color}\u25b8{RST} "
    # Responsive width: reflow the segment line across multiple rows to fit the
    # terminal (COLUMNS) instead of one very wide line that the terminal wraps
    # mid-segment. Falls back to a single line when width is unknown/disabled.
    render_width = ctx["render_width"]
    if render_width > 0 and parts:
        line1 = "\n".join(reflow_parts(parts, arrow, render_width))
    else:
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

        # full mode: line 2 — visual 24h timeline. Rendered even on off-peak
        # days so the bar is a consistent anchor; a day with no peak window is
        # a legitimate visual state. Hidden entirely when the schedule mode is
        # "normal" (build_timeline returns '').
        if features.get("show_timeline", True):
            timeline = build_timeline(ctx)
            if timeline:
                print(f"\n\n{timeline}", end="")

        # full mode: line 3 — rate limit bars (5h window + weekly)
        rate_line = build_rate_limits_line(ctx)
        if rate_line:
            print(f"\n{rate_line}", end="")

        external_usage = build_external_usage_lines(ctx)
        if external_usage:
            print(f"\n{external_usage}", end="")

        # full mode: line 4 — burn rate, cache hit ratio, session metrics
        metrics = build_metrics_line(ctx)
        if metrics:
            print(f"\n{metrics}", end="")

    # multi-cli: the promo banner renders as the final line (it was removed from
    # line 1 above), so line 1 stays clean and the banner anchors the bottom.
    if is_multi_cli:
        banner = _run_segment("banner", seg_banner, ctx)
        if banner:
            print(f"\n{banner}", end="")

    try:
        _write_vscode_context(ctx)
    except Exception:
        pass


def _write_vscode_context(ctx):
    """Write statusline data to %TEMP%/claude/statusline-context.json."""
    import tempfile

    context_dir = Path(tempfile.gettempdir()) / "claude"
    context_dir.mkdir(parents=True, exist_ok=True)
    context_path = context_dir / "statusline-context.json"

    usage_data = ctx.get("usage_data", {})
    wf_live = ctx.get("_wf_live", [])
    wf_completed = ctx.get("_wf_completed", {})
    stdin_data = ctx.get("stdin", {})
    cw = stdin_data.get("context_window", {})
    current_usage = cw.get("current_usage", {})
    current = (
        int(current_usage.get("input_tokens", 0))
        + int(current_usage.get("cache_creation_input_tokens", 0))
        + int(current_usage.get("cache_read_input_tokens", 0))
    )
    size = _resolve_ctx_window(ctx)
    pct = int(current * 100 / size) if size > 0 else 0

    payload = {
        "ts": int(time.time()),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "five_hour_pct": int(usage_data.get("five_hour", {}).get("utilization", 0)),
        "seven_day_pct": int(usage_data.get("seven_day", {}).get("utilization", 0)),
        "cost_usd": stdin_data.get("cost", {}).get("total_cost_usd", 0),
        "current_usage": current,
        "context_window_size": size,
        "pct": pct,
        # session_id lets the narrator confirm this session-specific current_usage
        # is ours before trusting it (the file is global, last render wins).
        "session_id": stdin_data.get("session_id", ""),
        # Include display_name AND id so the narrator can detect a window
        # encoded in the id ('claude-opus-4-8[1m]') when the display_name
        # ('Opus 4.8') carries no [1m]/(1M context) marker.
        "model": (
            f"{stdin_data.get('model', {}).get('display_name', '')} "
            f"{stdin_data.get('model', {}).get('id', '')}"
        ).strip(),
        "is_peak": ctx.get("is_peak", False),
        "active_workflow_agents": sum(item["agents"] for item in wf_live),
        "subagent_tokens_live": sum(item["tokens"] for item in wf_live),
        "subagent_runs_session": wf_completed.get("run_count", 0),
    }

    # Unique tmp name per process: concurrent sessions must not collide
    tmp_path = context_path.with_name(f"{context_path.name}.{os.getpid()}.tmp")
    tmp_path.write_text(json.dumps(payload), encoding="utf-8")
    os.replace(str(tmp_path), str(context_path))


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

        # os.urandom(8).hex() == secrets.token_hex(8) (16 lowercase hex chars)
        # without importing anything beyond os.
        uid = os.urandom(8).hex()
        TELEMETRY_ID_PATH.write_text(uid)
        try:
            os.chmod(TELEMETRY_ID_PATH, 0o600)
        except Exception:
            pass
        return uid
    except Exception:
        return ""

def _telemetry_enabled(config):
    """Telemetry is opt-in: requires telemetry: true in config.

    STATUSLINE_DISABLE_TELEMETRY=1 is a hard override and always wins, even
    if the config explicitly opts in.
    """
    if os.getenv("STATUSLINE_DISABLE_TELEMETRY") == "1":
        return False
    return config.get("telemetry") is True

def maybe_heartbeat(config):
    """Send a daily heartbeat. Fire-and-forget, never blocks. Opt-in only."""
    if not _telemetry_enabled(config):
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
            "id": uid, "v": "2.2", "engine": "python",
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
