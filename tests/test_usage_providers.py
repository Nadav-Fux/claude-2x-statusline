import json
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

    row = providers.format_provider_row_parts(record, 1_000)
    assert next(part for part in row["parts"] if part.get("kind") == "window" and part.get("pct") == 99)["label"] == "tok"


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


def test_providers_gracefully_unavailable_without_home_data(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.delenv("ZAI_API_KEY", raising=False)
    monkeypatch.delenv("ZHIPU_API_KEY", raising=False)

    for name in ("codex", "glm", "droid", "antigravity"):
        record = providers.get_provider_usage(name, {})
        assert record["provider"] == name
        assert record["available"] is False
