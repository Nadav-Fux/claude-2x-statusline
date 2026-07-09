import json
import os
import time
import urllib.error
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


def test_codex_new_schema_30d_single_window():
    # New Codex CLI schema: primary is a 30-day window, secondary is null, and the
    # wrapper carries limit_id/credits/individual_limit/rate_limit_reached_type.
    line = (FIXTURES / "codex_rollout_token_count_30d.jsonl").read_text(encoding="utf-8").strip()

    record = providers.parse_codex_token_count_line(line)

    assert record["available"] is True
    assert record["five_hour"]["used_pct"] == 6
    assert record["five_hour"]["resets_at"] == 1786214766
    assert record["five_hour"]["label"] == "30d"  # 43200 minutes -> honest 30d label
    assert record["weekly"] is None  # secondary null -> no weekly window
    assert record["plan"] == "free"

    row = providers.format_provider_row_parts(record, 1_000, label_width=5)
    window_parts = [part for part in row["parts"] if part.get("kind") == "window"]
    assert len(window_parts) == 1
    assert window_parts[0]["label"] == "30d"
    assert window_parts[0]["pct"] == 6
    assert "30d" in row["text"]
    assert "7d" not in row["text"]


def test_codex_window_label_maps_minutes_to_honest_labels():
    assert providers._codex_window_label(300, "5h") == "5h"
    assert providers._codex_window_label(10080, "7d") == "7d"
    assert providers._codex_window_label(43200, "7d") == "30d"
    assert providers._codex_window_label(720, "5h") == "12h"
    assert providers._codex_window_label(None, "7d") == "7d"
    assert providers._codex_window_label("bad", "5h") == "5h"


def _install_codex_rollouts(home, entries):
    """Write rollout fixtures into a monkeypatched ~/.codex/sessions tree.

    ``entries`` is a list of (name, fixture_file, mtime) tuples; each fixture is
    copied to sessions/2026/07/09/rollout-<name>.jsonl and stamped with mtime so
    the scan's newest-first ordering is deterministic.
    """
    base = home / ".codex" / "sessions" / "2026" / "07" / "09"
    base.mkdir(parents=True, exist_ok=True)
    for name, fixture, mtime in entries:
        dest = base / f"rollout-{name}.jsonl"
        dest.write_text((FIXTURES / fixture).read_text(encoding="utf-8"), encoding="utf-8")
        os.utime(dest, (mtime, mtime))


def test_codex_prefers_paid_plan_over_newer_free(tmp_path, monkeypatch):
    # Two apps share ~/.codex: the newest rollout is a FREE account (30d 6%),
    # an older one is the paid TEAM account (5h 100%, weekly 84%). Default config
    # must surface the paid limits, not the harmless free window.
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    now = time.time()
    _install_codex_rollouts(
        tmp_path,
        [
            ("team", "codex_rollout_team_snapshot.jsonl", now - 3600),
            ("free", "codex_rollout_token_count_30d.jsonl", now - 60),
        ],
    )

    record = providers.get_codex_usage({})

    assert record["available"] is True
    assert record["plan"] == "team"
    assert record["five_hour"]["used_pct"] == 100
    assert record["five_hour"]["label"] == "5h"
    assert record["weekly"]["used_pct"] == 84
    assert record["weekly"]["label"] == "7d"
    # stale reflects the SELECTED (team) snapshot's file age, not the newest file.
    assert record["stale_seconds"] >= 3600

    # Default config does NOT surface all_plans: one Codex subscription, one row.
    assert "all_plans" not in record

    # The row renders a single line for the selected (team) plan.
    row = providers.format_provider_row_parts(record, now, label_width=5)
    assert row.get("sub_rows") is None
    assert "team" in row["text"] and "5h" in row["text"] and "100%" in row["text"]
    assert "7d" in row["text"] and "84%" in row["text"]


