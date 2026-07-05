import json
import os
import time
from pathlib import Path

from lib import usage_providers as providers


FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_codex_fixture_maps_rate_limits():
    line = (FIXTURES / "codex_rollout_token_count.jsonl").read_text(encoding="utf-8").strip()

    record = providers.parse_codex_token_count_line(line)

    assert record["available"] is True
    assert record["five_hour"]["used_pct"] == 47
    assert record["five_hour"]["resets_at"] == 1782536836
    assert record["five_hour"]["label"] == "5h"
    assert record["weekly"]["used_pct"] == 10
    assert record["weekly"]["resets_at"] == 1783029435
    assert record["weekly"]["label"] == "7d"
    assert record["plan"] == "team"


def test_glm_fixture_maps_quota_limits():
    data = json.loads((FIXTURES / "glm_quota_response.json").read_text(encoding="utf-8"))

    record = providers.parse_glm_quota_response(data)

    assert record["available"] is True
    assert record["five_hour"]["used_pct"] == 0
    assert abs(record["five_hour"]["resets_at"] - 1783532012) <= 1
    assert record["five_hour"]["label"] == "5h"
    assert record["weekly"]["used_pct"] == 99
    assert abs(record["weekly"]["resets_at"] - 1782782126) <= 1
    assert record["weekly"]["label"] == "tok"
    assert record["plan"] == "lite"
    assert record["display"] == "compact"
    assert [(metric["label"], metric["used_pct"]) for metric in record["metrics"]] == [("5h", 0), ("tok", 99)]

    row = providers.format_provider_row_parts(record, 1_000)
    assert row["display"] == "compact"
    assert next(part for part in row["parts"] if part.get("kind") == "metric" and part.get("pct") == 99)["label"] == "tok"
    assert "5h 0%" in row["text"]
    assert "tok 99%" in row["text"]
    assert "\u25b0" not in row["text"]
    assert "\u25b1" not in row["text"]


def test_compact_provider_row_parts_render_metrics_without_bars_while_bars_records_keep_bars():
    compact = providers.format_provider_row_parts(
        {
            "provider": "glm",
            "label": "GLM",
            "available": True,
            "display": "compact",
            "metrics": [
                {"label": "5h", "used_pct": 0, "resets_at": 1_000 + 39 * 60},
                {"label": "tok", "used_pct": 8, "resets_at": 1_000 + 90 * 60},
            ],
            "five_hour": {"used_pct": 0, "resets_at": 1_000 + 39 * 60, "label": "5h"},
            "weekly": {"used_pct": 8, "resets_at": 1_000 + 90 * 60, "label": "tok"},
            "plan": "lite",
            "tokens": None,
            "stale_seconds": 0,
        },
        1_000,
    )

    assert "GLM lite  5h 0% \u00b7 tok 8% \u27f3 39m" in compact["text"]
    assert "\u25b0" not in compact["text"]
    assert "\u25b1" not in compact["text"]

    bars = providers.format_provider_row_parts(
        {
            "provider": "codex",
            "label": "Codex",
            "available": True,
            "display": "bars",
            "five_hour": {"used_pct": 60, "resets_at": None, "label": "5h"},
            "weekly": None,
            "plan": None,
            "tokens": None,
            "stale_seconds": 0,
        },
        1_000,
    )

    assert "\u25b0" in bars["text"] or "\u25b1" in bars["text"]


def test_provider_row_parts_include_reset_countdown_and_stale_marker():
    row = providers.format_provider_row_parts(
        {
            "provider": "codex",
            "label": "Codex",
            "available": True,
            "five_hour": {"used_pct": 60, "resets_at": 1_000 + 133 * 60},
            "weekly": None,
            "plan": "team",
            "tokens": None,
            "stale_seconds": 1_200,
        },
        1_000,
        label_width=7,
    )

    assert row["parts"][0]["label"] == "Codex  "
    assert row["parts"][1]["reset_text"] == "\u27f3 2h 13m"
    assert row["stale_text"] == " \u00b7stale"


def test_provider_row_parts_prefer_per_window_labels():
    row = providers.format_provider_row_parts(
        {
            "provider": "antigravity",
            "label": "Antigravity",
            "available": True,
            "five_hour": {"used_pct": 40, "resets_at": None, "label": "5h"},
            "weekly": {"used_pct": 12, "resets_at": None, "label": "wk"},
            "plan": None,
            "tokens": None,
            "stale_seconds": 0,
        },
        1_000,
    )

    assert row["parts"][1]["label"] == "5h"
    assert row["parts"][2]["label"] == "wk"


def test_antigravity_parser_maps_sprint_and_weekly_windows():
    record = providers.parse_antigravity_item_table(
        [
            {
                "key": "antigravity.usage",
                "value": '{"sprint":{"usedPercent":40,"resetsAt":1790000000},"weekly":{"usedPercent":12}}',
            }
        ]
    )

    assert record["available"] is True
    assert record["five_hour"]["used_pct"] == 40
    assert record["five_hour"]["resets_at"] == 1790000000
    assert record["five_hour"]["label"] == "5h"
    assert record["weekly"]["used_pct"] == 12
    assert record["weekly"]["resets_at"] is None
    assert record["weekly"]["label"] == "wk"


