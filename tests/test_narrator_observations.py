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


# ---------------------------------------------------------------------------
# Context window resolution (1M-aware) — guards the 200k-vs-1M false-alarm bug
# ---------------------------------------------------------------------------

def test_resolve_ctx_window_env_override(monkeypatch):
    monkeypatch.setenv("STATUSLINE_CTX_WINDOW", "777000")
    monkeypatch.setattr(observations, "_load_statusline_context", lambda *a, **k: {})
    assert observations._resolve_ctx_window_size({"context_window": {"context_window_size": 200000}}) == 777000


def test_resolve_ctx_window_trusts_real_stdin_size(monkeypatch):
    monkeypatch.delenv("STATUSLINE_CTX_WINDOW", raising=False)
    # A real 200k model must stay 200k even if the bar file says otherwise.
    monkeypatch.setattr(observations, "_load_statusline_context", lambda *a, **k: {"context_window_size": 1000000})
    assert observations._resolve_ctx_window_size({"context_window": {"context_window_size": 200000}}) == 200000


def test_resolve_ctx_window_from_bar_context_file(monkeypatch):
    """The narrator's hook stdin has no context_window — fall back to the bar file."""
    monkeypatch.delenv("STATUSLINE_CTX_WINDOW", raising=False)
    monkeypatch.setattr(
        observations, "_load_statusline_context",
        lambda *a, **k: {"context_window_size": 1000000, "model": "Opus 4.8 (1M context)"},
    )
    assert observations._resolve_ctx_window_size({}) == 1000000
    assert observations._resolve_ctx_window_size({"context_window": {}}) == 1000000


def test_resolve_ctx_window_from_model_name_when_size_missing(monkeypatch):
    monkeypatch.delenv("STATUSLINE_CTX_WINDOW", raising=False)
    monkeypatch.setattr(observations, "_load_statusline_context", lambda *a, **k: {"model": "Opus 4.8 (1M context)"})
    assert observations._resolve_ctx_window_size({}) == 1000000


def test_resolve_ctx_window_from_stdin_model_id(monkeypatch):
    monkeypatch.delenv("STATUSLINE_CTX_WINDOW", raising=False)
    monkeypatch.setattr(observations, "_load_statusline_context", lambda *a, **k: {})
    assert observations._resolve_ctx_window_size({"model": {"id": "claude-opus-4-8[1m]"}}) == 1000000


def test_resolve_ctx_window_defaults_to_200k(monkeypatch):
    monkeypatch.delenv("STATUSLINE_CTX_WINDOW", raising=False)
    monkeypatch.setattr(observations, "_load_statusline_context", lambda *a, **k: {})
    assert observations._resolve_ctx_window_size({}) == 200000
    assert observations._resolve_ctx_window_size({"model": {"display_name": "Sonnet 4.5"}}) == 200000


def test_resolve_ctx_window_1m_model_overrides_wrong_stdin_200k(monkeypatch):
    """Regression (2026-06-26): Claude Code now sends context_window_size=200000 on
    stdin even for a [1m] session. The 1M model detection MUST win over that wrong
    size, else 306k reads ~150% and fires false 'context full' pressure every prompt."""
    monkeypatch.delenv("STATUSLINE_CTX_WINDOW", raising=False)
    monkeypatch.setattr(observations, "_load_statusline_context", lambda *a, **k: {})
    stdin = {"model": {"id": "claude-opus-4-8[1m]"},
             "context_window": {"context_window_size": 200000}}
    assert observations._resolve_ctx_window_size(stdin) == 1_000_000


def test_build_ctx_pct_uses_true_1m_window_not_200k(monkeypatch):
    """Regression: ~160k tokens on a 1M model must read ~16%, not ~80%.

    Reproduces the real narrator path: hook stdin carries NO context_window, so
    tokens come from the rolling sample and the window must be resolved from the
    bar's context file (1,000,000). Before the fix this was 160k/200k = 80% and
    fired the pressure templates.
    """
    monkeypatch.delenv("STATUSLINE_CTX_WINDOW", raising=False)
    monkeypatch.setattr(observations, "_read_stdin_json", lambda: {
        "session_id": "s1",
        "cost": {"total_cost_usd": 50.0, "total_duration_ms": 7_200_000},
    })
    monkeypatch.setattr(observations, "_is_peak_hours", lambda: False)
    monkeypatch.setattr(observations, "_load_statusline_state", lambda: {
        "samples": [{"t": 1000.0, "cost": 50.0, "tokens_in": 2000, "tokens_out": 10,
                     "cache_read": 158000, "cache_creation": 0}],
    })
    monkeypatch.setattr(
        observations, "_load_statusline_context",
        lambda *a, **k: {"context_window_size": 1000000, "model": "Opus 4.8 (1M context)"},
    )

    obs = observations.build({"current": {}})

    assert obs.ctx_window_size == 1_000_000
    assert 15.0 < obs.ctx_pct < 17.0  # ~16%, NOT ~80%
    assert obs.ctx_pct < 70.0  # below every pressure-template threshold