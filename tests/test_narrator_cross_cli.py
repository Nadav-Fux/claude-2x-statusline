import json
import time

from lib import usage_providers
from narrator.observations import Observation
from narrator.scoring import _build_insights


def _memory():
    return {"current": {"delivered_narratives": []}, "prior_sessions": []}


def _keys(obs):
    return {insight.template_key for insight in _build_insights(obs, _memory())}


def test_cross_cli_capped_fires_for_external_cap():
    obs = Observation(
        external_usage=[
            {
                "provider": "glm",
                "label": "GLM",
                "available": True,
                "five_hour": {"used_pct": 0},
                "weekly": {"used_pct": 100, "label": "tok"},
            }
        ]
    )

    insights = _build_insights(obs, _memory())
    capped = [insight for insight in insights if insight.template_key == "cross_cli_capped"]

    assert capped
    assert "GLM tok quota is maxed (100%)" in capped[0].text
    assert capped[0].text_he


def test_cross_cli_offload_fires_when_claude_weekly_hot_and_external_cool():
    obs = Observation(
        rate_limit_7d_pct=70,
        external_usage=[
            {
                "provider": "codex",
                "label": "Codex",
                "available": True,
                "five_hour": {"used_pct": 10, "label": "5h"},
                "weekly": {"used_pct": 10, "label": "7d"},
            }
        ],
    )

    assert "cross_cli_offload" in _keys(obs)


def test_cross_cli_offload_skips_provider_busy_on_any_window():
    # Codex weekly is cool (25%) but its 5h window is at 90% — a bad offload
    # target. With no genuinely-cool provider, offload must stay silent.
    obs = Observation(
        rate_limit_7d_pct=70,
        external_usage=[
            {
                "provider": "codex",
                "label": "Codex",
                "available": True,
                "five_hour": {"used_pct": 90, "label": "5h"},
                "weekly": {"used_pct": 25, "label": "7d"},
            }
        ],
    )

    assert "cross_cli_offload" not in _keys(obs)


def test_cross_cli_templates_do_not_fire_without_external_usage():
    obs = Observation(rate_limit_7d_pct=70, external_usage=[])

    keys = _keys(obs)

    assert "cross_cli_capped" not in keys
    assert "cross_cli_offload" not in keys


def test_read_cached_external_usage_parses_glm_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(usage_providers.Path, "home", staticmethod(lambda: tmp_path))
    cache_dir = tmp_path / ".claude"
    cache_dir.mkdir()
    response = {
        "data": {
            "level": "lite",
            "limits": [
                {"type": "TIME_LIMIT", "percentage": 0, "nextResetTime": 1_783_532_012_000},
                {"type": "TOKENS_LIMIT", "percentage": 100, "nextResetTime": 1_782_782_126_000},
            ],
        }
    }
    (cache_dir / "statusline-usage-glm.json").write_text(
        json.dumps({"cached_at": time.time(), "response": response}),
        encoding="utf-8",
    )

    records = usage_providers.read_cached_external_usage(
        {
            "external_providers": {
                "enabled": True,
                "glm": {"enabled": True},
            }
        }
    )

    assert len(records) == 1
    assert records[0]["provider"] == "glm"
    assert records[0]["weekly"]["used_pct"] == 100
    assert records[0]["weekly"]["label"] == "tok"