def test_codex_windowed_snapshot_beats_newer_tokens_only_same_plan(tmp_path, monkeypatch):
    # A resumed/idle session can leave a team rollout with a fresher mtime whose
    # last event is tokens-only (rate_limits present but primary/secondary null).
    # The scan must upgrade that placeholder with the older WINDOWED team
    # snapshot instead of rendering a bar-less row.
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    now = time.time()
    _install_codex_rollouts(
        tmp_path,
        [
            ("free", "codex_rollout_token_count_30d.jsonl", now - 60),
            ("team-idle", "codex_rollout_team_tokens_only.jsonl", now - 600),
            ("team-real", "codex_rollout_team_snapshot.jsonl", now - 7200),
        ],
    )

    record = providers.get_codex_usage({})

    assert record["plan"] == "team"
    assert record["five_hour"]["used_pct"] == 100
    assert record["weekly"]["used_pct"] == 84
    # stale reflects the windowed snapshot actually selected.
    assert record["stale_seconds"] >= 7200


def test_codex_plan_pin_selects_free(tmp_path, monkeypatch):
    # An explicit external_providers.codex.plan pin overrides the paid-first rule.
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    now = time.time()
    _install_codex_rollouts(
        tmp_path,
        [
            ("team", "codex_rollout_team_snapshot.jsonl", now - 60),
            ("free", "codex_rollout_token_count_30d.jsonl", now - 3600),
        ],
    )

    record = providers.get_codex_usage({"external_providers": {"codex": {"plan": "free"}}})

    assert record["plan"] == "free"
    assert record["five_hour"]["used_pct"] == 6
    assert record["five_hour"]["label"] == "30d"
    assert record["weekly"] is None
    # Default config (show_all_plans unset) does NOT surface all_plans.
    assert "all_plans" not in record


def test_codex_all_plans_ages_out_stale_team(tmp_path, monkeypatch):
    # The owner switched off team >7 days ago (stale snapshot); free is current.
    # The stale team plan ages out of all_plans, and — no fresh paid plan left —
    # selection falls back through the unchanged rules to the newest overall (free).
    # show_all_plans is opted in so all_plans is still populated for this check.
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    now = time.time()
    _install_codex_rollouts(
        tmp_path,
        [
            ("team", "codex_rollout_team_snapshot.jsonl", now - 8 * 86400),
            ("free", "codex_rollout_token_count_30d.jsonl", now - 60),
        ],
    )

    record = providers.get_codex_usage({"external_providers": {"codex": {"show_all_plans": True}}})

    assert record["plan"] == "free"
    assert record["five_hour"]["label"] == "30d"
    assert [p["plan"] for p in record["all_plans"]] == ["free"]


def test_codex_show_all_plans_opt_in_renders_one_row_per_plan(tmp_path, monkeypatch):
    # Interleaved free+team fixtures with show_all_plans explicitly opted in:
    # the record carries both plans, and the rendered row fans out to two
    # sub-rows (team+5h, free+30d) — the opt-in multi-plan path.
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    now = time.time()
    _install_codex_rollouts(
        tmp_path,
        [
            ("team", "codex_rollout_team_snapshot.jsonl", now - 3600),
            ("free", "codex_rollout_token_count_30d.jsonl", now - 60),
        ],
    )

    record = providers.get_codex_usage({"external_providers": {"codex": {"show_all_plans": True}}})

    assert [p["plan"] for p in record["all_plans"]] == ["team", "free"]

    row = providers.format_provider_row_parts(record, now, label_width=5)
    sub_texts = [sub["text"] for sub in row["sub_rows"]]
    assert len(sub_texts) == 2
    assert "team" in sub_texts[0] and "5h" in sub_texts[0]
    assert "free" in sub_texts[1] and "30d" in sub_texts[1]


