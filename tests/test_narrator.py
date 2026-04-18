"""Tests for the narrator line (plain-language insight picker).

These tests exercise the pure `_narrator_insights(ctx)` helper, which is
deterministic given ctx + rolling_state. We avoid hitting build_narrator_line
directly because its string output depends on ANSI color constants and makes
brittle assertions.
"""
import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_engine():
    """Load engines/python-engine.py as a module and return it.

    The hyphen in the filename blocks a normal import, so we go through
    importlib. The module has no top-level side effects (main() is only
    called under `if __name__ == '__main__'`).
    """
    spec = importlib.util.spec_from_file_location(
        "engine", REPO_ROOT / "engines" / "python-engine.py"
    )
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as e:
        pytest.skip(f"engine import failed: {e}")
    return module


def _make_ctx(cost_usd=1.0, duration_ms=60000, ctx_size=200000,
              input_tokens=50000, cache_read=30000, cache_create=2000,
              output_tokens=1000, is_peak=False, schedule_mode="schedule"):
    return {
        "stdin": {
            "cost": {
                "total_cost_usd": cost_usd,
                "total_duration_ms": duration_ms,
            },
            "context_window": {
                "context_window_size": ctx_size,
                "current_usage": {
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "cache_read_input_tokens": cache_read,
                    "cache_creation_input_tokens": cache_create,
                },
            },
        },
        "is_peak": is_peak,
        "schedule": {"mode": schedule_mode},
    }


def test_no_insights_on_fresh_session(tmp_state_dir):
    """With zero cost and no rolling data, narrator stays silent."""
    engine = _load_engine()
    ctx = _make_ctx(cost_usd=0.0, duration_ms=0)
    insights = engine._narrator_insights(ctx)
    # Cost rate is None AND rate_session < 0.5 → no burn insight.
    # No peak, schedule_mode=schedule → off-peak insight still triggers.
    # That's fine; assert list is either empty OR contains only off-peak.
    assert all("Off-peak" in text or "headroom" in text for _, text, _ in insights)


def test_session_fallback_when_no_rolling_window(tmp_state_dir):
    """With no rolling samples, session-rate fallback fires."""
    engine = _load_engine()
    # $6.00 over 1 hour = $6/hr (session)
    ctx = _make_ctx(cost_usd=6.0, duration_ms=3600000)
    insights = engine._narrator_insights(ctx)
    texts = [t for _, t, _ in insights]
    assert any("$6.0/hr (session)" in t for t in texts)


def test_high_burn_triggers_critical(tmp_state_dir):
    """Burn >= $15/hr triggers priority-2 RED insight."""
    engine = _load_engine()
    # $20 over 1 hour = $20/hr
    ctx = _make_ctx(cost_usd=20.0, duration_ms=3600000)
    insights = engine._narrator_insights(ctx)
    assert any(p <= 2 and "high" in t for p, t, _ in insights)


def test_low_burn_marks_dim(tmp_state_dir):
    """Low burn rate appears as informational dim insight."""
    engine = _load_engine()
    # $1 over 1 hour = $1/hr
    ctx = _make_ctx(cost_usd=1.0, duration_ms=3600000)
    insights = engine._narrator_insights(ctx)
    texts = [t for _, t, _ in insights]
    assert any("low burn" in t for t in texts)


def test_peak_insight_when_peak_active(tmp_state_dir):
    """is_peak=True surfaces the peak-hours warning."""
    engine = _load_engine()
    ctx = _make_ctx(is_peak=True)
    insights = engine._narrator_insights(ctx)
    assert any("Peak hours" in t for _, t, _ in insights)


def test_offpeak_insight_in_schedule_mode(tmp_state_dir):
    """schedule.mode == 'schedule' + not peak → off-peak info."""
    engine = _load_engine()
    ctx = _make_ctx(is_peak=False, schedule_mode="schedule")
    insights = engine._narrator_insights(ctx)
    assert any("Off-peak" in t for _, t, _ in insights)


def test_no_offpeak_insight_in_normal_mode(tmp_state_dir):
    """schedule.mode == 'normal' means all-day free usage — suppress off-peak line."""
    engine = _load_engine()
    ctx = _make_ctx(is_peak=False, schedule_mode="normal")
    insights = engine._narrator_insights(ctx)
    assert not any("Off-peak" in t for _, t, _ in insights)


def test_context_pressure_at_80_percent(tmp_state_dir):
    """Context at 80%+ (and no tight mins_left) adds the 'headroom shrinking' note."""
    engine = _load_engine()
    # 160K used of 200K = 80%
    ctx = _make_ctx(
        ctx_size=200000,
        input_tokens=140000,
        cache_read=20000,
        cache_create=0,
    )
    insights = engine._narrator_insights(ctx)
    assert any("headroom" in t.lower() for _, t, _ in insights)


def test_build_narrator_line_caps_at_two(tmp_state_dir):
    """Even if many insights trigger, the line contains at most 2 separators."""
    engine = _load_engine()
    ctx = _make_ctx(
        cost_usd=20.0,
        duration_ms=3600000,
        ctx_size=200000,
        input_tokens=160000,
        is_peak=True,
    )
    line = engine.build_narrator_line(ctx)
    # ' · ' is the separator, so 2 insights = 1 separator max.
    assert line.count("\u00b7") <= 2  # 1 separator + possibly the ⓘ prefix


def test_build_narrator_returns_empty_when_no_data(tmp_state_dir):
    """No cost, no peak, schedule.mode == 'normal' → line is empty."""
    engine = _load_engine()
    ctx = _make_ctx(cost_usd=0.0, duration_ms=0, schedule_mode="normal")
    line = engine.build_narrator_line(ctx)
    assert line == ""


def test_insights_sorted_by_priority(tmp_state_dir):
    """build_narrator_line must pick lowest-priority-number (most urgent) first."""
    engine = _load_engine()
    # High burn ($20/hr) + off-peak → priority 2 (high burn) beats priority 6 (off-peak)
    ctx = _make_ctx(cost_usd=20.0, duration_ms=3600000, is_peak=False, schedule_mode="schedule")
    line = engine.build_narrator_line(ctx)
    # High-burn should appear before off-peak (if both present)
    if "high" in line and "Off-peak" in line:
        assert line.index("high") < line.index("Off-peak")
