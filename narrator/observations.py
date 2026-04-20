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
from functools import lru_cache
from pathlib import Path
from typing import Optional

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

    # Trend fields (delta vs 5 min ago and 20 min ago from rolling_observations)
    cost_delta_5m: float = 0.0
    cost_delta_20m: float = 0.0
    ctx_delta_5m: float = 0.0    # pct-point change in ctx usage

    # Raw token counts (for haiku context)
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    ctx_window_size: int = 200000

    # Cost milestones crossed this session (for scoring freshness)
    cost_milestones_hit: list = field(default_factory=list)


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
    """Load the rolling state JSON directly (for cost/token data)."""
    state_path = Path.home() / ".claude" / "statusline-state.json"
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return {"samples": []}


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

    # ── rolling_state samples ────────────────────────────────────────────────
    try:
        from lib import rolling_state as rs
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

    # ── context % and minutes left ───────────────────────────────────────────
    if obs.ctx_window_size > 0 and obs.total_input_tokens > 0:
        used = obs.total_input_tokens + obs.total_output_tokens
        obs.ctx_pct = min(100.0, used / obs.ctx_window_size * 100.0)

        if obs.session_duration_min > 1 and obs.ctx_pct > 0:
            rate_pct_per_min = obs.ctx_pct / obs.session_duration_min
            if rate_pct_per_min > 0:
                obs.ctx_mins_left = (100.0 - obs.ctx_pct) / rate_pct_per_min

    # ── cache % ──────────────────────────────────────────────────────────────
    total_in = obs.total_input_tokens
    if total_in > 0 and obs.cache_read_tokens > 0:
        obs.cache_pct = obs.cache_read_tokens / total_in * 100.0

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
    obs.ctx_window_size = int(ctx_block.get("context_window_size", 200000))
    usage = ctx_block.get("current_usage", {})
    obs.total_input_tokens = int(usage.get("input_tokens", 0))
    obs.total_output_tokens = int(usage.get("output_tokens", 0))
    obs.cache_read_tokens = int(usage.get("cache_read_input_tokens", 0))
    obs.cache_creation_tokens = int(usage.get("cache_creation_input_tokens", 0))

    obs.is_peak = bool(data.get("is_peak", False))
    schedule = data.get("schedule", {})
    obs.schedule_mode = schedule.get("mode", "normal")

    rate_limits = data.get("rate_limits", {})
    obs.rate_limit_5h_pct = float(rate_limits.get("pct_5h", 0.0))
    obs.rate_limit_7d_pct = float(rate_limits.get("pct_7d", 0.0))


def _apply_sample(obs: Observation, sample: dict) -> None:
    """Populate obs fields from a rolling_state sample dict."""
    obs.cost_usd = float(sample.get("cost", 0.0))
    obs.total_input_tokens = int(sample.get("tokens_in", 0))
    obs.total_output_tokens = int(sample.get("tokens_out", 0))
    obs.cache_read_tokens = int(sample.get("cache_read", 0))
    obs.cache_creation_tokens = int(sample.get("cache_creation", 0))
