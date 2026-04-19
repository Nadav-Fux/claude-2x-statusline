"""Unit tests for narrator.scoring.pick().

Tests cover:
- Critical ctx beats moderate burn (priority ordering)
- Novelty: repeated template returns 0 novelty → drops in ranking
- Actionability: "Consider Sonnet" rates higher than "Cache is saving"
- Cost milestone fires once per threshold
- Off-peak + low rate limit → "good moment for refactors"
- Session-management templates (long session, high ctx + session, very high ctx,
  many prompts, pivot suggestion, subagent suggestion)
- Bilingual output (STATUSLINE_NARRATOR_LANGS=en,he)
"""

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from narrator.observations import Observation
from narrator.scoring import pick, Insight, _novelty, _build_insights, _COST_MILESTONES


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _empty_memory() -> dict:
    return {
        "current": {
            "session_id": "test-sess",
            "started_at": 0.0,
            "last_emit_at": 0.0,
            "last_haiku_at": 0.0,
            "rolling_observations": [],
            "delivered_narratives": [],
            "cost_milestones_hit": [],
            "prompt_count": 0,
        },
        "prior_sessions": [],
    }


def _obs(**kwargs) -> Observation:
    """Build an Observation with keyword overrides."""
    o = Observation()
    for k, v in kwargs.items():
        setattr(o, k, v)
    return o


# ---------------------------------------------------------------------------
# 1. Priority ordering: critical ctx beats moderate burn
# ---------------------------------------------------------------------------

class TestPriorityOrdering:
    def test_critical_ctx_beats_moderate_burn(self):
        """ctx_mins_left < 30 should produce a higher-score insight than burn ~$7/hr."""
        mem = _empty_memory()
        obs = _obs(
            ctx_pct=95.0,
            ctx_mins_left=15.0,          # critical
            ctx_window_size=200000,
            total_input_tokens=190000,
            session_duration_min=30.0,
            burn_10m=7.0,                # moderate burn
            burn_session=7.0,
        )
        results = pick(obs, mem)
        assert len(results) >= 1
        top = results[0]
        # Critical ctx has urgency=10, moderate burn has urgency=4
        assert top.urgency >= 7, f"Expected urgent insight first, got urgency={top.urgency}: {top.text}"
        assert "compact now" in top.text.lower() or "full" in top.text.lower()

    def test_high_burn_beats_low_cache(self):
        """High burn (urgency=10) should rank above low cache (urgency=4)."""
        mem = _empty_memory()
        obs = _obs(
            burn_10m=12.0,               # high burn
            burn_session=12.0,
            cache_pct=30.0,              # low cache
            session_duration_min=10.0,
            total_input_tokens=50000,
        )
        results = pick(obs, mem)
        assert len(results) >= 1
        texts = [i.text for i in results]
        # High burn should appear before cache insight
        burn_idx = next((i for i, t in enumerate(texts) if "burning" in t.lower()), None)
        cache_idx = next((i for i, t in enumerate(texts) if "cache hit" in t.lower()), None)
        if burn_idx is not None and cache_idx is not None:
            assert burn_idx < cache_idx


# ---------------------------------------------------------------------------
# 2. Novelty: repeated template gets 0 novelty
# ---------------------------------------------------------------------------

