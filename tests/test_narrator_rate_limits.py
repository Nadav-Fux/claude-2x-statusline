"""Narrator rate-limit source tests."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import narrator.observations as observations
from narrator.observations import Observation
from narrator.scoring import _build_insights


# A fixed "now" the cycle-aware tests anchor against. resets_at values below are
# expressed as offsets from this instant so the day-in-cycle math is explicit.
_NOW_EPOCH = 1_780_000_000.0  # 2026-05-28 ~ (arbitrary fixed instant)
_NOW_DT = datetime.fromtimestamp(_NOW_EPOCH, tz=timezone.utc)


def _empty_memory() -> dict:
    return {"current": {"delivered_narratives": []}}


def _obs(**kwargs) -> Observation:
    o = Observation()
    for k, v in kwargs.items():
        setattr(o, k, v)
    return o


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


# ---------------------------------------------------------------------------
# Step 1 — reset times parsed into the Observation
# ---------------------------------------------------------------------------

def _write_usage_cache(claude_dir: Path, *, five=None, seven=None) -> None:
    payload = {}
    if five is not None:
        payload["five_hour"] = five
    if seven is not None:
        payload["seven_day"] = seven
    (claude_dir / "statusline-usage-cache.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


def _build_with_cache(tmp_path, monkeypatch, *, five=None, seven=None, now=_NOW_EPOCH):
    fake_home = tmp_path / "home"
    claude_dir = fake_home / ".claude"
    claude_dir.mkdir(parents=True)
    _write_usage_cache(claude_dir, five=five, seven=seven)

    monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))
    monkeypatch.setattr(observations, "_is_peak_hours", lambda: False)
    monkeypatch.setattr(observations, "_load_statusline_state", lambda: {"samples": []})
    monkeypatch.setattr(observations, "_read_stdin_json", lambda: None)
    # Same "now" source the rest of build() uses — keeps hours_left deterministic.
    monkeypatch.setattr(observations.time, "time", lambda: now)
    return observations.build({"current": {}})


def test_parse_reset_at_handles_z_suffix_and_offset():
    """Both 'Z' and explicit-offset ISO timestamps parse to a tz-aware datetime."""
    z = observations._parse_reset_at({"resets_at": "2026-06-11T12:00:00Z"})
    off = observations._parse_reset_at({"resets_at": "2026-06-11T12:00:00+00:00"})
    assert z == off
    assert z is not None and z.tzinfo is not None


def test_parse_reset_at_returns_none_on_bad_input():
    assert observations._parse_reset_at(None) is None
    assert observations._parse_reset_at({}) is None
    assert observations._parse_reset_at({"resets_at": "null"}) is None
    assert observations._parse_reset_at({"resets_at": "not-a-date"}) is None
    assert observations._parse_reset_at({"resets_at": 12345}) is None


def test_build_populates_reset_times_and_hours_left(tmp_path, monkeypatch):
    """build() exposes parsed reset datetimes and 7d hours-left vs the same now."""
    # 7-day window resets in exactly 48h; 5h window resets in 3h.
    seven_reset = datetime.fromtimestamp(_NOW_EPOCH + 48 * 3600, tz=timezone.utc)
    five_reset = datetime.fromtimestamp(_NOW_EPOCH + 3 * 3600, tz=timezone.utc)
    obs = _build_with_cache(
        tmp_path, monkeypatch,
        five={"utilization": 20.0, "resets_at": five_reset.isoformat()},
        seven={"utilization": 30.0, "resets_at": seven_reset.isoformat()},
    )
    assert obs.rate_limit_7d_resets_at is not None
    assert obs.rate_limit_5h_resets_at is not None
    assert abs(obs.rate_limit_7d_hours_left - 48.0) < 0.01


def test_build_hours_left_none_when_no_reset_data(tmp_path, monkeypatch):
    obs = _build_with_cache(
        tmp_path, monkeypatch,
        seven={"utilization": 85.0},  # no resets_at
    )
    assert obs.rate_limit_7d_resets_at is None
    assert obs.rate_limit_7d_hours_left is None


def test_build_hours_left_clamped_to_zero_for_past_reset(tmp_path, monkeypatch):
    past = datetime.fromtimestamp(_NOW_EPOCH - 3600, tz=timezone.utc)
    obs = _build_with_cache(
        tmp_path, monkeypatch,
        seven={"utilization": 50.0, "resets_at": past.isoformat()},
    )
    assert obs.rate_limit_7d_hours_left == 0.0


# ---------------------------------------------------------------------------
# Step 2 — cycle-aware rate-limit tiers in scoring._build_insights
# ---------------------------------------------------------------------------

def _keys(insights):
    return [i.template_key for i in insights]


def test_tier_a_high_pct_early_in_cycle_fires_ahead_of_pace():
    """(a) High 7d% with most of the week left → AHEAD/negative template fires."""
    # 6 days left of 7 → elapsed ~14%, even pace ~14%. 60% used >> pace → ahead.
    obs = _obs(rate_limit_5h_pct=20.0, rate_limit_7d_pct=60.0,
               rate_limit_7d_hours_left=6 * 24.0)
    insights = _build_insights(obs, _empty_memory())
    keys = _keys(insights)
    assert "rate_limit_ahead_of_pace" in keys
    assert "rate_limit_high" not in keys
    ahead = next(i for i in insights if i.template_key == "rate_limit_ahead_of_pace")
    assert ahead.urgency == 7  # firm, not alarmist
    assert "ahead of an even" in ahead.text
    assert ahead.text_he  # Hebrew present


def test_ahead_fires_on_any_day_not_just_early():
    """Generalised AHEAD: hot vs even pace fires mid-cycle too (e.g. day 5)."""
    # 2 days left of 7 → elapsed ~71%, pace ~71%. 90% used >> pace → ahead by ~19.
    obs = _obs(rate_limit_5h_pct=10.0, rate_limit_7d_pct=90.0,
               rate_limit_7d_hours_left=2 * 24.0)
    insights = _build_insights(obs, _empty_memory())
    keys = _keys(insights)
    # 90% < 90 cap? no — 90 >= 90 → NEAR CAP wins. Use 88 to isolate AHEAD.
    obs2 = _obs(rate_limit_5h_pct=10.0, rate_limit_7d_pct=88.0,
                rate_limit_7d_hours_left=2 * 24.0)
    keys2 = _keys(_build_insights(obs2, _empty_memory()))
    assert "rate_limit_ahead_of_pace" in keys2
    assert "rate_limit_high" not in keys2


def test_tier_b_lowish_pct_last_day_fires_headroom():
    """(b) Lowish 7d% on the last day → HEADROOM :) encourage variant fires."""
    # 12h left → days_left=0.5 (<=1). 40% used; pace ~93 so (pace-pct7)>=12.
    obs = _obs(rate_limit_5h_pct=10.0, rate_limit_7d_pct=40.0,
               rate_limit_7d_hours_left=12.0)
    insights = _build_insights(obs, _empty_memory())
    keys = _keys(insights)
    assert "rate_limit_headroom_near_reset" in keys
    assert "rate_limit_ahead_of_pace" not in keys
    head = next(i for i in insights if i.template_key == "rate_limit_headroom_near_reset")
    assert head.urgency == 3  # gentle/encouraging
    assert "resets in" in head.text and "before it resets" in head.text  # last-day variant
    assert ":)" in head.text_he
    assert head.text_he


def test_behind_fires_on_general_day_with_calm_phrasing():
    """BEHIND on a non-last day → calm general phrasing (not the :) last-day one)."""
    # 5 days left → elapsed ~29%, pace ~29%. 10% used → behind by ~19, lots of headroom.
    obs = _obs(rate_limit_5h_pct=10.0, rate_limit_7d_pct=10.0,
               rate_limit_7d_hours_left=5 * 24.0)
    insights = _build_insights(obs, _empty_memory())
    keys = _keys(insights)
    assert "rate_limit_headroom_near_reset" in keys
    head = next(i for i in insights if i.template_key == "rate_limit_headroom_near_reset")
    assert head.urgency == 3
    assert "under an even weekly pace" in head.text  # general (non-last-day) phrasing
    assert "before it resets" not in head.text  # NOT the last-day variant
    assert head.text_he


def test_on_pace_fires_when_near_the_line():
    """ON-PACE: utilisation hugging the even line → neutral low-urgency cue."""
    # 3.5 days left → elapsed 50%, pace 50%. 45% used → abs(45-50)=5 < 12, pct7>=20.
    obs = _obs(rate_limit_5h_pct=10.0, rate_limit_7d_pct=45.0,
               rate_limit_7d_hours_left=3.5 * 24.0)
    insights = _build_insights(obs, _empty_memory())
    keys = _keys(insights)
    assert "rate_limit_on_pace" in keys
    assert "rate_limit_ahead_of_pace" not in keys
    assert "rate_limit_headroom_near_reset" not in keys
    onp = next(i for i in insights if i.template_key == "rate_limit_on_pace")
    assert onp.urgency == 2  # lowest
    assert "on an even weekly pace" in onp.text
    assert onp.text_he


def test_on_pace_does_not_fire_when_too_early_low_pct():
    """ON-PACE needs pct7>=20 — a quiet early week stays silent (no nag)."""
    # 6 days left → pace ~14. 10% used: abs(10-14)=4<12 but pct7<20 → no on-pace.
    obs = _obs(rate_limit_5h_pct=10.0, rate_limit_7d_pct=10.0,
               rate_limit_7d_hours_left=6 * 24.0)
    insights = _build_insights(obs, _empty_memory())
    rl_keys = [k for k in _keys(insights) if k.startswith("rate_limit")]
    assert rl_keys == []


def test_tier_c_near_cap_fires_regardless_of_cycle():
    """(c) >=90% on the weekly window → NEAR CAP fires even mid-cycle."""
    obs = _obs(rate_limit_5h_pct=30.0, rate_limit_7d_pct=92.0,
               rate_limit_7d_hours_left=3 * 24.0)
    insights = _build_insights(obs, _empty_memory())
    keys = _keys(insights)
    assert "rate_limit_high" in keys
    assert "rate_limit_ahead_of_pace" not in keys
    high = next(i for i in insights if i.template_key == "rate_limit_high")
    assert high.urgency == 10


def test_tier_d_missing_reset_data_falls_back_to_old_behaviour():
    """(d) No resets_at → graceful fallback to the old >80% near-cap behaviour."""
    obs = _obs(rate_limit_5h_pct=85.0, rate_limit_7d_pct=10.0,
               rate_limit_7d_hours_left=None)
    insights = _build_insights(obs, _empty_memory())
    keys = _keys(insights)
    assert "rate_limit_high" in keys
    # No cycle-aware tier can fire without reset data.
    assert "rate_limit_ahead_of_pace" not in keys
    assert "rate_limit_headroom_near_reset" not in keys


def test_5h_rolling_tier_fires_when_no_weekly_tier_speaks():
    """5h window hot (but <90), weekly window in the dead-band → 5h rolling tier.

    pct5=88 is >85 (Tier 4) yet keeps max_rl<90 so near-cap stays quiet. The
    weekly window sits in the 12–15 'slightly ahead' dead-band (ahead<15, not
    on-pace, not behind), so no weekly tier speaks and the 5h tier surfaces.
    """
    # 3 days left → pace ~57%. pct7=70 → ahead by ~13 (>=12 so not on-pace,
    # <15 so not AHEAD; not behind). No weekly tier fires.
    obs = _obs(rate_limit_5h_pct=88.0, rate_limit_7d_pct=70.0,
               rate_limit_7d_hours_left=3 * 24.0)
    insights = _build_insights(obs, _empty_memory())
    keys = _keys(insights)
    assert "rate_limit_5h_rolling" in keys
    assert "rate_limit_high" not in keys
    assert "rate_limit_ahead_of_pace" not in keys
    assert "rate_limit_on_pace" not in keys
    assert "rate_limit_headroom_near_reset" not in keys
    roll = next(i for i in insights if i.template_key == "rate_limit_5h_rolling")
    assert roll.urgency == 9
    assert "5-hour rolling" in roll.text


def test_tiers_are_mutually_exclusive():
    """At most one rate-limit tier fires for any single observation."""
    obs = _obs(rate_limit_5h_pct=95.0, rate_limit_7d_pct=92.0,
               rate_limit_7d_hours_left=12.0)
    insights = _build_insights(obs, _empty_memory())
    rl_keys = [k for k in _keys(insights) if k.startswith("rate_limit")]
    assert len(rl_keys) == 1
    assert rl_keys[0] == "rate_limit_high"  # near-cap wins precedence


def test_dead_band_slightly_ahead_emits_no_tier():
    """The 12–15 'slightly ahead' band intentionally stays quiet (non-annoying)."""
    # 3 days left → pace ~57. pct7=70 → ahead by ~13: not on-pace (>=12), not
    # AHEAD (<15), not behind. No weekly tier, no 5h tier.
    obs = _obs(rate_limit_5h_pct=30.0, rate_limit_7d_pct=70.0,
               rate_limit_7d_hours_left=3 * 24.0)
    insights = _build_insights(obs, _empty_memory())
    rl_keys = [k for k in _keys(insights) if k.startswith("rate_limit")]
    assert rl_keys == []
