#!/usr/bin/env python3
"""Claude Code statusline — modular Python engine.

Reads JSON from stdin (provided by Claude Code) + config file,
runs enabled segments, outputs ANSI-colored status line.
"""
import sys
import json
import os
import subprocess
import hashlib
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

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

# ══════════════════════════════════════════════════════════════════════════════
# TIER PRESETS
# ══════════════════════════════════════════════════════════════════════════════
TIER_PRESETS = {
    "minimal": ["promo_2x", "git_branch", "git_dirty"],
    "standard": ["promo_2x", "model", "context", "git_branch", "git_dirty", "cost"],
    "full": ["promo_2x", "model", "context", "git_branch", "git_dirty", "cost"],
}

DEFAULT_CONFIG = {
    "tier": "standard",
    "segments": {},
    "timezone": "auto",
    "promo_start": 20260313,
    "promo_end": 20260327,
    "separator": " │ ",
    "mode": "minimal",
    "full_mode_rate_limits": True,
    "full_mode_timeline": True,
}

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


def get_enabled_segments(config):
    tier = config.get("tier", "standard")
    if tier == "custom":
        return [k for k, v in config.get("segments", {}).items() if v]
    return TIER_PRESETS.get(tier, TIER_PRESETS["standard"])


# ══════════════════════════════════════════════════════════════════════════════
# STDIN JSON
# ══════════════════════════════════════════════════════════════════════════════
def read_stdin():
    try:
        if not sys.stdin.isatty():
            data = sys.stdin.read().strip()
            if data:
                return json.loads(data)
    except Exception:
        pass
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


def get_israel_time():
    utc = datetime.now(timezone.utc)
    m, d = utc.month, utc.day
    # Israel DST: ~March 27 → ~October 25
    if (m > 3 or (m == 3 and d >= 27)) and (m < 10 or (m == 10 and d < 25)):
        offset = 3  # IDT
    else:
        offset = 2  # IST
    il = utc + timedelta(hours=offset)
    return il, offset


# ══════════════════════════════════════════════════════════════════════════════
# SEGMENTS
# ══════════════════════════════════════════════════════════════════════════════

def seg_time(ctx):
    il = ctx["il_time"]
    return f"{WHITE}{BOLD}{il.strftime('%H:%M')}{RST}"


def seg_promo_2x(ctx):
    config = ctx["config"]
    il, offset = ctx["il_time"], ctx["il_offset"]
    il_date = int(il.strftime("%Y%m%d"))

    promo_start = config.get("promo_start", 20260313)
    promo_end = config.get("promo_end", 20260327)

    if not (promo_start <= il_date <= promo_end):
        return f"{DIM}Promo ended{RST}"

    hour, minute = il.hour, il.minute
    weekday = il.isoweekday()  # 1=Mon, 7=Sun
    now_mins = hour * 60 + minute

    peak_start = 12 + offset
    peak_end = 18 + offset

    doubled, reason, mins_left, mins_until = False, "", 0, 0

    # Weekend: Sat 09:00 → Mon 09:00
    if weekday == 6 and now_mins >= 540:
        doubled, reason, mins_left = True, "weekend", (1440 - now_mins) + 1440 + 540
    elif weekday == 7:
        doubled, reason, mins_left = True, "weekend", (1440 - now_mins) + 540
    elif weekday == 1 and now_mins < 540:
        doubled, reason, mins_left = True, "weekend", 540 - now_mins
    elif now_mins >= peak_end * 60:
        doubled, reason, mins_left = True, "off-peak", (1440 - now_mins) + peak_start * 60
    elif now_mins < peak_start * 60:
        doubled, reason, mins_left = True, "off-peak", peak_start * 60 - now_mins

    if not doubled:
        mins_until = peak_end * 60 - now_mins

    # Store for full mode
    ctx["is_2x"] = doubled
    ctx["is_promo"] = True
    ctx["peak_start_local"] = peak_start
    ctx["peak_end_local"] = peak_end

    if doubled:
        t = fmt_duration(mins_left)
        if mins_left > 180:
            bg = BG_GREEN
        elif mins_left > 60:
            bg = BG_YELLOW
        else:
            bg = BG_RED
        wknd = f" {DIM}weekend{RST}" if reason == "weekend" else ""
        return f"{bg} 2x ACTIVE {RST} {WHITE}{t} left{RST}{wknd}"
    else:
        t = fmt_duration(mins_until)
        return f"{BG_GRAY} PEAK {RST} {DIM}\u2192 2x in {t}{RST}"