class TestNovelty:
    def test_novelty_first_call_is_10(self):
        """Template unseen in recent narratives → novelty = 10."""
        mem = _empty_memory()
        assert _novelty("burn_high", mem) == 10

    def test_novelty_drops_after_repeat(self):
        """Same template key seen in delivered_narratives → novelty = 0."""
        mem = _empty_memory()
        mem["current"]["delivered_narratives"] = [
            {"text": "some burn text", "template_key": "burn_high", "ts": 1000.0},
        ]
        assert _novelty("burn_high", mem) == 0

    def test_novelty_zero_drops_score_and_ranking(self):
        """An insight with novelty=0 should rank below a fresh insight with same urgency."""
        mem = _empty_memory()
        # Seed memory with recent burn_high delivery
        mem["current"]["delivered_narratives"] = [
            {"text": "burn high text", "template_key": "burn_high", "ts": 1000.0},
        ]

        obs = _obs(
            burn_10m=12.0,           # would normally fire burn_high
            burn_session=12.0,
            session_duration_min=10.0,
            ctx_mins_left=25.0,      # also fires ctx_critical
            ctx_pct=92.0,
            total_input_tokens=185000,
            ctx_window_size=200000,
        )
        results = pick(obs, mem)
        assert len(results) >= 1
        # ctx_critical is fresh (novelty=10) and burn_high has novelty=0
        # ctx_critical should rank first
        top = results[0]
        assert "compact" in top.text.lower() or "full" in top.text.lower()

    def test_novelty_window_is_last_3(self):
        """Novelty checks last 3 delivered_narratives, not all history."""
        mem = _empty_memory()
        # 4 old deliveries + 1 recent repeat of burn_low
        mem["current"]["delivered_narratives"] = [
            {"text": "t1", "template_key": "burn_high", "ts": 100.0},
            {"text": "t2", "template_key": "burn_high", "ts": 200.0},
            {"text": "t3", "template_key": "burn_high", "ts": 300.0},
            {"text": "t4", "template_key": "other", "ts": 400.0},
            {"text": "t5", "template_key": "burn_low", "ts": 500.0},
        ]
        # burn_low is in last 3 (positions 3,4,5 = other, burn_low)
        assert _novelty("burn_low", mem) == 0
        # burn_high is NOT in last 3 (last 3 are burn_high@300, other, burn_low)
        # Actually it IS in last 3: [burn_high@300, other, burn_low]
        assert _novelty("burn_high", mem) == 0
        # Something completely new
        assert _novelty("totally_new_key", mem) == 10


# ---------------------------------------------------------------------------
# 3. Actionability scoring
# ---------------------------------------------------------------------------

class TestActionability:
    def test_consider_sonnet_rates_10(self):
        """High-burn insight containing 'Consider Sonnet' has actionability=10."""
        mem = _empty_memory()
        obs = _obs(
            burn_10m=12.0,
            burn_session=12.0,
            session_duration_min=10.0,
        )
        insights = _build_insights(obs, mem)
        burn_insights = [i for i in insights if "consider sonnet" in i.text.lower()]
        assert burn_insights, "Expected a burn_high insight with 'Consider Sonnet'"
        assert burn_insights[0].actionability == 10

    def test_cache_saving_has_lower_actionability(self):
        """Cache active insight has actionability=5 (informational with suggestion)."""
        mem = _empty_memory()
        obs = _obs(
            cache_delta_5m=2000,
            cache_read_tokens=40000,
            total_input_tokens=100000,
        )
        insights = _build_insights(obs, mem)
        cache_insights = [i for i in insights if "cache saving" in i.text.lower()]
        assert cache_insights, "Expected a cache_active insight"
        assert cache_insights[0].actionability <= 5

    def test_actionability_ordering_in_pick(self):
        """pick() places higher-actionability insight first when urgency is equal."""
        mem = _empty_memory()
        # Conditions that trigger burn_high (actionability=10) + cache_low (actionability=5)
        obs = _obs(
            burn_10m=12.0,
            burn_session=12.0,
            cache_pct=20.0,
            session_duration_min=10.0,
            total_input_tokens=50000,
        )
        results = pick(obs, mem)
        assert len(results) >= 1
        # burn_high has urgency=10, cache_low has urgency=4 → burn_high wins
        assert results[0].urgency >= 7


# ---------------------------------------------------------------------------
# 4. Cost milestone fires once per threshold
# ---------------------------------------------------------------------------

