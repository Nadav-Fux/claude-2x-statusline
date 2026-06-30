"""narrator.observations — build a structured Observation from live session state.

Reads:
- rolling_state samples (via lib.rolling_state)
- stdin JSON (if piped)
- env vars / config files for session metadata

The Observation dataclass is the single source of truth fed to scoring and Haiku.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Optional

try:
    from lib.workflows import (
        detect_live_workflows,
        find_session_dir,
        read_completed_workflows,
    )
except ImportError:
    detect_live_workflows = None
    find_session_dir = None
    read_completed_workflows = None

try:
    from lib import usage_providers
except ImportError:
    usage_providers = None

# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class Observation:
    # Cost / burn
    cost_usd: float = 0.0          # session cumulative cost
    burn_10m: Optional[float] = None   # $/hr rolling 10-min window
    burn_session: Optional[float] = None  # $/hr lifetime session average

    # Context window
    ctx_pct: float = 0.0           # 0–100 % of context used
    ctx_mins_left: Optional[float] = None  # minutes until full (linear proj)

    # Cache
    cache_pct: float = 0.0         # cache_read / total_input_tokens * 100
    cache_delta_5m: Optional[int] = None  # cache_read tokens added in last 5m

    # Peak / schedule
    is_peak: bool = False
    schedule_mode: str = "normal"  # "normal" | "schedule"

    # Session metadata
    session_duration_min: float = 0.0
    prompt_count: int = 0

    # Rate limits (0–100 %)
    rate_limit_5h_pct: float = 0.0
    rate_limit_7d_pct: float = 0.0
    external_usage: list = field(default_factory=list)

    # Rate-limit reset times (parsed datetimes; None when absent/malformed) and a
    # derived "hours until the 7-day weekly window resets". These let the rate-limit
    # insight reason about WHERE we are in the reset cycle, not just the raw %.
    rate_limit_5h_resets_at: Optional[datetime] = None
    rate_limit_7d_resets_at: Optional[datetime] = None
    rate_limit_7d_hours_left: Optional[float] = None  # hours until weekly reset

    # Trend fields (delta vs 5 min ago and 20 min ago from rolling_observations)
    cost_delta_5m: float = 0.0
    cost_delta_20m: float = 0.0
    ctx_delta_5m: float = 0.0    # pct-point change in ctx usage

    # Raw token counts (for haiku context)
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    ctx_window_size: int = 200000  # placeholder; build() resolves the true window (1M-aware)

    # Cost milestones crossed this session (for scoring freshness)
    cost_milestones_hit: list = field(default_factory=list)

    # Workflow fields
    subagent_tokens_live: int = 0
    subagent_runs_session: int = 0
    active_workflow_agents: int = 0

    # Project hygiene: line count of the nearest CLAUDE.md (Boris Cherny:
    # ~60 optimal, 200 ceiling — rules past it get deprioritized).
    claude_md_lines: int = 0


# ---------------------------------------------------------------------------
# Peak-hours helper (delegates to the authoritative python engine logic)
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _load_python_engine_module():
    engine_path = Path(__file__).resolve().parent.parent / "engines" / "python-engine.py"
    spec = importlib.util.spec_from_file_location("statusline_python_engine", engine_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load engine module from {engine_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _is_peak_hours() -> bool:
    """Return the current peak-hours state using the runtime schedule logic."""
    try:
        engine = _load_python_engine_module()
        config = engine.load_config()
        schedule = engine.load_schedule(config)
        local_time, _, local_offset = engine.get_local_time()
        ctx = {
            "schedule": schedule,
            "local_time": local_time,
            "local_offset": local_offset,
        }
        engine.seg_peak_hours(ctx)
        return bool(ctx.get("is_peak", False))
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Stdin parsing
# ---------------------------------------------------------------------------

def _read_stdin_json() -> Optional[dict]:
    """Return parsed JSON from stdin, or None if stdin is a TTY or invalid."""
    if sys.stdin.isatty():
        return None
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return None
        return json.loads(raw)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Config / state file parsing
# ---------------------------------------------------------------------------

def _load_statusline_state() -> dict:
    """Load the rolling state JSON directly (for cost/token data).

    Uses rolling_state._state_path() to respect per-session scoping
    when set_session_id() has been called.
    """
    try:
        from lib import rolling_state as rs
        state_path = rs._state_path()
    except Exception:
        state_path = Path.home() / ".claude" / "statusline-state.json"
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return {"samples": []}


def _load_statusline_context(stdin_data: Optional[dict] = None) -> dict:
    """Load the bar's statusline-context.json (authoritative window + usage + model).

    The narrator runs from hooks whose stdin does NOT include a context_window
    block, so this file is its only source for the true window size and the live
    current_usage. The file is global (one path, last render wins).

    Freshness: when the file's session_id matches ours it is authoritative at ANY
    age — our own session's window/usage do not go stale just because the bar
    hasn't re-rendered during a long turn. That time-based staleness was exactly
    what made the narrator discard correct data and fall back to the
    over-counting rolling-token sum, reporting 100% while the bar showed ~44%.
    The 5-min guard now applies ONLY when the session is different/unknown, to
    avoid scaling our tokens by another (or finished) session's data.
    """
    try:
        import tempfile

        path = Path(tempfile.gettempdir()) / "claude" / "statusline-context.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        our_sid = (stdin_data or {}).get("session_id")
        file_sid = data.get("session_id")
        if our_sid and file_sid and our_sid == file_sid:
            return data  # our session — authoritative regardless of age
        if time.time() - path.stat().st_mtime > 300:
            return {}
        return data
    except Exception:
        return {}


def _window_from_name(name: str) -> Optional[int]:
    """Extract a context-window size encoded in a model name, dynamically:
    '[1m]' -> 1_000_000, '(500k context)' -> 500_000, 'Opus 4.8 (1M context)' -> 1_000_000.
    Only matches a number+unit inside brackets/parens OR adjacent to a context/token/
    window word, so version numbers ('4-8') and param counts ('31b') never false-match.
    Returns token count, or None when the name encodes no window."""
    import re
    if not name:
        return None
    for rx in (
        re.compile(r"[\[(]\s*(\d+(?:\.\d+)?)\s*([mk])\b", re.I),
        re.compile(r"(\d+(?:\.\d+)?)\s*([mk])\s*(?:context|tokens?|ctx|window)", re.I),
    ):
        m = rx.search(name)
        if m:
            n = float(m.group(1))
            return int(n * (1_000_000 if m.group(2).lower() == "m" else 1_000))
    return None


def _resolve_ctx_window_size(stdin_data: Optional[dict]) -> int:
    """Resolve the TRUE context window size for ctx_pct.

    Defaulting to 200k mis-scales the percentage on 1M-context models: ~160k
    tokens reads as 80% of 200k (and fires the pressure templates) when it is
    really 16% of a 1,000,000 window. Resolution order, highest priority first:

    1. ``STATUSLINE_CTX_WINDOW`` env override (explicit token count).
    2. A real size reported on stdin (the bar's path; >0).
    3. The bar's statusline-context.json — its context_window_size, else a 1M
       reading from its model name ("Opus 4.8 (1M context)").
    4. 1M detection from the stdin model block (display_name / id contains 1m).
    5. 200,000 default.
    """
    env = os.environ.get("STATUSLINE_CTX_WINDOW", "").strip()
    if env.isdigit() and int(env) > 0:
        return int(env)

    cfile = _load_statusline_context(stdin_data)

    # 1M-context models FIRST. Claude Code can still report context_window_size=200000
    # on stdin for a [1m] session; trusting that size mis-scales the % ~5x and fires
    # false "context full" pressure at ~16% real usage. Detect the 1M model and override
    # the (wrong) stdin size before we ever trust it.
    model = (stdin_data or {}).get("model", {}) or {}
    name = str(model.get("display_name", "")) + " " + str(model.get("id", ""))
    cfile_model = str((cfile or {}).get("model", ""))
    win = _window_from_name(name) or _window_from_name(cfile_model)
    if win:
        return win

    ctx_block = (stdin_data or {}).get("context_window", {}) or {}
    size = int(ctx_block.get("context_window_size", 0) or 0)
    if size > 0:
        return size

    if cfile:
        csize = int(cfile.get("context_window_size", 0) or 0)
        if csize > 0:
            return csize

    return 200000


def _count_claude_md_lines(stdin_data: Optional[dict]) -> int:
    """Line count of the project CLAUDE.md (cwd/CLAUDE.md), 0 if none.

    Best-practice guidance (Boris Cherny / Anthropic): ~60 lines is optimal,
    200 is the ceiling — rules past it get quietly deprioritized. We surface a
    gentle hint when a project's file is oversized.
    """
    try:
        cwd = (stdin_data or {}).get("cwd") or os.getcwd()
        path = Path(cwd) / "CLAUDE.md"
        if path.is_file():
            with path.open(encoding="utf-8", errors="replace") as fh:
                return sum(1 for _ in fh)
    except Exception:
        pass
    return 0


def _load_usage_cache() -> dict:
    """Load the rate-limits usage cache written by seg_rate_limits()."""
    cache_path = Path.home() / ".claude" / "statusline-usage-cache.json"
    try:
        age = time.time() - cache_path.stat().st_mtime
        if age > 300:
            return {}
        return json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _safe_utilization(block) -> float:
    """Coerce a usage-cache window block's utilization to float.

    The cache can be valid JSON with the wrong shape (e.g. five_hour: null,
    utilization: "abc") — never let that throw; fall back to 0.0.
    """
    if not isinstance(block, dict):
        return 0.0
    try:
        return float(block.get("utilization", 0.0))
    except (TypeError, ValueError):
        return 0.0


def _parse_reset_at(block) -> Optional[datetime]:
    """Parse a usage-cache window block's ``resets_at`` to a tz-aware datetime.

    Mirrors the engine's _format_reset parsing (fromisoformat with the trailing
    'Z' rewritten to '+00:00', since Python 3.9's fromisoformat rejects 'Z').
    Returns None when the block is the wrong shape, the field is missing/null,
    or the timestamp is malformed — never raises.
    """
    if not isinstance(block, dict):
        return None
    iso = block.get("resets_at")
    if not iso or not isinstance(iso, str) or iso == "null":
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    # Normalise to tz-aware UTC so the hours-left math below is unambiguous.
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _latest_sample(state: dict) -> Optional[dict]:
    samples = state.get("samples", [])
    if not samples:
        return None
    return max(samples, key=lambda s: s["t"])


# ---------------------------------------------------------------------------
# Trend computation from memory.rolling_observations
# ---------------------------------------------------------------------------

def _trend_fields(rolling_obs: list, now: float) -> dict:
    """Find recent comparison baselines from rolling_observations."""
    result = {
        "cost_5m_ago": None,
        "cost_20m_ago": None,
        "ctx_5m_ago": None,
    }
    if not rolling_obs:
        return result

    target_5m = now - 5 * 60
    target_20m = now - 20 * 60

    def _closest(target: float) -> Optional[dict]:
        candidates = [o for o in rolling_obs if "ts" in o]
        if not candidates:
            return None
        return min(candidates, key=lambda o: abs(o["ts"] - target))

    obs_5m = _closest(target_5m)
    obs_20m = _closest(target_20m)

    # Only use if within a narrow tolerance; otherwise treat as "no baseline".
    if obs_5m and abs(obs_5m["ts"] - target_5m) < 180:
        result["cost_5m_ago"] = obs_5m.get("cost_usd")
        result["ctx_5m_ago"] = obs_5m.get("ctx_pct")

    if obs_20m and abs(obs_20m["ts"] - target_20m) < 300:
        result["cost_20m_ago"] = obs_20m.get("cost_usd")

    return result


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------

def build(memory: dict) -> Observation:
    """Build an Observation from all available sources.

    Priority order for token/cost data:
    1. Piped stdin JSON (most authoritative — direct from hook)
    2. Latest sample from rolling_state.json
    3. Defaults / zero
    """
    obs = Observation()
    now = time.time()

    # ── stdin ────────────────────────────────────────────────────────────────
    stdin_data = _read_stdin_json()
    if stdin_data:
        _apply_stdin(obs, stdin_data)

    usage_cache = _load_usage_cache()
    if usage_cache:
        five_hour = usage_cache.get("five_hour")
        seven_day = usage_cache.get("seven_day")
        obs.rate_limit_5h_pct = _safe_utilization(five_hour)
        obs.rate_limit_7d_pct = _safe_utilization(seven_day)

        # Reset times → cycle-awareness for the rate-limit insight. Use the same
        # "now" source (time.time()) the rest of build() uses so tests can
        # monkeypatch observations.time.time against a fixed resets_at.
        obs.rate_limit_5h_resets_at = _parse_reset_at(five_hour)
        obs.rate_limit_7d_resets_at = _parse_reset_at(seven_day)
        if obs.rate_limit_7d_resets_at is not None:
            secs_left = obs.rate_limit_7d_resets_at.timestamp() - now
            # Clamp negatives to 0 (a reset that has just passed = 0h left), so
            # the cycle math never produces a nonsense elapsed_frac > 1.
            obs.rate_limit_7d_hours_left = max(0.0, secs_left / 3600.0)

    if usage_providers is not None:
        try:
            engine = _load_python_engine_module()
            config = engine.load_config()
            obs.external_usage = usage_providers.read_cached_external_usage(config)
        except Exception:
            obs.external_usage = []

    # ── rolling_state samples ────────────────────────────────────────────────
    try:
        from lib import rolling_state as rs
        if stdin_data and stdin_data.get("session_id"):
            rs.set_session_id(stdin_data["session_id"])
        obs.burn_10m = rs.rolling_rate(10)
        obs.cache_delta_5m = rs.cache_delta(5)
    except Exception:
        pass

    # If stdin didn't provide token data, fall back to latest rolling sample
    if obs.total_input_tokens == 0:
        state = _load_statusline_state()
        sample = _latest_sample(state)
        if sample:
            _apply_sample(obs, sample)

    # ── session duration from memory ─────────────────────────────────────────
    current = memory.get("current", {})
    started_at = current.get("started_at")
    if started_at:
        try:
            obs.session_duration_min = (now - float(started_at)) / 60.0
        except (TypeError, ValueError):
            pass

    obs.prompt_count = current.get("prompt_count", 0)
    obs.cost_milestones_hit = current.get("cost_milestones_hit", [])

    # ── session burn rate ────────────────────────────────────────────────────
    # Require at least 1 minute of session before computing, otherwise tiny
    # durations produce absurd rates (e.g. $20 / 60ms ≈ $1.2M/hr).
    # Sanity cap at $200/hr — anything above is a spike, drop it (caller can
    # fall back to rolling_rate or show nothing).
    if obs.session_duration_min >= 1.0 and obs.cost_usd > 0:
        candidate = obs.cost_usd / (obs.session_duration_min / 60.0)
        obs.burn_session = candidate if candidate <= 200.0 else None

    # ── true context window size (1M-aware; not the bare 200k default) ───────
    obs.ctx_window_size = _resolve_ctx_window_size(stdin_data)

    # ── project CLAUDE.md size (best-practice hygiene hint) ──────────────────
    obs.claude_md_lines = _count_claude_md_lines(stdin_data)

    # ── context % and minutes left ───────────────────────────────────────────
    # Prefer the bar's authoritative current_usage from statusline-context.json
    # (the live window occupancy Claude Code reports at render time and the bar
    # displays). The narrator's own rolling-sample token sums (input + cache_read
    # + cache_creation) do NOT equal live occupancy — they over-count and, in
    # long/active sessions, wrongly clamp ctx_pct to 100% while the bar shows ~25%
    # (which also makes the ctx_pct>60 insight gates misfire). _load_statusline_context()
    # already applies a 5-min freshness guard; on a stale/absent file we fall
    # back to the rolling estimate.
    _bar_ctx = _load_statusline_context(stdin_data)
    _bar_usage = _bar_ctx.get("current_usage")
    # The context file is global (last render wins). current_usage is
    # session-specific, so when the file records a session_id only trust it if it
    # matches ours — otherwise a concurrent session's usage leaks in. Files from
    # older bars carry no session_id; stay lenient for them. A legit 0 (fresh
    # empty window) IS authoritative — don't fall back to the rolling sum for it.
    _bar_sid = _bar_ctx.get("session_id")
    _our_sid = (stdin_data or {}).get("session_id")
    # Lenient when either side lacks a session_id (older bars write "" / None):
    # only a definite mismatch between two known ids blocks trust.
    _usage_trusted = not _bar_sid or not _our_sid or _bar_sid == _our_sid
    if (obs.ctx_window_size > 0 and _usage_trusted
            and isinstance(_bar_usage, (int, float)) and not isinstance(_bar_usage, bool)
            and _bar_usage >= 0):
        obs.ctx_pct = min(100.0, float(_bar_usage) / obs.ctx_window_size * 100.0)
    elif obs.ctx_window_size > 0 and obs.total_input_tokens > 0:
        used = obs.total_input_tokens + obs.cache_creation_tokens + obs.cache_read_tokens
        obs.ctx_pct = min(100.0, used / obs.ctx_window_size * 100.0)

    if obs.ctx_pct > 0 and obs.session_duration_min > 1:
        rate_pct_per_min = obs.ctx_pct / obs.session_duration_min
        if rate_pct_per_min > 0:
            obs.ctx_mins_left = (100.0 - obs.ctx_pct) / rate_pct_per_min

    # ── cache % ──────────────────────────────────────────────────────────────
    total_in = obs.total_input_tokens
    if total_in > 0 and obs.cache_read_tokens > 0:
        obs.cache_pct = obs.cache_read_tokens / total_in * 100.0

    if find_session_dir is not None:
        try:
            session_dir = find_session_dir(stdin_data or {})
            if session_dir:
                live_wfs = detect_live_workflows(session_dir)
                obs.active_workflow_agents = sum(item["agents"] for item in live_wfs)
                obs.subagent_tokens_live = sum(item["tokens"] for item in live_wfs)
                if not live_wfs:
                    completed = read_completed_workflows(session_dir)
                    obs.subagent_runs_session = completed["run_count"]
        except Exception:
            pass

    # ── peak hours ──────────────────────────────────────────────────────────
    if not stdin_data or "is_peak" not in stdin_data:
        obs.is_peak = _is_peak_hours()

    # ── trend fields ─────────────────────────────────────────────────────────
    rolling_obs = current.get("rolling_observations", [])
    trends = _trend_fields(rolling_obs, now)
    if trends["cost_5m_ago"] is not None:
        obs.cost_delta_5m = obs.cost_usd - trends["cost_5m_ago"]
    if trends["cost_20m_ago"] is not None:
        obs.cost_delta_20m = obs.cost_usd - trends["cost_20m_ago"]
    if trends["ctx_5m_ago"] is not None:
        obs.ctx_delta_5m = obs.ctx_pct - trends["ctx_5m_ago"]

    return obs


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _apply_stdin(obs: Observation, data: dict) -> None:
    """Populate obs fields from a stdin JSON payload (hook format)."""
    cost_block = data.get("cost", {})
    obs.cost_usd = float(cost_block.get("total_cost_usd", 0.0))

    duration_ms = float(cost_block.get("total_duration_ms", 0))
    if duration_ms > 0:
        obs.session_duration_min = duration_ms / 60000.0

    ctx_block = data.get("context_window", {})
    # Raw stdin value only (0 if absent). build() finalizes the true window via
    # _resolve_ctx_window_size — do NOT bake the 200k default in here.
    obs.ctx_window_size = int(ctx_block.get("context_window_size", 0) or 0)
    usage = ctx_block.get("current_usage", {})
    obs.total_input_tokens = int(usage.get("input_tokens", 0))
    obs.total_output_tokens = int(usage.get("output_tokens", 0))
    obs.cache_read_tokens = int(usage.get("cache_read_input_tokens", 0))
    obs.cache_creation_tokens = int(usage.get("cache_creation_input_tokens", 0))

    obs.is_peak = bool(data.get("is_peak", False))
    schedule = data.get("schedule", {})
    obs.schedule_mode = schedule.get("mode", "normal")

    # Claude Code hook payloads do not expose pct_5h/pct_7d. The narrator
    # populates these from statusline-usage-cache.json in build().
    obs.rate_limit_5h_pct = 0.0
    obs.rate_limit_7d_pct = 0.0


def _apply_sample(obs: Observation, sample: dict) -> None:
    """Populate obs fields from a rolling_state sample dict."""
    obs.cost_usd = float(sample.get("cost", 0.0))
    obs.total_input_tokens = int(sample.get("tokens_in", 0))
    obs.total_output_tokens = int(sample.get("tokens_out", 0))
    obs.cache_read_tokens = int(sample.get("cache_read", 0))
    obs.cache_creation_tokens = int(sample.get("cache_creation", 0))