def seg_model(ctx):
    name = ctx["stdin"].get("model", {}).get("display_name", "")
    if not name:
        return ""
    # Shorten: "Opus 4.6 (1M context)" -> "Opus 4.6"
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
    return f"{color}{_fmt_tokens(current)}/{_fmt_tokens(size)}{RST} {color}{pct}%{RST}"


def seg_git_branch(ctx):
    branch = git_cmd("branch", "--show-current")
    if not branch:
        return ""
    ctx["git_branch"] = branch
    return f"{DIM}{branch}{RST}"


def seg_git_dirty(ctx):
    porcelain = git_cmd("status", "--porcelain")
    if not porcelain:
        return ""
    count = len(porcelain.splitlines())
    return f"{YELLOW}~{count}{RST}"


def seg_git_ahead_behind(ctx):
    branch = ctx.get("git_branch", "")
    if not branch:
        return ""
    ahead = git_cmd("rev-list", "--count", f"@{{u}}..HEAD")
    behind = git_cmd("rev-list", "--count", f"HEAD..@{{u}}")
    parts = []
    if ahead and ahead != "0":
        parts.append(f"↑{ahead}")
    if behind and behind != "0":
        parts.append(f"↓{behind}")
    if not parts:
        return ""
    return f"{DIM}{''.join(parts)}{RST}"


def seg_cost(ctx):
    cost = ctx["stdin"].get("cost", {}).get("total_cost_usd")
    if cost is None:
        return ""
    return f"{MAGENTA}${cost:.1f}{RST}"


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
    h = hashlib.md5(cwd.encode()).hexdigest()
    cache = Path(f"/tmp/tsc-errors-{h}.txt")
    if not cache.exists():
        return ""
    try:
        age = time.time() - cache.stat().st_mtime
        if age > 300:  # 5 min TTL
            return ""
        count = int(cache.read_text().strip().split()[0])
        if count > 0:
            return f"{RED}TS:{count}{RST}"
    except Exception:
        pass
    return ""


def seg_rate_limits(ctx):
    """Fetch rate limits from Claude OAuth API (cached 60s)."""
    cache_dir = Path("/tmp/claude")
    cache_dir.mkdir(parents=True, exist_ok=True)
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
    frozen = " ❄" if ctx.get("is_2x") else ""

    return f"{build_usage_bar(fh_pct)} {color_for_pct(fh_pct)}{fh_pct}%{RST}{frozen}"