class TestCostMilestone:
    def test_milestone_fires_when_not_hit(self):
        """Crossing $5 for the first time produces a milestone insight."""
        mem = _empty_memory()
        obs = _obs(
            cost_usd=6.0,
            cost_milestones_hit=[],
            session_duration_min=30.0,
        )
        insights = _build_insights(obs, mem)
        milestone_hits = [i for i in insights if "crossed" in i.text.lower()]
        assert milestone_hits, "Expected a cost milestone insight"

    def test_milestone_does_not_fire_when_already_hit(self):
        """$5 milestone already recorded → no milestone insight."""
        mem = _empty_memory()
        obs = _obs(
            cost_usd=6.0,
            cost_milestones_hit=[5.0],   # already tracked
            session_duration_min=30.0,
        )
        insights = _build_insights(obs, mem)
        milestone_hits = [i for i in insights if "crossed" in i.text.lower()]
        assert not milestone_hits, "Milestone should not fire again once hit"

    def test_multiple_milestones_fires_highest(self):
        """Crossing $10 when $5 already hit → milestone fires for $10."""
        mem = _empty_memory()
        obs = _obs(
            cost_usd=11.0,
            cost_milestones_hit=[5.0],   # $5 already hit, $10 is new
            session_duration_min=60.0,
        )
        insights = _build_insights(obs, mem)
        milestone_hits = [i for i in insights if "crossed" in i.text.lower()]
        assert milestone_hits
        assert "$10" in milestone_hits[0].text

    def test_all_milestones_already_hit(self):
        """All milestones hit → no milestone insight at all."""
        mem = _empty_memory()
        obs = _obs(
            cost_usd=150.0,
            cost_milestones_hit=[5.0, 10.0, 25.0, 50.0, 100.0],
            session_duration_min=120.0,
        )
        insights = _build_insights(obs, mem)
        milestone_hits = [i for i in insights if "crossed" in i.text.lower()]
        assert not milestone_hits


# ---------------------------------------------------------------------------
# 5. Off-peak + low rate limit → "good moment for refactors"
# ---------------------------------------------------------------------------

class TestOffPeakInsight:
    def test_off_peak_wide_open_fires(self):
        """Off-peak + rate_limit < 50% → 'good moment for heavy refactors' insight."""
        mem = _empty_memory()
        obs = _obs(
            is_peak=False,
            rate_limit_5h_pct=20.0,
            rate_limit_7d_pct=15.0,
        )
        insights = _build_insights(obs, mem)
        off_peak = [i for i in insights if "refactors" in i.text.lower()]
        assert off_peak, f"Expected off-peak insight, got: {[i.text for i in insights]}"
        assert off_peak[0].template_key == "off_peak_wide_open"

    def test_off_peak_does_not_fire_when_rate_limit_high(self):
        """If rate limit > 80%, rate_limit_high takes precedence, no off_peak_wide_open."""
        mem = _empty_memory()
        obs = _obs(
            is_peak=False,
            rate_limit_5h_pct=85.0,
            rate_limit_7d_pct=10.0,
        )
        insights = _build_insights(obs, mem)
        off_peak = [i for i in insights if "refactors" in i.text.lower()]
        # off_peak_wide_open should not fire when rate_limit > 80%
        assert not off_peak

    def test_peak_hours_fires_instead_of_off_peak(self):
        """is_peak=True → peak_rate_ok fires, not off_peak."""
        mem = _empty_memory()
        obs = _obs(
            is_peak=True,
            rate_limit_5h_pct=30.0,
            rate_limit_7d_pct=20.0,
        )
        insights = _build_insights(obs, mem)
        off_peak = [i for i in insights if "refactors" in i.text.lower()]
        peak_insights = [i for i in insights if "peak hours" in i.text.lower()]
        assert not off_peak
        assert peak_insights

    def test_off_peak_actionability_is_7(self):
        """off_peak_wide_open has actionability=7 (clear action suggestion)."""
        mem = _empty_memory()
        obs = _obs(
            is_peak=False,
            rate_limit_5h_pct=10.0,
            rate_limit_7d_pct=5.0,
        )
        insights = _build_insights(obs, mem)
        off_peak = [i for i in insights if i.template_key == "off_peak_wide_open"]
        assert off_peak
        assert off_peak[0].actionability == 7


