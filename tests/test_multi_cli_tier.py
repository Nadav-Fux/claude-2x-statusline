from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest


_ROOT = Path(__file__).resolve().parent.parent
_ENGINE_PATH = _ROOT / "engines" / "python-engine.py"
_spec = importlib.util.spec_from_file_location("engine_multi_cli", _ENGINE_PATH)
engine = importlib.util.module_from_spec(_spec)
try:
    _spec.loader.exec_module(engine)
    _IMPORT_OK = True
except Exception as _exc:
    _IMPORT_OK = False
    _IMPORT_ERR = str(_exc)


REGULAR_TIER_PRESETS = {
    "minimal": ["model", "context", "workflows", "tasks", "git_branch", "git_dirty", "rate_limits", "env"],
    "standard": ["model", "context", "vim_mode", "agent", "workflows", "tasks", "git_branch", "git_dirty", "cost", "effort", "env"],
    "full": ["model", "context", "vim_mode", "agent", "workflows", "tasks", "git_branch", "git_dirty", "cost", "usage_credits", "effort", "env"],
}

MULTI_CLI_PRESET = ["model", "gateway", "context", "vim_mode", "agent", "sessions", "jobs", "workflows", "tasks", "git_branch", "git_dirty", "cost", "usage_credits", "churn", "effort", "env"]


def _require_engine():
    if not _IMPORT_OK:
        pytest.skip(f"engine import failed: {_IMPORT_ERR}")


def _write_config(home: Path, config: dict) -> None:
    claude_dir = home / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    (claude_dir / "statusline-config.json").write_text(json.dumps(config), encoding="utf-8")


def _write_cached_schedule(home: Path) -> None:
    (home / ".claude" / "statusline-schedule.json").write_text(
        json.dumps(
            {
                "v": 2,
                "mode": "normal",
                "peak": {
                    "enabled": True,
                    "tz": "America/Los_Angeles",
                    "days": [1, 2, 3, 4, 5],
                    "start": 5,
                    "end": 11,
                    "label_peak": "Peak",
                    "label_offpeak": "Off-Peak",
                },
                "banner": {"text": "", "expires": "", "color": "yellow"},
                "release": {},
                "features": {"show_peak_segment": True, "show_rate_limits": False, "show_timeline": False},
            }
        ),
        encoding="utf-8",
    )


def _write_usage_cache(home: Path) -> None:
    (home / ".claude" / "statusline-usage-cache.json").write_text(
        json.dumps(
            {
                "five_hour": {"utilization": 42, "resets_at": "2099-01-01T01:00:00Z"},
                "seven_day": {"utilization": 24, "resets_at": "2099-01-07T01:00:00Z"},
            }
        ),
        encoding="utf-8",
    )