def _get_oauth_token():
    """Try to find Claude OAuth token."""
    # 1. Environment variable
    token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "")
    if token:
        return token

    # 2. Credentials file
    creds = Path.home() / ".claude" / ".credentials.json"
    if creds.exists():
        try:
            data = json.loads(creds.read_text())
            token = data.get("claudeAiOauth", {}).get("accessToken", "")
            if token:
                return token
        except Exception:
            pass

    # 3. macOS keychain
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
    if not ctx.get("is_promo"):
        return ""

    il = ctx["il_time"]
    hour, minute = il.hour, il.minute
    offset = ctx["il_offset"]
    weekday = il.isoweekday()
    is_weekend = weekday >= 6

    peak_start = ctx.get("peak_start_local", 14)
    peak_end = ctx.get("peak_end_local", 20)

    cursor_pos = hour * 2 + (1 if minute >= 30 else 0)

    bar = ""
    for i in range(48):
        h = i // 2
        if i == cursor_pos:
            bar += f"{WHITE}{BOLD}●{RST}"
        elif is_weekend or h < peak_start or h >= peak_end:
            bar += f"{GREEN}━{RST}"
        else:
            bar += f"{YELLOW}━{RST}"

    if is_weekend:
        return f"{DIM}\u2502{RST} {bar} {DIM}\u2502{RST}  {GREEN}\u2501{RST}{DIM} 2x all day{RST}"

    return f"{DIM}\u2502{RST} {bar} {DIM}\u2502{RST}  {GREEN}\u2501{RST}{DIM} 2x{RST} {YELLOW}\u2501{RST}{DIM} peak{RST}"


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

    frozen = f" {CYAN}❄{RST}" if ctx.get("is_2x") else ""

    # Format reset times
    fh_time = _format_reset(fh_reset, "time")
    sd_time = _format_reset(sd_reset, "date")

    arrow = f" {GREEN}\u25b8{RST} "
    current = f"{DIM}\u2502{RST} {GREEN}\u25b8{RST} {WHITE}5h{RST} {fh_bar} {fh_color}{fh_pct:3d}%{RST} {DIM}\u27f3{RST} {WHITE}{fh_time}{RST}"
    weekly = f"{WHITE}weekly{RST} {sd_bar} {sd_color}{sd_pct:3d}%{RST}{frozen} {DIM}\u27f3{RST} {WHITE}{sd_time}{RST}"

    return f"{current} {DIM}\u00b7{RST} {weekly} {DIM}\u2502{RST}"


def _format_reset(iso_str, style="time"):
    if not iso_str or iso_str == "null":
        return ""
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        local = dt.astimezone()
        if style == "time":
            return local.strftime("%-I:%M%p").lower()
        else:
            return local.strftime("%b %-d").lower()
    except Exception:
        return ""


# ══════════════════════════════════════════════════════════════════════════════
# SEGMENT REGISTRY
# ══════════════════════════════════════════════════════════════════════════════
SEGMENTS = {
    "time": seg_time,
    "promo_2x": seg_promo_2x,
    "model": seg_model,
    "context": seg_context,
    "git_branch": seg_git_branch,
    "git_dirty": seg_git_dirty,
    "git_ahead_behind": seg_git_ahead_behind,
    "cost": seg_cost,
    "duration": seg_duration,
    "lines": seg_lines,
    "ts_errors": seg_ts_errors,
    "rate_limits": seg_rate_limits,
}


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════
def main():
    config = load_config()
    stdin_data = read_stdin()

    # Mode from args or config
    mode = config.get("mode", "minimal")
    for arg in sys.argv[1:]:
        if arg == "--full":
            mode = "full"
        elif arg == "--minimal":
            mode = "minimal"
        elif arg.startswith("--tier="):
            config["tier"] = arg.split("=", 1)[1]

    il, offset = get_israel_time()
    ctx = {
        "config": config,
        "stdin": stdin_data,
        "mode": mode,
        "il_time": il,
        "il_offset": offset,
        "is_2x": False,
        "is_promo": False,
    }

    enabled = get_enabled_segments(config)

    # In full mode, fetch rate limits data (for line 3) but don't show in line 1
    if mode == "full":
        seg_rate_limits(ctx)  # populates ctx["usage_data"]

    # Flow design: colored arrows as separators
    is_2x = ctx.get("is_2x", False)
    arrow_color = GREEN if is_2x else YELLOW
    arrow = f" {arrow_color}\u25b8{RST} "

    # Build line 1 — merge git_branch + git_dirty into one segment
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

    line1 = arrow.join(parts)
    print(line1, end="")

    # Full mode: additional lines
    if mode == "full":
        timeline = build_timeline(ctx)
        rate_line = build_rate_limits_line(ctx)
        if timeline:
            print(f"\n\n{timeline}", end="")
        if rate_line:
            print(f"\n{rate_line}", end="")


if __name__ == "__main__":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    main()