def test_codex_all_plans_renders_one_row_per_plan(tmp_path, monkeypatch):
    # Engine-level seam: format_provider_row_parts on a record carrying all_plans
    # of 2 yields two rendered rows (sub_rows) — team (5h) then free (30d).
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    team = providers.parse_codex_token_count_line(
        (FIXTURES / "codex_rollout_team_snapshot.jsonl").read_text(encoding="utf-8").strip()
    )
    free = providers.parse_codex_token_count_line(
        (FIXTURES / "codex_rollout_token_count_30d.jsonl").read_text(encoding="utf-8").strip()
    )
    record = dict(team)
    record["all_plans"] = [team, free]

    row = providers.format_provider_row_parts(record, 1_000, label_width=5)
    texts = [sub["text"] for sub in row["sub_rows"]]
    assert len(texts) == 2
    assert "team" in texts[0] and "5h" in texts[0]
    assert "free" in texts[1] and "30d" in texts[1]
    # Absent all_plans still renders the single record as one row (old caches).
    single = providers.format_provider_row_parts(team, 1_000, label_width=5)
    assert single.get("sub_rows") is None
    assert "team" in single["text"] and "5h" in single["text"]


def test_codex_only_free_selected_unchanged(tmp_path, monkeypatch):
    # Single free account present: default config keeps selecting it (newest overall).
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    now = time.time()
    _install_codex_rollouts(
        tmp_path,
        [("free", "codex_rollout_token_count_30d.jsonl", now - 120)],
    )

    record = providers.get_codex_usage({})

    assert record["plan"] == "free"
    assert record["five_hour"]["used_pct"] == 6
    assert record["five_hour"]["label"] == "30d"
    assert record["weekly"] is None


def test_heal_codex_record_zeroes_an_elapsed_window():
    # Direct unit test of the healing helper: an elapsed five_hour window (its
    # resets_at is in the past) is provably reset — no newer rollout for this
    # plan exists, so recorded usage since the reset is zero. The still-future
    # weekly window is untouched.
    now = 1_000_000
    record = {
        "provider": "codex",
        "available": True,
        "five_hour": {"used_pct": 100, "resets_at": now - 100, "label": "5h"},
        "weekly": {"used_pct": 84, "resets_at": now + 500_000, "label": "7d"},
        "plan": "team",
    }

    healed = providers._heal_codex_record(record, now)

    assert healed["five_hour"] == {"used_pct": 0.0, "resets_at": None, "label": "5h"}
    assert healed["weekly"] == {"used_pct": 84, "resets_at": now + 500_000, "label": "7d"}
    # The helper does not mutate its input.
    assert record["five_hour"]["used_pct"] == 100


def test_codex_get_usage_heals_an_elapsed_five_hour_window(tmp_path, monkeypatch):
    # End-to-end (fresh build, no cache yet): the team snapshot's 5h window
    # reset long ago (resets_at 1700000000). Absent any newer team rollout,
    # get_codex_usage must render 0% instead of the frozen 100% snapshot.
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    now = time.time()
    _install_codex_rollouts(
        tmp_path,
        [("team", "codex_rollout_team_elapsed.jsonl", now - 60)],
    )

    record = providers.get_codex_usage({})

    assert record["plan"] == "team"
    assert record["five_hour"] == {"used_pct": 0.0, "resets_at": None, "label": "5h"}
    assert record["weekly"]["used_pct"] == 84
    assert record["weekly"]["resets_at"] == 4102444800
    assert record["weekly"]["label"] == "7d"


def test_codex_get_usage_heals_a_cache_hit(tmp_path, monkeypatch):
    # A cache written while the window still looked hot (or written by an older
    # binary, pre-healing) must still render healed when read back within TTL:
    # the elapsed-window proof depends on wall-clock time at READ time, not at
    # write time.
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    cache_dir = tmp_path / ".claude"
    cache_dir.mkdir(parents=True)
    (cache_dir / "statusline-usage-codex.json").write_text(
        json.dumps(
            {
                "cached_at": time.time(),
                "record": {
                    "provider": "codex",
                    "label": "Codex",
                    "available": True,
                    "five_hour": {"used_pct": 100, "resets_at": 1700000000, "label": "5h"},
                    "weekly": {"used_pct": 84, "resets_at": 4102444800, "label": "7d"},
                    "plan": "team",
                    "tokens": None,
                    "stale_seconds": 0,
                },
            }
        ),
        encoding="utf-8",
    )

    record = providers.get_codex_usage({})

    assert record["five_hour"] == {"used_pct": 0.0, "resets_at": None, "label": "5h"}
    assert record["weekly"]["used_pct"] == 84
    assert record["weekly"]["resets_at"] == 4102444800


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


