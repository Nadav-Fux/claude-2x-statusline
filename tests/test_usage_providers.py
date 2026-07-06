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


class _Proc:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_refresh_copilot_cache_org_mode_success(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd == ["gh", "auth", "status"]:
            return _Proc(0, "")
        assert cmd[0:2] == ["gh", "api"]
        assert cmd[2].startswith("/organizations/acme/settings/billing/usage?")
        return _Proc(
            0,
            json.dumps(
                {
                    "usageItems": [
                        {"sku": "Copilot AI Credits", "quantity": 500},
                        {"sku": "Actions Linux", "quantity": 999},
                    ]
                }
            ),
        )

    monkeypatch.setattr(providers.subprocess, "run", fake_run)

    assert providers.refresh_copilot_cache({"mode": "org", "org": "acme", "cap": 2000, "pool": 4000}) is True

    cache = json.loads((tmp_path / ".claude" / "statusline-usage-copilot.json").read_text(encoding="utf-8"))
    record = cache["record"]
    assert calls[0] == ["gh", "auth", "status"]
    assert record["provider"] == "copilot"
    assert record["available"] is True
    assert record["display"] == "bars"
    assert record["five_hour"]["label"] == "1500 left"
    assert record["five_hour"]["used_pct"] == 25
    assert isinstance(record["five_hour"]["resets_at"], int)
    assert record["plan"] == "business"
    assert record["source"] == "gh-billing"
    assert record["used"] == 500
    assert record["cap"] == 2000
    assert record["pool"] == 4000
    assert record["remaining"] == 1500


def test_refresh_copilot_cache_individual_derives_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))

    def fake_run(cmd, **kwargs):
        if cmd == ["gh", "auth", "status"]:
            return _Proc(0, "")
        if cmd == ["gh", "api", "user", "-q", ".login"]:
            return _Proc(0, "octo\n")
        assert cmd[0:2] == ["gh", "api"]
        assert cmd[2].startswith("/users/octo/settings/billing/usage?year=")
        return _Proc(
            0,
            json.dumps(
                {
                    "includedQuantity": 300,
                    "usageItems": [
                        {"sku": "Copilot Premium Requests", "quantity": 50},
                        {"sku": "Actions Linux", "quantity": 10},
                    ],
                }
            ),
        )

    monkeypatch.setattr(providers.subprocess, "run", fake_run)

    assert providers.refresh_copilot_cache({"mode": "individual"}) is True

    record = json.loads((tmp_path / ".claude" / "statusline-usage-copilot.json").read_text(encoding="utf-8"))["record"]
    assert record["plan"] == "individual"
    assert record["used"] == 50
    assert record["cap"] == 300
    assert record["remaining"] == 250
    assert record["five_hour"]["label"] == "250 left"
    assert record["five_hour"]["used_pct"] == 17


def test_refresh_copilot_cache_individual_without_cap_is_count_only(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))

    def fake_run(cmd, **kwargs):
        if cmd == ["gh", "auth", "status"]:
            return _Proc(0, "")
        if cmd == ["gh", "api", "user", "-q", ".login"]:
            return _Proc(0, "octo\n")
        assert cmd[0:2] == ["gh", "api"]
        assert cmd[2].startswith("/users/octo/settings/billing/usage?year=")
        return _Proc(0, json.dumps({"usageItems": [{"sku": "Copilot Premium Requests", "quantity": 12}]}))

    monkeypatch.setattr(providers.subprocess, "run", fake_run)

    assert providers.refresh_copilot_cache({"mode": "individual"}) is True

    record = json.loads((tmp_path / ".claude" / "statusline-usage-copilot.json").read_text(encoding="utf-8"))["record"]
    assert record["used"] == 12
    assert record["cap"] == 0
    assert record["remaining"] is None
    assert record["five_hour"]["label"] == "12 used"
    assert record["five_hour"]["used_pct"] == 0