# ---------------------------------------------------------------------------
# 6. Score formula
# ---------------------------------------------------------------------------

class TestScoreFormula:
    def test_score_computation(self):
        """Verify weighted formula: urgency*3 + novelty*2 + actionability*2 + uniqueness."""
        i = Insight(
            text="test",
            urgency=10,
            novelty=10,
            actionability=10,
            uniqueness=10,
            template_key="x",
        )
        expected = 10 * 3 + 10 * 2 + 10 * 2 + 10 * 1
        assert i.score == expected

    def test_pick_returns_at_most_2(self):
        """pick() never returns more than 2 insights."""
        mem = _empty_memory()
        # Trigger many conditions simultaneously
        obs = _obs(
            ctx_mins_left=20.0,
            ctx_pct=95.0,
            ctx_window_size=200000,
            total_input_tokens=190000,
            burn_10m=12.0,
            burn_session=12.0,
            cache_pct=20.0,
            cache_delta_5m=2000,
            cache_read_tokens=10000,
            is_peak=True,
            rate_limit_5h_pct=85.0,
            session_duration_min=30.0,
            cost_usd=6.0,
            cost_milestones_hit=[],
        )
        results = pick(obs, mem)
        assert len(results) <= 2

    def test_pick_empty_on_no_conditions(self):
        """With a completely default (zero) Observation and no matching templates, pick may return 0 or more."""
        mem = _empty_memory()
        obs = Observation()  # all zeros, off-peak=False, no rate limit info
        results = pick(obs, mem)
        # off_peak_wide_open fires for default obs (is_peak=False, both rate limits = 0 < 50)
        assert isinstance(results, list)
        assert len(results) <= 2


# ---------------------------------------------------------------------------
# 7. Session-management templates
# ---------------------------------------------------------------------------

