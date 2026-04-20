"""Targeted tests for narrator.observations edge cases."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import narrator.observations as observations


def test_build_preserves_authoritative_stdin_peak_flag(monkeypatch):
    """Hook stdin should win over the fallback schedule probe."""
    monkeypatch.setattr(
        observations,
        "_read_stdin_json",
        lambda: {
            "is_peak": True,
            "schedule": {"mode": "peak_hours"},
            "cost": {"total_cost_usd": 0.0, "total_duration_ms": 0},
            "context_window": {
                "context_window_size": 200000,
                "current_usage": {
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cache_read_input_tokens": 0,
                    "cache_creation_input_tokens": 0,
                },
            },
            "rate_limits": {},
        },
    )
    monkeypatch.setattr(observations, "_is_peak_hours", lambda: False)
    monkeypatch.setattr(observations, "_load_statusline_state", lambda: {"samples": []})

    obs = observations.build({"current": {}})

    assert obs.is_peak is True


def test_build_zeroes_deltas_when_recent_baseline_is_missing(monkeypatch):
    """Missing 5m/20m comparison points should not turn into full-session deltas."""
    now = 2_000.0
    monkeypatch.setattr(observations.time, "time", lambda: now)
    monkeypatch.setattr(observations, "_read_stdin_json", lambda: {
        "cost": {"total_cost_usd": 5.0, "total_duration_ms": 120_000},
        "context_window": {
            "context_window_size": 100,
            "current_usage": {
                "input_tokens": 40,
                "output_tokens": 0,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0,
            },
        },
        "schedule": {"mode": "peak_hours"},
        "rate_limits": {},
    })
    monkeypatch.setattr(observations, "_is_peak_hours", lambda: False)
    monkeypatch.setattr(observations, "_load_statusline_state", lambda: {"samples": []})

    memory = {
        "current": {
            "rolling_observations": [
                {"ts": 0.0, "cost_usd": 1.5, "ctx_pct": 10.0},
            ]
        }
    }

    obs = observations.build(memory)

    assert obs.cost_delta_5m == 0.0
    assert obs.cost_delta_20m == 0.0
    assert obs.ctx_delta_5m == 0.0


def test_is_peak_hours_uses_engine_schedule_logic(monkeypatch):
    """Peak detection should delegate to the main engine instead of hardcoding UTC hours."""
    calls = {"seg_peak_hours": 0}

    def fake_seg_peak_hours(ctx):
        calls["seg_peak_hours"] += 1
        ctx["is_peak"] = True
        return "Peak"

    fake_engine = SimpleNamespace(
        load_config=lambda: {"tier": "standard"},
        load_schedule=lambda config: {"peak": {"enabled": True}},
        get_local_time=lambda: (datetime(2026, 4, 20, 9, 0, 0), "UTC", 0),
        seg_peak_hours=fake_seg_peak_hours,
    )

    monkeypatch.setattr(observations, "_load_python_engine_module", lambda: fake_engine)

    assert observations._is_peak_hours() is True
    assert calls["seg_peak_hours"] == 1