def test_refresh_copilot_cache_sku_filtering(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))

    def fake_run(cmd, **kwargs):
        if cmd == ["gh", "auth", "status"]:
            return _Proc(0, "")
        return _Proc(
            0,
            json.dumps(
                {
                    "usageItems": [
                        {"sku": "Copilot AI Credits", "quantity": 500},
                        {"sku": "Copilot Premium Requests", "quantity": 9},
                    ]
                }
            ),
        )

    monkeypatch.setattr(providers.subprocess, "run", fake_run)

    assert providers.refresh_copilot_cache({"mode": "org", "org": "acme", "cap": 100, "skus": ["Premium Requests"]})
    record = json.loads((tmp_path / ".claude" / "statusline-usage-copilot.json").read_text(encoding="utf-8"))["record"]
    assert record["used"] == 9
    assert record["remaining"] == 91
    assert record["five_hour"]["used_pct"] == 9


def test_refresh_copilot_cache_gh_failure_preserves_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    cache = _write_copilot_cache(tmp_path, age_seconds=0)
    before = cache.read_text(encoding="utf-8")

    def fake_run(cmd, **kwargs):
        if cmd == ["gh", "auth", "status"]:
            return _Proc(0, "")
        return _Proc(1, "", "HTTP 403")

    monkeypatch.setattr(providers.subprocess, "run", fake_run)

    assert providers.refresh_copilot_cache({"mode": "org", "org": "acme", "cap": 2000}) is False
    assert cache.read_text(encoding="utf-8") == before


def test_refresh_copilot_cache_incomplete_org_config_returns_false(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))

    def fail_run(cmd, **kwargs):
        raise AssertionError("gh should not run for incomplete org config")

    monkeypatch.setattr(providers.subprocess, "run", fail_run)

    assert providers.refresh_copilot_cache({"mode": "org", "org": "acme"}) is False
    assert not (tmp_path / ".claude" / "statusline-usage-copilot.json").exists()


def test_copilot_reads_fresh_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    _write_copilot_cache(tmp_path, age_seconds=0)

    record = providers.get_copilot_usage({})
    expected = json.loads((FIXTURES / "copilot_usage_cache.json").read_text(encoding="utf-8"))["record"]

    assert record == expected
    assert record["provider"] == "copilot"
    assert record["available"] is True
    assert record["label"] == "Copilot"
    assert record["plan"] == "business"
    assert record["five_hour"]["used_pct"] == 25
    assert record["five_hour"]["label"] == "1500 left"


def test_copilot_reads_stale_cache_still_returns_record(tmp_path, monkeypatch):
    # A stale cache (age > 300s) still renders the last good record; the reader
    # only kicks off a detached background refresh and never clobbers the cache.
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    _write_copilot_cache(tmp_path, age_seconds=3600)
    popens = []

    class _Popen:
        def __init__(self, cmd, **kwargs):
            popens.append((cmd, kwargs))

    monkeypatch.setattr(providers.subprocess, "Popen", _Popen)

    record = providers.get_copilot_usage({})

    assert popens
    cmd, kwargs = popens[0]
    assert cmd[:2] == ["python3", "-c"]
    assert "refresh_copilot_cache" in cmd[2]
    assert kwargs["stdout"] is providers.subprocess.DEVNULL
    assert kwargs["stderr"] is providers.subprocess.DEVNULL
    assert kwargs["stdin"] is providers.subprocess.DEVNULL
    assert kwargs["start_new_session"] is True
    assert json.loads(kwargs["env"]["CLAUDE_STATUSLINE_COPILOT_CONFIG"]) == {}
    assert record["provider"] == "copilot"
    assert record["available"] is True
    assert record["five_hour"]["used_pct"] == 25
    assert record["stale_seconds"] >= 300


def test_copilot_missing_cache_is_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.setattr(providers.subprocess, "Popen", lambda *a, **k: None)

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
