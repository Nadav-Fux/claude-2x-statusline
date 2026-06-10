"""Narrator rate-limit source tests."""

from __future__ import annotations

import json
from pathlib import Path

import narrator.observations as observations


def test_build_reads_rate_limits_from_usage_cache_not_stdin(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    claude_dir = fake_home / ".claude"
    claude_dir.mkdir(parents=True)
    (claude_dir / "statusline-usage-cache.json").write_text(
        json.dumps(
            {
                "five_hour": {"utilization": 72.5},
                "seven_day": {"utilization": 41.25},
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))
    monkeypatch.setattr(observations, "_is_peak_hours", lambda: False)
    monkeypatch.setattr(observations, "_load_statusline_state", lambda: {"samples": []})
    monkeypatch.setattr(
        observations,
        "_read_stdin_json",
        lambda: {
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
            "rate_limits": {
                "pct_5h": 999.0,
                "pct_7d": 999.0,
                "five_hour": {"utilization": 999.0},
                "seven_day": {"utilization": 999.0},
            },
        },
    )

    obs = observations.build({"current": {}})

    assert obs.rate_limit_5h_pct == 72.5
    assert obs.rate_limit_7d_pct == 41.25


def test_build_survives_wrong_shape_usage_cache(tmp_path, monkeypatch):
    """Valid JSON with the wrong shape must coerce to 0.0, not throw."""
    fake_home = tmp_path / "home"
    claude_dir = fake_home / ".claude"
    claude_dir.mkdir(parents=True)
    (claude_dir / "statusline-usage-cache.json").write_text(
        json.dumps(
            {
                "five_hour": None,
                "seven_day": {"utilization": "abc"},
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))
    monkeypatch.setattr(observations, "_is_peak_hours", lambda: False)
    monkeypatch.setattr(observations, "_load_statusline_state", lambda: {"samples": []})
    monkeypatch.setattr(observations, "_read_stdin_json", lambda: None)

    obs = observations.build({"current": {}})

    assert obs.rate_limit_5h_pct == 0.0
    assert obs.rate_limit_7d_pct == 0.0