def test_antigravity_cli_snapshot_groups_current_lineup_into_two_pools():
    """Real `antigravity-usage quota --json` shape: 8 models across the current
    Gemini/Claude/GPT-OSS lineup. Antigravity's real quota structure is TWO
    pools ("Gemini Models" and "Claude and GPT models") that each share ONE
    5-hour + weekly limit — Opus/Sonnet/GPT are NOT independent pools. Within a
    pool, used_pct is the MAX (most-constrained) member, and resets_at picks
    the earliest resetTime among members tied on that max.
    """
    snapshot = json.loads((FIXTURES / "antigravity_quota_response.json").read_text(encoding="utf-8"))

    metrics = providers._map_antigravity_snapshot(snapshot)

    assert [(metric["label"], metric["used_pct"]) for metric in metrics] == [
        ("Gemini", 60),
        ("Claude+GPT", 90),
    ]
    # Gemini's max (60%) is tied between "Flash (High)" and "Pro (High)"; the
    # earlier of their two resetTimes wins ("Pro (High)" resets at noon UTC).
    # Claude+GPT's max (90%) is "Claude Opus 4.6 (Thinking)" alone, no tie.
    assert [metric["resets_at"] for metric in metrics] == [1783598400, 1783627200]

    record = providers.unavailable("antigravity")
    record.update({"available": True, "label": "AGY", "display": "compact", "metrics": metrics})
    row = providers.format_provider_row_parts(record, 1_000)
    for label, pct in (("Gemini", 60), ("Claude+GPT", 90)):
        assert f"{label} {pct}%" in row["text"]


def test_antigravity_cli_snapshot_skips_autocomplete_only_models():
    snapshot = {
        "models": [
            {
                "label": "Gemini 3.5 Flash (Autocomplete)",
                "modelId": "gemini-ac",
                "remainingPercentage": 0.1,
                "isAutocompleteOnly": True,
            },
            {"label": "Gemini 3.5 Flash (Low)", "modelId": "gemini-flash-low", "remainingPercentage": 0.7},
        ]
    }

    metrics = providers._map_antigravity_snapshot(snapshot)

    assert [(metric["label"], metric["used_pct"]) for metric in metrics] == [("Gemini", 30)]


def test_antigravity_cli_snapshot_old_lineup_lands_in_gemini_pool():
    """Backward compatibility: if the CLI ever reverts to the old bare
    Flash/Pro labels (no "Gemini" prefix), the flash/pro keyword match must
    still route them into the Gemini pool instead of a spurious own pool."""
    snapshot = {
        "models": [
            {"label": "Flash", "modelId": "flash", "remainingPercentage": 0.8},
            {"label": "Pro", "modelId": "pro", "remainingPercentage": 0.6},
        ]
    }

    metrics = providers._map_antigravity_snapshot(snapshot)

    assert [(metric["label"], metric["used_pct"]) for metric in metrics] == [("Gemini", 40)]


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


def _write_glm_cache(home, age_seconds=0, auth_style=None):
    claude_dir = home / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    response = json.loads((FIXTURES / "glm_quota_response.json").read_text(encoding="utf-8"))
    payload = {"cached_at": time.time(), "response": response}
    if auth_style:
        payload["auth_style"] = auth_style
    cache = claude_dir / "statusline-usage-glm.json"
    cache.write_text(json.dumps(payload), encoding="utf-8")
    mtime = time.time() - age_seconds
    os.utime(cache, (mtime, mtime))
    return cache


class _HttpResponse:
    status = 200

    def __init__(self, data):
        self.data = data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.data).encode("utf-8")


