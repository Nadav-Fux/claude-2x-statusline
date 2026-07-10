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


# ── Live `codex app-server` refresh (Phase 2) ────────────────────────────────


def _codex_app_server_results(plan="team", primary_pct=10, secondary_pct=2, now=None):
    """Canned account/read + account/rateLimits/read results shaped like the real
    app-server protocol (usedPercent / windowDurationMins / resetsAt)."""
    now = int(now if now is not None else time.time())
    account = {
        "account": {"type": "chatgpt", "email": "redacted@example.com", "planType": plan},
        "requiresOpenaiAuth": True,
    }
    snapshot = {
        "limitId": "codex",
        "limitName": None,
        "primary": {"usedPercent": primary_pct, "windowDurationMins": 300, "resetsAt": now + 3600},
        "secondary": {"usedPercent": secondary_pct, "windowDurationMins": 10080, "resetsAt": now + 7 * 86400},
        "planType": plan,
    }
    rate = {"rateLimits": dict(snapshot), "rateLimitsByLimitId": {"codex": dict(snapshot)}}
    return account, rate


def _write_codex_live_cache(home, record, age_seconds=0):
    cache_dir = home / ".claude"
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / "statusline-usage-codex.json"
    path.write_text(json.dumps({"cached_at": time.time(), "record": record}), encoding="utf-8")
    if age_seconds:
        stamp = time.time() - age_seconds
        os.utime(path, (stamp, stamp))
    return path


def test_normalize_codex_rate_limits_maps_app_server_snapshot():
    now = 1783654055
    account, rate = _codex_app_server_results(plan="team", primary_pct=10, secondary_pct=2, now=now)

    record = providers.normalize_codex_rate_limits(account, rate, stale_seconds=0)

    assert record["available"] is True
    assert record["source"] == "app-server"
    assert record["plan"] == "team"
    assert record["five_hour"]["used_pct"] == 10
    assert record["five_hour"]["label"] == "5h"
    assert record["five_hour"]["resets_at"] == now + 3600
    assert record["weekly"]["used_pct"] == 2
    assert record["weekly"]["label"] == "7d"
    assert record["weekly"]["resets_at"] == now + 7 * 86400
    assert record["stale_seconds"] == 0


def test_refresh_codex_cache_writes_live_record(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    account, rate = _codex_app_server_results(plan="team", primary_pct=10, secondary_pct=2)
    monkeypatch.setattr(providers, "_codex_app_server_exchange", lambda *a, **k: (account, rate))

    assert providers.refresh_codex_cache({}) is True

    data = json.loads((tmp_path / ".claude" / "statusline-usage-codex.json").read_text(encoding="utf-8"))
    record = data["record"]
    assert record["source"] == "app-server"
    assert record["available"] is True
    assert record["plan"] == "team"
    assert record["five_hour"]["used_pct"] == 10
    assert record["weekly"]["used_pct"] == 2


def test_codex_app_server_exchange_speaks_jsonrpc(tmp_path, monkeypatch):
    # Exercises the real protocol framing against a faked subprocess: initialize
    # request, initialized notification, then account/read + rateLimits reads.
    now = int(time.time())
    responses = [
        json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"userAgent": "x", "codexHome": str(tmp_path)}}),
        json.dumps({"jsonrpc": "2.0", "id": 2, "result": {"account": {"type": "chatgpt", "planType": "team"}}}),
        json.dumps({"jsonrpc": "2.0", "id": 3, "result": {"rateLimits": {
            "limitId": "codex",
            "primary": {"usedPercent": 10, "windowDurationMins": 300, "resetsAt": now + 3600},
            "secondary": {"usedPercent": 2, "windowDurationMins": 10080, "resetsAt": now + 7 * 86400},
            "planType": "team",
        }}}),
    ]

    class _FakeStdin:
        def __init__(self):
            self.closed = False
            self.writes = []

        def write(self, s):
            self.writes.append(s)

        def flush(self):
            pass

        def close(self):
            self.closed = True

    instances = []

    class _FakePopen:
        def __init__(self, *args, **kwargs):
            self.pid = None
            self.stdin = _FakeStdin()
            self.stdout = iter(responses)
            self._alive = True
            instances.append(self)

        def poll(self):
            return None if self._alive else 0

        def kill(self):
            self._alive = False

        def wait(self, timeout=None):
            self._alive = False
            return 0

    monkeypatch.setattr(providers.subprocess, "Popen", _FakePopen)

    account, rate = providers._codex_app_server_exchange("codex", timeout=5)

    assert account["account"]["planType"] == "team"
    record = providers.normalize_codex_rate_limits(account, rate)
    assert record["available"] is True
    assert record["source"] == "app-server"
    assert record["five_hour"]["used_pct"] == 10
    assert record["weekly"]["used_pct"] == 2

    sent = "".join(instances[0].stdin.writes)
    assert '"method": "initialize"' in sent
    assert '"method": "initialized"' in sent
    assert '"method": "account/rateLimits/read"' in sent
    # Every frame is newline-delimited (no Content-Length framing).
    assert instances[0].stdin.writes[0].endswith("\n")