def test_antigravity_model_parser_maps_model_group_metrics():
    metrics = providers.parse_antigravity_models(
        {
            "models": {
                "gemini-3-flash": {"usedPercent": 23},
                "gemini-3-pro-low": {"usedPercent": 67},
                "claude-opus": {"usedPercent": 41},
            }
        }
    )

    assert [(metric["label"], metric["used_pct"]) for metric in metrics] == [("Flash", 23), ("Pro", 67), ("Opus", 41)]
    assert providers.parse_antigravity_models({"hello": "world"}) is None

    record = providers.parse_antigravity_item_table(
        [
            {
                "key": "antigravity.models",
                "value": json.dumps(
                    {
                        "models": {
                            "gemini-3-flash": {"usedPercent": 23},
                            "gemini-3-pro-low": {"usedPercent": 67},
                            "claude-opus": {"usedPercent": 41},
                        }
                    }
                ),
            }
        ]
    )
    assert record["available"] is True
    assert record["label"] == "AGY"
    assert record["display"] == "compact"
    assert [(metric["label"], metric["used_pct"]) for metric in record["metrics"]] == [
        ("Flash", 23),
        ("Pro", 67),
        ("Opus", 41),
    ]


def test_antigravity_parser_returns_unavailable_for_junk_rows():
    record = providers.parse_antigravity_item_table(
        [
            {"key": "antigravity.usage", "value": "not json"},
            {"key": "other", "value": '{"hello":"world"}'},
        ]
    )

    assert record["provider"] == "antigravity"
    assert record["available"] is False


def test_provider_row_parts_omit_past_reset_countdown():
    row = providers.format_provider_row_parts(
        {
            "provider": "glm",
            "label": "GLM",
            "available": True,
            "five_hour": {"used_pct": 0, "resets_at": 999},
            "weekly": None,
            "plan": "lite",
            "tokens": None,
            "stale_seconds": 0,
        },
        1_000,
    )

    assert row["parts"][1]["reset_text"] == ""
    assert row["stale_text"] == ""


def test_antigravity_dual_model_rows_render_two_compact_rows_without_bars():
    record = {
        "provider": "antigravity",
        "label": "AGY",
        "available": True,
        "display": "compact",
        "metrics_5h": [
            {"label": "Opus", "used_pct": 12, "resets_at": 4_071_000_000},
            {"label": "Pro", "used_pct": 45, "resets_at": 4_071_000_000},
            {"label": "Flash", "used_pct": 7, "resets_at": 4_071_000_000},
        ],
        "metrics_weekly": [
            {"label": "Opus", "used_pct": 30, "resets_at": 4_072_000_000},
            {"label": "Pro", "used_pct": 60, "resets_at": 4_072_000_000},
            {"label": "Flash", "used_pct": 22, "resets_at": 4_072_000_000},
        ],
        "stale_seconds": 0,
    }

    # Fixed clock formatter so the two-row layout is deterministic across hosts.
    def clock(_epoch, style):
        return "12:00pm" if style == "time" else "4/7 5:00am"

    row = providers.format_provider_row_parts(record, 1_000, format_clock=clock)

    assert row is not None
    assert row["display"] == "agy_dual"
    assert len(row["sub_rows"]) == 2

    lines = row["text"].splitlines()
    assert len(lines) == 2
    five_hour, weekly = lines

    assert five_hour.startswith("AGY 5h")
    assert "Opus 12%" in five_hour and "Pro 45%" in five_hour and "Flash 7%" in five_hour
    assert "⟳ 12:00pm" in five_hour

    assert weekly.startswith("AGY 7d")
    assert "Opus 30%" in weekly and "Pro 60%" in weekly and "Flash 22%" in weekly
    assert "⟳ 4/7 5:00am" in weekly

    # No bar glyphs in either row.
    assert "▰" not in row["text"]
    assert "▱" not in row["text"]


def _write_copilot_cache(home, age_seconds=0):
    """Copy the copilot cache fixture into a monkeypatched home and age it.

    Returns the cache path. `age_seconds` sets how long ago the file was last
    written (0 = fresh, >300 = stale enough to trigger a background refresh).
    """
    claude_dir = home / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    cache = claude_dir / "statusline-usage-copilot.json"
    cache.write_text((FIXTURES / "copilot_usage_cache.json").read_text(encoding="utf-8"), encoding="utf-8")
    mtime = time.time() - age_seconds
    os.utime(cache, (mtime, mtime))
    return cache


def test_copilot_reads_fresh_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    _write_copilot_cache(tmp_path, age_seconds=0)

    record = providers.get_copilot_usage({})

    assert record["provider"] == "copilot"
    assert record["available"] is True
    assert record["label"] == "Copilot"
    assert record["plan"] == "business"
    assert record["five_hour"]["used_pct"] == 25
    assert record["five_hour"]["label"] == "1500 left"


def test_copilot_reads_stale_cache_still_returns_record(tmp_path, monkeypatch):
    # A stale cache (age > 300s) still renders the last good record; the reader
    # only kicks off a background refresh (no refresh script exists under the
    # test home, so nothing is spawned) and never clobbers the cache.
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    _write_copilot_cache(tmp_path, age_seconds=3600)

    record = providers.get_copilot_usage({})

    assert record["provider"] == "copilot"
    assert record["available"] is True
    assert record["five_hour"]["used_pct"] == 25


def test_copilot_missing_cache_is_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))

    record = providers.get_copilot_usage({})

    assert record["provider"] == "copilot"
    assert record["available"] is False


def test_providers_gracefully_unavailable_without_home_data(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.delenv("ZAI_API_KEY", raising=False)
    monkeypatch.delenv("ZHIPU_API_KEY", raising=False)

    for name in ("codex", "glm", "droid", "antigravity"):
        record = providers.get_provider_usage(name, {})
        assert record["provider"] == name
        assert record["available"] is False