def test_glm_fetch_retries_bearer_after_raw_401(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    response = json.loads((FIXTURES / "glm_quota_response.json").read_text(encoding="utf-8"))
    auth_headers = []

    def fake_urlopen(req, timeout):
        auth_headers.append(req.get_header("Authorization"))
        if len(auth_headers) == 1:
            raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, None)
        return _HttpResponse(response)

    monkeypatch.setattr(providers.urllib.request, "urlopen", fake_urlopen)

    data = providers._fetch_glm_response({"base_url": "https://api.z.ai"}, "KEY-PLACEHOLDER")

    assert data == response
    assert auth_headers == ["KEY-PLACEHOLDER", "Bearer KEY-PLACEHOLDER"]
    assert providers._GLM_LAST_AUTH_STYLE == "bearer"


def test_refresh_glm_cache_persists_successful_auth_style(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.setattr(providers, "_keychain_glm_key", lambda: "")
    monkeypatch.delenv("ZAI_API_KEY", raising=False)
    monkeypatch.delenv("ZHIPU_API_KEY", raising=False)
    response = json.loads((FIXTURES / "glm_quota_response.json").read_text(encoding="utf-8"))
    auth_headers = []

    def fake_urlopen(req, timeout):
        auth_headers.append(req.get_header("Authorization"))
        if len(auth_headers) == 1:
            raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, None)
        return _HttpResponse(response)

    monkeypatch.setattr(providers.urllib.request, "urlopen", fake_urlopen)

    assert providers.refresh_glm_cache({"api_key": "KEY-PLACEHOLDER"}) is True

    cache = json.loads((tmp_path / ".claude" / "statusline-usage-glm.json").read_text(encoding="utf-8"))
    assert auth_headers == ["KEY-PLACEHOLDER", "Bearer KEY-PLACEHOLDER"]
    assert cache["auth_style"] == "bearer"
    assert cache["response"] == response


def test_glm_fetch_uses_remembered_bearer_style_first(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    _write_glm_cache(tmp_path, auth_style="bearer")
    response = json.loads((FIXTURES / "glm_quota_response.json").read_text(encoding="utf-8"))
    auth_headers = []

    def fake_urlopen(req, timeout):
        auth_headers.append(req.get_header("Authorization"))
        return _HttpResponse(response)

    monkeypatch.setattr(providers.urllib.request, "urlopen", fake_urlopen)

    data = providers._fetch_glm_response({}, "KEY-PLACEHOLDER")

    assert data == response
    assert auth_headers == ["Bearer KEY-PLACEHOLDER"]


def test_glm_reads_stale_cache_and_spawns_refresh_without_blocking(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    _write_glm_cache(tmp_path, age_seconds=3600, auth_style="raw")
    popens = []

    def fail_fetch(*_args, **_kwargs):
        raise AssertionError("render path must not fetch GLM synchronously")

    class _Popen:
        def __init__(self, cmd, **kwargs):
            popens.append((cmd, kwargs))

    monkeypatch.setattr(providers, "_fetch_glm_response", fail_fetch)
    monkeypatch.setattr(providers.subprocess, "Popen", _Popen)

    record = providers.get_glm_usage({"base_url": "https://api.z.ai", "api_key": "KEY-PLACEHOLDER"})

    assert popens
    cmd, kwargs = popens[0]
    assert cmd[:2] == ["python3", "-c"]
    assert "refresh_" in cmd[2]
    assert "CLAUDE_STATUSLINE_REFRESH_CONFIG" in kwargs["env"]
    assert kwargs["env"]["HOME"] == str(tmp_path)
    assert json.loads(kwargs["env"]["CLAUDE_STATUSLINE_REFRESH_CONFIG"]) == {"base_url": "https://api.z.ai"}
    assert kwargs["stdout"] is providers.subprocess.DEVNULL
    assert kwargs["stderr"] is providers.subprocess.DEVNULL
    assert kwargs["stdin"] is providers.subprocess.DEVNULL
    assert kwargs["start_new_session"] is True
    assert record["provider"] == "glm"
    assert record["available"] is True
    assert record["weekly"]["label"] == "tok"
    assert record["stale_seconds"] >= 300


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