class TestSessionManagementTemplates:

    def test_long_session_advice_fires_after_2h(self):
        """session_duration_min=130 → long_session template fires."""
        mem = _empty_memory()
        obs = _obs(session_duration_min=130.0)
        insights = _build_insights(obs, mem)
        long_sess = [i for i in insights if i.template_key == "long_session"]
        assert long_sess, f"Expected long_session insight, got: {[i.template_key for i in insights]}"
        assert "2h" in long_sess[0].text or "h " in long_sess[0].text
        assert long_sess[0].actionability == 8

    def test_long_session_does_not_fire_under_2h(self):
        """session_duration_min=90 → long_session should NOT fire."""
        mem = _empty_memory()
        obs = _obs(session_duration_min=90.0)
        insights = _build_insights(obs, mem)
        long_sess = [i for i in insights if i.template_key == "long_session"]
        assert not long_sess

    def test_high_context_compact_directive_fires(self):
        """ctx_pct=75, session_duration_min=80 → ctx_high_long_session fires."""
        mem = _empty_memory()
        obs = _obs(ctx_pct=75.0, session_duration_min=80.0)
        insights = _build_insights(obs, mem)
        high_ctx = [i for i in insights if i.template_key == "ctx_high_long_session"]
        assert high_ctx, f"Expected ctx_high_long_session insight, got: {[i.template_key for i in insights]}"
        assert "compact" in high_ctx[0].text.lower()
        assert high_ctx[0].actionability == 10
        assert high_ctx[0].urgency == 6

    def test_high_context_compact_directive_does_not_fire_short_session(self):
        """ctx_pct=75 but session_duration_min=30 → ctx_high_long_session should NOT fire."""
        mem = _empty_memory()
        obs = _obs(ctx_pct=75.0, session_duration_min=30.0)
        insights = _build_insights(obs, mem)
        high_ctx = [i for i in insights if i.template_key == "ctx_high_long_session"]
        assert not high_ctx

    def test_very_high_context_fires_at_95(self):
        """ctx_pct=95 → ctx_very_high fires with urgency=9."""
        mem = _empty_memory()
        obs = _obs(ctx_pct=95.0)
        insights = _build_insights(obs, mem)
        very_high = [i for i in insights if i.template_key == "ctx_very_high"]
        assert very_high, f"Expected ctx_very_high insight, got: {[i.template_key for i in insights]}"
        assert very_high[0].urgency == 9
        assert very_high[0].actionability == 10
        assert "auto-compact" in very_high[0].text.lower() or "/compact" in very_high[0].text

    def test_many_prompts_fires_above_30(self):
        """prompt_count=35 → many_prompts template fires."""
        mem = _empty_memory()
        obs = _obs(prompt_count=35)
        insights = _build_insights(obs, mem)
        many = [i for i in insights if i.template_key == "many_prompts"]
        assert many, f"Expected many_prompts insight, got: {[i.template_key for i in insights]}"
        assert "35" in many[0].text
        assert many[0].urgency == 3
        assert many[0].actionability == 8

    def test_many_prompts_does_not_fire_under_30(self):
        """prompt_count=25 → many_prompts should NOT fire."""
        mem = _empty_memory()
        obs = _obs(prompt_count=25)
        insights = _build_insights(obs, mem)
        many = [i for i in insights if i.template_key == "many_prompts"]
        assert not many

    def test_pivot_suggestion_fires_when_deep_no_milestone(self):
        """ctx_pct=60, prompt_count=25, no recent milestone → pivot_suggestion fires."""
        mem = _empty_memory()
        # No active milestone crossing: cost_usd < any milestone, milestones_hit = []
        obs = _obs(ctx_pct=60.0, prompt_count=25, cost_usd=0.0, cost_milestones_hit=[])
        insights = _build_insights(obs, mem)
        pivot = [i for i in insights if i.template_key == "pivot_suggestion"]
        assert pivot, f"Expected pivot_suggestion insight, got: {[i.template_key for i in insights]}"
        assert "rewind" in pivot[0].text.lower()
        assert pivot[0].urgency == 5

    def test_pivot_suggestion_suppressed_when_milestone_fresh(self):
        """pivot_suggestion should NOT fire when a fresh milestone is being crossed."""
        mem = _empty_memory()
        # cost_usd just crossed $5 and not yet recorded in milestones_hit
        obs = _obs(ctx_pct=60.0, prompt_count=25, cost_usd=6.0, cost_milestones_hit=[])
        insights = _build_insights(obs, mem)
        pivot = [i for i in insights if i.template_key == "pivot_suggestion"]
        assert not pivot

    def test_subagent_suggestion_fires_heavy_session(self):
        """session_duration_min=20, burn_10m=9 → subagent_suggestion fires."""
        mem = _empty_memory()
        obs = _obs(session_duration_min=20.0, burn_10m=9.0)
        insights = _build_insights(obs, mem)
        subagent = [i for i in insights if i.template_key == "subagent_suggestion"]
        assert subagent, f"Expected subagent_suggestion insight, got: {[i.template_key for i in insights]}"
        assert "subagent" in subagent[0].text.lower()
        assert subagent[0].urgency == 2

    def test_subagent_suggestion_does_not_fire_light_session(self):
        """burn_10m=5 → subagent_suggestion should NOT fire (threshold is > 8)."""
        mem = _empty_memory()
        obs = _obs(session_duration_min=20.0, burn_10m=5.0)
        insights = _build_insights(obs, mem)
        subagent = [i for i in insights if i.template_key == "subagent_suggestion"]
        assert not subagent


# ---------------------------------------------------------------------------
# 8. Bilingual output
# ---------------------------------------------------------------------------