def test_codex_get_usage_prefers_fresh_live_cache_over_rollouts(tmp_path, monkeypatch):
    # A frozen rollout on disk says 100% used, but a fresh live snapshot says 10%.
    # The render path must prefer the live truth.
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.setattr(providers, "_spawn_provider_refresh", lambda *a, **k: None)
    now = time.time()
    _install_codex_rollouts(tmp_path, [("team", "codex_rollout_team_snapshot.jsonl", now - 60)])
    account, rate = _codex_app_server_results(plan="team", primary_pct=10, secondary_pct=2, now=now)
    live = providers.normalize_codex_rate_limits(account, rate, stale_seconds=0)
    _write_codex_live_cache(tmp_path, live, age_seconds=5)

    record = providers.get_codex_usage({})

    assert record["source"] == "app-server"
    assert record["five_hour"]["used_pct"] == 10
    assert record["weekly"]["used_pct"] == 2
    assert record["stale_seconds"] == 5


def test_codex_stale_live_cache_renders_and_spawns_refresh(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    spawns = []
    monkeypatch.setattr(providers, "_spawn_provider_refresh", lambda provider, config: spawns.append(provider))
    now = time.time()
    account, rate = _codex_app_server_results(plan="team", primary_pct=10, secondary_pct=2, now=now)
    live = providers.normalize_codex_rate_limits(account, rate, stale_seconds=0)
    _write_codex_live_cache(tmp_path, live, age_seconds=200)  # > CODEX_LIVE_TTL

    record = providers.get_codex_usage({})

    assert record["source"] == "app-server"
    assert record["five_hour"]["used_pct"] == 10
    assert record["stale_seconds"] >= providers.CODEX_LIVE_TTL
    assert spawns == ["codex"]


def test_refresh_codex_cache_failure_falls_back_to_rollouts(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    # Broken protocol / offline: refresh writes nothing (never-clobber).
    monkeypatch.setattr(providers, "_codex_app_server_exchange", lambda *a, **k: (None, None))
    assert providers.refresh_codex_cache({}) is False
    assert not (tmp_path / ".claude" / "statusline-usage-codex.json").exists()

    # The render path still answers from the rollout scan exactly as today.
    monkeypatch.setattr(providers, "_spawn_provider_refresh", lambda *a, **k: None)
    now = time.time()
    _install_codex_rollouts(tmp_path, [("team", "codex_rollout_team_snapshot.jsonl", now - 60)])

    record = providers.get_codex_usage({})

    assert record["available"] is True
    assert record["plan"] == "team"
    assert record["source"] == "local-jsonl"


def test_refresh_codex_cache_never_clobbers_last_good_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    account, rate = _codex_app_server_results(plan="team", primary_pct=10, secondary_pct=2)
    good = providers.normalize_codex_rate_limits(account, rate, stale_seconds=0)
    path = _write_codex_live_cache(tmp_path, good)
    before = path.read_text(encoding="utf-8")

    # The next refresh fails mid-protocol: the last good cache must survive.
    monkeypatch.setattr(providers, "_codex_app_server_exchange", lambda *a, **k: (None, None))
    assert providers.refresh_codex_cache({}) is False

    assert path.read_text(encoding="utf-8") == before


def test_codex_live_pin_mismatch_falls_back_to_rollouts_without_clobber(tmp_path, monkeypatch):
    # Live account is TEAM, but the config pins FREE — a plan only the rollouts
    # know. Render from rollouts, keep the (still fresh) live snapshot intact, and
    # do not spawn a pointless live refresh for the mismatched pin.
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    spawns = []
    monkeypatch.setattr(providers, "_spawn_provider_refresh", lambda provider, config: spawns.append(provider))
    now = time.time()
    account, rate = _codex_app_server_results(plan="team", primary_pct=10, secondary_pct=2, now=now)
    live = providers.normalize_codex_rate_limits(account, rate, stale_seconds=0)
    live_path = _write_codex_live_cache(tmp_path, live, age_seconds=5)
    live_before = live_path.read_text(encoding="utf-8")
    _install_codex_rollouts(tmp_path, [("free", "codex_rollout_token_count_30d.jsonl", now - 60)])

    record = providers.get_codex_usage({"external_providers": {"codex": {"plan": "free"}}})

    assert record["plan"] == "free"
    assert record["source"] == "local-jsonl"
    assert live_path.read_text(encoding="utf-8") == live_before
    assert spawns == []


def test_spawn_codex_refresh_skips_when_logged_out(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.setattr(providers.shutil, "which", lambda *a, **k: "/usr/bin/codex")
    popens = []
    monkeypatch.setattr(providers.subprocess, "Popen", lambda *a, **k: popens.append((a, k)))

    # No ~/.codex/auth.json under the temp home -> no refresher is spawned.
    providers._spawn_provider_refresh("codex", {})

    assert popens == []


def test_spawn_codex_refresh_runs_when_logged_in(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    (tmp_path / ".codex").mkdir(parents=True)
    (tmp_path / ".codex" / "auth.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(providers.shutil, "which", lambda *a, **k: "/usr/bin/codex")
    popens = []

    class _Popen:
        def __init__(self, cmd, **kwargs):
            popens.append((cmd, kwargs))

    monkeypatch.setattr(providers.subprocess, "Popen", _Popen)

    providers._spawn_provider_refresh("codex", {})

    assert popens
    cmd, kwargs = popens[0]
    assert cmd[:2] == ["python3", "-c"]
    assert "refresh_codex_cache" in cmd[2]
    assert kwargs["start_new_session"] is True
    assert json.loads(kwargs["env"]["CLAUDE_STATUSLINE_REFRESH_CONFIG"]) == {}


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


# ── Antigravity quota-summary (two pools × 5h+weekly) ─────────────────────────

def _quota_summary_fixture():
    return json.loads((FIXTURES / "antigravity_quota_summary.json").read_text(encoding="utf-8"))


def _assert_two_pool_summary(pools):
    assert [p["plan"] for p in pools] == ["gemini", "claude+gpt"]
    gemini, claude_gpt = pools
    # remainingFraction -> used%: 1.0->0, 0.97->3, 0.78->22
    assert gemini["five_hour"]["used_pct"] == 0 and gemini["five_hour"]["label"] == "5h"
    assert gemini["weekly"]["used_pct"] == 3 and gemini["weekly"]["label"] == "wk"
    assert claude_gpt["five_hour"]["used_pct"] == 0
    assert claude_gpt["weekly"]["used_pct"] == 22
    # Reset times parsed to epoch seconds from the ISO strings.
    assert gemini["five_hour"]["resets_at"] == 1783713600      # 2026-07-10T20:00Z
    assert gemini["weekly"]["resets_at"] == 1784145600         # 2026-07-15T20:00Z
    assert claude_gpt["five_hour"]["resets_at"] == 1783706400  # 2026-07-10T18:00Z
    assert claude_gpt["weekly"]["resets_at"] == 1783983600     # 2026-07-13T23:00Z
    for pool in pools:
        assert pool["label"] == "AGY" and pool["display"] == "bars"
        assert pool["source"] == "quota-summary"


def test_antigravity_quota_summary_maps_bare_form_into_two_pools():
    pools = providers._map_antigravity_quota_summary(_quota_summary_fixture())
    _assert_two_pool_summary(pools)


def test_antigravity_quota_summary_maps_wrapped_form_into_two_pools():
    # The local language-server route wraps the payload under ``response``.
    wrapped = {"response": _quota_summary_fixture()}
    pools = providers._map_antigravity_quota_summary(wrapped)
    _assert_two_pool_summary(pools)


def test_antigravity_quota_summary_top_level_mirrors_worst_pool():
    pools = providers._map_antigravity_quota_summary(_quota_summary_fixture())
    record = providers._compose_antigravity_quota_record(pools)
    # Worst pool = highest max-used across its windows: claude+gpt (22%) > gemini (3%).
    assert record["plan"] == "claude+gpt"
    assert record["weekly"]["used_pct"] == 22
    assert record["source"] == "quota-summary"
    assert [p["plan"] for p in record["all_plans"]] == ["gemini", "claude+gpt"]


def test_antigravity_quota_summary_renders_one_row_per_pool_with_both_windows():
    pools = providers._map_antigravity_quota_summary(_quota_summary_fixture())
    record = providers._compose_antigravity_quota_record(pools)

    def clock(_epoch, style):
        return "8:00pm" if style == "time" else "15/7 8:00pm"

    row = providers.format_provider_row_parts(record, 1_000, format_clock=clock)
    lines = row["text"].splitlines()
    assert len(lines) == 2
    gemini_line, claude_line = lines

    assert gemini_line.startswith("AGY gemini")
    assert "5h" in gemini_line and "wk" in gemini_line
    assert "  0%" in gemini_line and "  3%" in gemini_line
    # Both pool rows carry bar glyphs (bars display, not compact).
    assert "▱" in gemini_line

    assert claude_line.startswith("AGY claude+gpt")
    assert " 22%" in claude_line
    assert "▰" in claude_line  # 22% weekly has at least two filled cells


def test_antigravity_quota_summary_partial_buckets_still_map():
    # Only the gemini pool reports; the claude+gpt pool is absent entirely.
    summary = {
        "groups": [
            {
                "buckets": [
                    {"bucketId": "gemini-5h", "remainingFraction": 0.5, "resetTime": "2026-07-10T20:00:00Z"},
                    {"bucketId": "gemini-weekly", "remainingFraction": 0.9, "resetTime": "2026-07-15T20:00:00Z"},
                ]
            }
        ]
    }
    pools = providers._map_antigravity_quota_summary(summary)
    assert [p["plan"] for p in pools] == ["gemini"]
    assert pools[0]["five_hour"]["used_pct"] == 50
    assert pools[0]["weekly"]["used_pct"] == 10


def test_antigravity_quota_summary_ignores_unknown_buckets():
    summary = {"groups": [{"buckets": [{"bucketId": "mystery-5h", "remainingFraction": 0.5}]}]}
    assert providers._map_antigravity_quota_summary(summary) is None


def test_refresh_antigravity_cache_writes_two_pool_record(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    summary = providers._map_antigravity_quota_summary(_quota_summary_fixture())
    # Local route succeeds; cloud route must not be reached.
    monkeypatch.setattr(providers, "_antigravity_local_summary", lambda deadline: summary)
    monkeypatch.setattr(
        providers,
        "_antigravity_cloud_summary",
        lambda deadline: (_ for _ in ()).throw(AssertionError("cloud route must not run")),
    )

    assert providers.refresh_antigravity_cache({}) is True

    cache = json.loads((tmp_path / ".claude" / "statusline-usage-antigravity.json").read_text(encoding="utf-8"))
    record = cache["record"]
    assert record["available"] is True
    assert record["source"] == "quota-summary"
    assert [p["plan"] for p in record["all_plans"]] == ["gemini", "claude+gpt"]


def test_refresh_antigravity_cache_falls_back_to_cloud(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    summary = providers._map_antigravity_quota_summary(_quota_summary_fixture())
    monkeypatch.setattr(providers, "_antigravity_local_summary", lambda deadline: None)
    monkeypatch.setattr(providers, "_antigravity_cloud_summary", lambda deadline: summary)

    assert providers.refresh_antigravity_cache({}) is True
    cache = json.loads((tmp_path / ".claude" / "statusline-usage-antigravity.json").read_text(encoding="utf-8"))
    assert cache["record"]["source"] == "quota-summary"


def test_refresh_antigravity_cache_never_clobbers_on_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    prior = {"cached_at": 123.0, "record": {"provider": "antigravity", "available": True, "sentinel": "keep-me"}}
    cache_path = claude_dir / "statusline-usage-antigravity.json"
    cache_path.write_text(json.dumps(prior), encoding="utf-8")

    # Both transports fail — refresh must leave the prior cache byte-for-byte intact.
    monkeypatch.setattr(providers, "_antigravity_local_summary", lambda deadline: None)
    monkeypatch.setattr(providers, "_antigravity_cloud_summary", lambda deadline: None)

    assert providers.refresh_antigravity_cache({}) is False
    assert json.loads(cache_path.read_text(encoding="utf-8")) == prior


def test_get_antigravity_usage_prefers_fresh_quota_summary_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.setattr(providers, "_spawn_provider_refresh", lambda provider, config: None)
    # If the CLI path were reached it would raise; a fresh quota-summary must win.
    monkeypatch.setattr(
        providers,
        "_antigravity_cli_usage",
        lambda config: (_ for _ in ()).throw(AssertionError("CLI fallback must not run")),
    )
    pools = providers._map_antigravity_quota_summary(_quota_summary_fixture())
    record = providers._compose_antigravity_quota_record(pools)
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    (claude_dir / "statusline-usage-antigravity.json").write_text(
        json.dumps({"cached_at": time.time(), "record": record}), encoding="utf-8"
    )

    out = providers.get_antigravity_usage({})
    assert out["source"] == "quota-summary"
    assert [p["plan"] for p in out["all_plans"]] == ["gemini", "claude+gpt"]


def test_get_antigravity_usage_falls_back_to_cli_without_quota_summary(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    spawned = []
    monkeypatch.setattr(providers, "_spawn_provider_refresh", lambda provider, config: spawned.append(provider))
    snapshot = json.loads((FIXTURES / "antigravity_quota_response.json").read_text(encoding="utf-8"))

    def fake_run(cmd, capture_output, text, timeout):
        class _P:
            stdout = json.dumps(snapshot)
        return _P()

    monkeypatch.setattr(providers.subprocess, "run", fake_run)

    out = providers.get_antigravity_usage({})
    # No quota-summary cache -> current 5h-only compact behavior is unchanged.
    assert out["available"] is True
    assert out["display"] == "compact"
    assert out["source"] == "api"
    assert [m["label"] for m in out["metrics"]] == ["Gemini", "Claude+GPT"]
    # A background quota-summary refresh was still kicked off for next time.
    assert "antigravity" in spawned


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
