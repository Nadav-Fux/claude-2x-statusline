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
    # source == "local-jsonl" + a small stale_seconds is the ONE trustworthy
    # per-record recency signal (see _provider_recently_active) — this is the
    # "active multi-CLI flow" case, so the insight should fire.
    obs = Observation(
        external_usage=[
            {
                "provider": "glm",
                "label": "GLM",
                "available": True,
                "source": "local-jsonl",
                "stale_seconds": 30,
                "five_hour": {"used_pct": 0},
                "weekly": {"used_pct": 100, "label": "tok"},
            }
        ]
    )

    insights = _build_insights(obs, _memory())
    capped = [insight for insight in insights if insight.template_key == "cross_cli_capped"]

    assert capped
    assert "GLM's tok quota is maxed (100%)" in capped[0].text
    assert "Your Claude budget" in capped[0].text
    assert capped[0].text_he
    assert "GLM" in capped[0].text_he


def test_cross_cli_capped_suppressed_when_capped_cli_is_idle():
    # Same cap, but the record's own recency signal shows it hasn't been
    # touched in an hour (source == "local-jsonl", stale_seconds way past the
    # 10-minute window) — an idle CLI's cap must not surface as an insight.
    obs = Observation(
        external_usage=[
            {
                "provider": "glm",
                "label": "GLM",
                "available": True,
                "source": "local-jsonl",
                "stale_seconds": 3600,
                "five_hour": {"used_pct": 0},
                "weekly": {"used_pct": 100, "label": "tok"},
            }
        ]
    )

    assert "cross_cli_capped" not in _keys(obs)


def test_cross_cli_capped_suppressed_for_untrusted_live_source_when_claude_is_cool():
    # Reproduces the reported false alarm: Codex's LIVE ("app-server") snapshot
    # always carries stale_seconds == 0 — written fresh on every background
    # poll regardless of whether Codex was actually used (see
    # lib.usage_providers.normalize_codex_rate_limits / CODEX_LIVE_TTL). That
    # "0" looks fresh but is not proof of recent human activity, so
    # "app-server" is not a trusted source (see _LOCAL_ACTIVITY_SOURCES) and
    # the conservative fallback applies instead. With Claude's own 5h usage at
    # 2% and no weekly-pace data, the fallback must suppress — this is exactly
    # the "Claude at 2%, Codex maxed" false alarm from the bug report.
    obs = Observation(
        rate_limit_5h_pct=2,
        external_usage=[
            {
                "provider": "codex",
                "label": "Codex",
                "available": True,
                "source": "app-server",
                "stale_seconds": 0,
                "five_hour": {"used_pct": 100, "label": "5h"},
                "weekly": {"used_pct": 0, "label": "7d"},
            }
        ],
    )

    assert "cross_cli_capped" not in _keys(obs)


def test_cross_cli_capped_fallback_fires_when_claude_5h_is_hot():
    # Same untrusted-source record as above, but Claude's OWN 5h usage is
    # already warm (>= 50%) — the conservative fallback now judges the
    # cross-CLI mention relevant even without a trusted per-record signal, and
    # the wording still names the other CLI and clarifies Claude is unaffected.
    obs = Observation(
        rate_limit_5h_pct=60,
        external_usage=[
            {
                "provider": "codex",
                "label": "Codex",
                "available": True,
                "source": "app-server",
                "stale_seconds": 0,
                "five_hour": {"used_pct": 100, "label": "5h"},
                "weekly": {"used_pct": 0, "label": "7d"},
            }
        ],
    )

    insights = _build_insights(obs, _memory())
    capped = [insight for insight in insights if insight.template_key == "cross_cli_capped"]

    assert capped
    assert "Codex" in capped[0].text
    assert "Your Claude budget" in capped[0].text


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