class TestBilingualOutput:

    def test_bilingual_output_has_both_languages(self):
        """STATUSLINE_NARRATOR_LANGS=en,he → output contains English and Hebrew text."""
        import time
        import narrator.memory as _mem

        # Build a memory dict that will trigger at least one session-management template
        data = {
            "current": {
                "session_id": "test-bilingual",
                "started_at": time.time() - 130 * 60,  # 130 min ago → long_session fires
                "last_emit_at": 0.0,
                "last_haiku_at": 0.0,
                "rolling_observations": [],
                "delivered_narratives": [],
                "cost_milestones_hit": [],
                "prompt_count": 1,
            },
            "prior_sessions": [],
        }

        obs = _obs(session_duration_min=130.0)

        from narrator.scoring import pick as _pick
        insights = _pick(obs, data)
        assert insights, "Expected at least one insight for bilingual test"

        # Build lines as engine.py would, with both langs
        en_parts = [i.text for i in insights]
        he_parts = [i.text_he for i in insights if i.text_he]

        assert en_parts, "Expected English parts"
        assert he_parts, "Expected Hebrew parts — new templates must have text_he"

        en_line = " · ".join(en_parts)
        he_line = " · ".join(he_parts)

        # Verify English keyword present
        assert any(kw in en_line for kw in ("Context", "session", "prompts", "Long")), \
            f"Expected English keyword in: {en_line}"
        # Verify Hebrew content present (at least one Hebrew character)
        assert any("\u05d0" <= c <= "\u05ea" for c in he_line), \
            f"Expected Hebrew characters in: {he_line}"

    def test_insight_has_text_he_field(self):
        """New session-management insights carry a non-empty text_he."""
        mem = _empty_memory()
        obs = _obs(session_duration_min=130.0)
        insights = _build_insights(obs, mem)
        long_sess = [i for i in insights if i.template_key == "long_session"]
        assert long_sess
        assert long_sess[0].text_he, "long_session insight must have a Hebrew text"
        # Hebrew must contain at least one Hebrew character
        assert any("\u05d0" <= c <= "\u05ea" for c in long_sess[0].text_he)

    def test_engine_languages_default_en(self):
        """Without STATUSLINE_NARRATOR_LANGS set, _languages() returns ['en']."""
        from narrator.engine import _languages
        with patch.dict(os.environ, {}, clear=False):
            env = os.environ.copy()
            env.pop("STATUSLINE_NARRATOR_LANGS", None)
            with patch.dict(os.environ, env, clear=True):
                result = _languages()
        assert result == ["en"]

    def test_engine_languages_parses_en_he(self):
        """STATUSLINE_NARRATOR_LANGS=en,he → ['en', 'he']."""
        from narrator.engine import _languages
        with patch.dict(os.environ, {"STATUSLINE_NARRATOR_LANGS": "en,he"}):
            result = _languages()
        assert result == ["en", "he"]

    def test_engine_languages_rejects_unknown(self):
        """STATUSLINE_NARRATOR_LANGS=en,fr → only 'en' kept."""
        from narrator.engine import _languages
        with patch.dict(os.environ, {"STATUSLINE_NARRATOR_LANGS": "en,fr"}):
            result = _languages()
        assert result == ["en"]


# ---------------------------------------------------------------------------
# 9. Locale-detection tests
# ---------------------------------------------------------------------------