def _write_external_usage_caches(home: Path) -> None:
    claude_dir = home / ".claude"
    now = time.time()
    (claude_dir / "statusline-usage-codex.json").write_text(
        json.dumps(
            {
                "cached_at": now,
                "record": {
                    "provider": "codex",
                    "label": "Codex",
                    "available": True,
                    "five_hour": {"used_pct": 12, "resets_at": 4_071_000_000, "label": "5h"},
                    "weekly": {"used_pct": 34, "resets_at": 4_072_000_000, "label": "7d"},
                    "plan": "team",
                    "tokens": None,
                    "stale_seconds": 0,
                },
            }
        ),
        encoding="utf-8",
    )
    (claude_dir / "statusline-usage-glm.json").write_text(
        json.dumps(
            {
                "cached_at": now,
                "response": {
                    "data": {
                        "level": "lite",
                        "limits": [
                            {"type": "TIME_LIMIT", "percentage": 3, "nextResetTime": 4_071_000_000_000},
                            {"type": "TOKENS_LIMIT", "percentage": 9, "nextResetTime": 4_072_000_000_000},
                        ],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    (claude_dir / "statusline-usage-droid.json").write_text(
        json.dumps(
            {
                "cached_at": now,
                "record": {
                    "provider": "droid",
                    "label": "Droid",
                    "available": True,
                    "five_hour": None,
                    "weekly": None,
                    "plan": None,
                    "tokens": {"total": 12345},
                    "stale_seconds": 0,
                },
            }
        ),
        encoding="utf-8",
    )


def _run_engine(home: Path, stdin_data: dict) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home),
            "USERPROFILE": str(home),
            "ANTHROPIC_BASE_URL": "https://api.z.ai/api/anthropic",
            "STATUSLINE_DISABLE_TELEMETRY": "1",
        }
    )
    return subprocess.run(
        [sys.executable, str(_ENGINE_PATH)],
        input=json.dumps(stdin_data),
        text=True,
        capture_output=True,
        cwd=_ROOT,
        env=env,
        timeout=10,
        check=False,
    )


def _stdin() -> dict:
    return {
        "model": {"display_name": "Sonnet 4.6"},
        "context_window": {"context_window_size": 200000, "current_usage": {"input_tokens": 1000}},
        "cost": {"total_cost_usd": 1.23, "total_duration_ms": 600000},
        "workspace": {"current_dir": str(_ROOT)},
    }


def test_python_tier_presets_keep_regular_tiers_clean_and_add_multi_cli():
    _require_engine()
    for tier, preset in REGULAR_TIER_PRESETS.items():
        assert engine.TIER_PRESETS[tier] == preset
        for segment in ("gateway", "sessions", "jobs", "churn"):
            assert segment not in engine.TIER_PRESETS[tier]

    assert engine.TIER_PRESETS["multi-cli"] == MULTI_CLI_PRESET
    for segment in ("gateway", "sessions", "jobs", "churn", "usage_credits"):
        assert segment in engine.TIER_PRESETS["multi-cli"]


def test_python_multi_cli_effective_external_config_forces_default_providers(monkeypatch):
    _require_engine()
    captured = []

    def fake_collect(config):
        captured.append(config)
        return [
            {
                "provider": "codex",
                "label": "Codex",
                "available": True,
                "five_hour": {"used_pct": 1, "resets_at": None, "label": "5h"},
                "weekly": None,
                "plan": None,
                "tokens": None,
                "stale_seconds": 0,
            }
        ]

    monkeypatch.setattr(engine._usage_providers, "collect_external_usage", fake_collect)
    rendered = engine.build_external_usage_lines(
        {
            "config": {"tier": "multi-cli", "external_providers": {"enabled": False, "glm": {"api_key": "x"}}},
            "is_full": True,
            "is_multi_cli": True,
            "render_width": 0,
        }
    )

    assert "Codex" in rendered
    effective = captured[0]["external_providers"]
    assert effective["enabled"] is True
    assert effective["codex"]["enabled"] is True
    assert effective["glm"]["enabled"] is True
    assert effective["droid"]["enabled"] is True
    assert effective["antigravity"]["enabled"] is False


def test_python_full_tier_ignores_foreign_gateway_and_keeps_claude_rate_limit_bars(tmp_path):
    home = tmp_path / "home"
    _write_config(home, {"tier": "full", "schedule_url": "", "schedule_cache_hours": 999})
    _write_cached_schedule(home)
    _write_usage_cache(home)

    proc = _run_engine(home, _stdin())

    assert proc.returncode == 0, proc.stderr
    assert "via z.ai" not in proc.stdout
    assert "rate limits n/a on gateway" not in proc.stdout
    assert "weekly" in proc.stdout
    assert "$1.23" in proc.stdout


def test_python_multi_cli_tier_shows_gateway_badge_and_forced_external_rows(tmp_path):
    home = tmp_path / "home"
    _write_config(
        home,
        {
            "tier": "multi-cli",
            "schedule_url": "",
            "schedule_cache_hours": 999,
            "external_providers": {"enabled": False, "glm": {"api_key": "test-key"}},
        },
    )
    _write_cached_schedule(home)
    _write_usage_cache(home)
    _write_external_usage_caches(home)

    proc = _run_engine(home, _stdin())

    assert proc.returncode == 0, proc.stderr
    assert "via z.ai (GLM)" in proc.stdout
    assert "Codex" in proc.stdout
    assert "lite" in proc.stdout
    assert "Droid" in proc.stdout