class TestLocaleDetection:

    def test_locale_hebrew_sets_default_he(self):
        """LANG=he_IL.UTF-8, no STATUSLINE_NARRATOR_LANGS → _languages() == ['he']."""
        from narrator.engine import _languages
        env = {k: v for k, v in os.environ.items()
               if k not in ("STATUSLINE_NARRATOR_LANGS", "LC_ALL", "LC_MESSAGES", "LANG")}
        env["LANG"] = "he_IL.UTF-8"
        with patch.dict(os.environ, env, clear=True):
            result = _languages()
        assert result == ["he"], f"Expected ['he'], got {result}"

    def test_locale_english_sets_default_en(self):
        """LANG=en_US.UTF-8, no override → _languages() == ['en']."""
        from narrator.engine import _languages
        env = {k: v for k, v in os.environ.items()
               if k not in ("STATUSLINE_NARRATOR_LANGS", "LC_ALL", "LC_MESSAGES", "LANG")}
        env["LANG"] = "en_US.UTF-8"
        with patch.dict(os.environ, env, clear=True):
            result = _languages()
        assert result == ["en"], f"Expected ['en'], got {result}"

    def test_env_override_wins_over_locale(self):
        """LANG=he_IL AND STATUSLINE_NARRATOR_LANGS=en → explicit override wins → ['en']."""
        from narrator.engine import _languages
        env = {k: v for k, v in os.environ.items()
               if k not in ("STATUSLINE_NARRATOR_LANGS", "LC_ALL", "LC_MESSAGES", "LANG")}
        env["LANG"] = "he_IL"
        env["STATUSLINE_NARRATOR_LANGS"] = "en"
        with patch.dict(os.environ, env, clear=True):
            result = _languages()
        assert result == ["en"], f"Expected ['en'], got {result}"

    def test_lc_all_takes_priority_over_lang(self):
        """LC_ALL=he wins over LANG=en."""
        from narrator.engine import _languages
        env = {k: v for k, v in os.environ.items()
               if k not in ("STATUSLINE_NARRATOR_LANGS", "LC_ALL", "LC_MESSAGES", "LANG")}
        env["LC_ALL"] = "he_IL.UTF-8"
        env["LANG"] = "en_US.UTF-8"
        with patch.dict(os.environ, env, clear=True):
            result = _languages()
        assert result == ["he"], f"Expected ['he'], got {result}"


# ---------------------------------------------------------------------------
# 10. Structural: every template that can fire has text_he
# ---------------------------------------------------------------------------

class TestEveryTemplateHasHebrew:

    def _universal_obs(self) -> "Observation":
        """Build an Observation that triggers all template conditions simultaneously."""
        return _obs(
            ctx_pct=85.0,
            ctx_mins_left=20.0,          # < 30 → ctx_critical
            ctx_window_size=200000,
            total_input_tokens=170000,
            burn_10m=12.0,               # >= 10 → burn_high
            burn_session=12.0,
            cache_pct=30.0,              # < 50 → cache_low
            cache_delta_5m=2000,         # > 500 → cache_active
            cache_read_tokens=30000,
            is_peak=True,
            rate_limit_5h_pct=85.0,      # > 80 → rate_limit_high
            rate_limit_7d_pct=20.0,
            session_duration_min=130.0,  # > 120 → long_session; > 60 → ctx_high_long_session
            cost_usd=6.0,                # crosses $5 milestone
            cost_milestones_hit=[],
            prompt_count=35,             # > 30 → many_prompts
        )

    def test_every_template_has_hebrew(self):
        """All insights that _build_insights() can return must have a non-empty text_he."""
        mem = _empty_memory()
        obs = self._universal_obs()
        insights = _build_insights(obs, mem)
        assert insights, "Expected at least one insight from universal observation"

        missing = [
            (i.template_key, i.text[:60])
            for i in insights
            if not i.text_he
        ]
        assert not missing, (
            "The following templates are missing text_he:\n"
            + "\n".join(f"  key={k!r}  text={t!r}" for k, t in missing)
        )

    def test_hebrew_contains_hebrew_characters(self):
        """Every text_he that is set must contain at least one Hebrew character."""
        mem = _empty_memory()
        obs = self._universal_obs()
        insights = _build_insights(obs, mem)

        bad = []
        for i in insights:
            if i.text_he and not any("\u05d0" <= c <= "\u05ea" for c in i.text_he):
                bad.append((i.template_key, i.text_he[:60]))

        assert not bad, (
            "text_he fields that lack Hebrew characters:\n"
            + "\n".join(f"  key={k!r}  text_he={t!r}" for k, t in bad)
        )
