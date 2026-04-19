"""narrator.scoring — 4-axis scoring and rules-template renderer.

Each template follows the observation → meaning → action pattern.
The pick() function returns up to 2 Insight objects, sorted by weighted score.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from narrator.observations import Observation


# ---------------------------------------------------------------------------
# Insight dataclass
# ---------------------------------------------------------------------------

@dataclass
class Insight:
    text: str
    urgency: int = 4         # 10=critical, 7=warning, 4=info, 1=fallback
    novelty: int = 10        # 10=not seen recently, 0=repeated
    actionability: int = 5   # 10=strong action, 5=info+suggestion, 2=pure info
    uniqueness: int = 10     # 10=novel fact, 5=adds meaning, 0=restatement
    template_key: str = ""   # used for novelty dedup
    text_he: str = ""        # Hebrew translation (optional)

    @property
    def score(self) -> int:
        return self.urgency * 3 + self.novelty * 2 + self.actionability * 2 + self.uniqueness * 1


# ---------------------------------------------------------------------------
# Cost milestones
# ---------------------------------------------------------------------------

_COST_MILESTONES = [5.0, 10.0, 25.0, 50.0, 100.0]


def _next_milestone(cost: float) -> Optional[float]:
    """Return the highest milestone crossed that hasn't been hit yet."""
    crossed = [m for m in _COST_MILESTONES if cost >= m]
    return max(crossed) if crossed else None


# ---------------------------------------------------------------------------
# Novelty helper
# ---------------------------------------------------------------------------

def _novelty(template_key: str, memory: dict) -> int:
    """Return 10 if template hasn't fired in the last 3 delivered narratives, else 0."""
    current = memory.get("current", {})
    recent = current.get("delivered_narratives", [])[-3:]
    for entry in recent:
        if isinstance(entry, dict) and entry.get("template_key") == template_key:
            return 0
        if isinstance(entry, str) and template_key in entry:
            return 0
    return 10


# ---------------------------------------------------------------------------
# Template builders
# ---------------------------------------------------------------------------

def _build_insights(obs: "Observation", memory: dict) -> list[Insight]:
    """Evaluate all templates against obs and return matching Insight objects."""
    results: list[Insight] = []

    # Convenience aliases
    ctx = obs.ctx_pct
    ctx_left = obs.ctx_mins_left
    burn_10m = obs.burn_10m
    burn_sess = obs.burn_session
    effective_burn = burn_10m if burn_10m is not None else burn_sess

    # ── Context: Critical (< 30 min left) ────────────────────────────────────
    if ctx_left is not None and ctx_left < 30:
        n = math.ceil(ctx_left)
        key = "ctx_critical"
        results.append(Insight(
            text=f"Context fills in ~{n}m — compact now or history gets truncated.",
            urgency=10,
            novelty=_novelty(key, memory),
            actionability=10,
            uniqueness=10,
            template_key=key,
        ))

    # ── Context: Warning (< 60 min left) ─────────────────────────────────────
    elif ctx_left is not None and ctx_left < 60:
        n = math.ceil(ctx_left)
        key = "ctx_warning"
        results.append(Insight(
            text=f"Context at ~{ctx:.0f}% with {n}m until full. "
                 f"Finish current thread before starting new work.",
            urgency=7,
            novelty=_novelty(key, memory),
            actionability=7,
            uniqueness=5,
            template_key=key,
        ))

    # ── Context: Crossed 80 % with > 30 min left ─────────────────────────────
    elif ctx >= 80 and (ctx_left is None or ctx_left > 30):
        key = "ctx_80_headroom"
        results.append(Insight(
            text=f"Context at {ctx:.0f}% — headroom shrinking, plan a natural break soon.",
            urgency=7,
            novelty=_novelty(key, memory),
            actionability=7,
            uniqueness=5,
            template_key=key,
        ))

    # ── Burn: High (≥ $10/hr rolling or ≥ $15/hr session) ───────────────────
    if effective_burn is not None and (
        (burn_10m is not None and burn_10m >= 10.0) or
        (burn_sess is not None and burn_sess >= 15.0)
    ):
        rate_display = burn_10m if burn_10m is not None else burn_sess
        # Time to $X budget (assume $50 default — use 5-hour budget extrapolation)
        budget_hours = 5.0
        hours_left = max(0.0, (50.0 - obs.cost_usd) / rate_display) if rate_display > 0 else 0.0
        mins_left = int(hours_left * 60)
        key = "burn_high"
        results.append(Insight(
            text=f"Burning ${rate_display:.1f}/hr — at this rate your 5-hour budget ends in "
                 f"~{mins_left}m. Consider Sonnet for simple steps.",
            urgency=10,
            novelty=_novelty(key, memory),
            actionability=10,
            uniqueness=10,
            template_key=key,
        ))

    # ── Burn: Moderate ($5–$10/hr) ────────────────────────────────────────────
    elif effective_burn is not None and effective_burn >= 5.0:
        key = "burn_moderate"
        label = "(10m)" if burn_10m is not None else "(session)"
        results.append(Insight(
            text=f"Spending ${effective_burn:.1f}/hr {label} — steady pace for complex work. Budget OK.",
            urgency=4,
            novelty=_novelty(key, memory),
            actionability=5,
            uniqueness=5,
            template_key=key,
        ))

    # ── Burn: Low (< $5/hr, session > 5 min) ─────────────────────────────────
    elif effective_burn is not None and effective_burn < 5.0 and obs.session_duration_min > 5:
        key = "burn_low"
        results.append(Insight(
            text=f"Spending ${effective_burn:.1f}/hr — cheap session, cache doing its job.",
            urgency=4,
            novelty=_novelty(key, memory),
            actionability=2,
            uniqueness=5,
            template_key=key,
        ))

    # ── Cache: Low hit ratio (< 50 %, session > 2 min) ───────────────────────
    if obs.cache_pct < 50 and obs.session_duration_min > 2 and obs.total_input_tokens > 0:
        key = "cache_low"
        results.append(Insight(
            text=f"Cache hit ratio is {obs.cache_pct:.0f}% — most tokens are being created fresh. "
                 f"If looping on same files they should warm up shortly.",
            urgency=4,
            novelty=_novelty(key, memory),
            actionability=5,
            uniqueness=10,
            template_key=key,
        ))

    # ── Cache: Active (delta > 500 in 5 min) ─────────────────────────────────
    if obs.cache_delta_5m is not None and obs.cache_delta_5m > 500:
        delta_k = obs.cache_delta_5m / 1000
        # Effective cost-reduction pct: cache reads cost ~10% of normal input,
        # so savings ≈ (cache_hit_ratio) × 90%. Clamp to [0, 90].
        savings_pct = max(0.0, min(90.0, obs.cache_pct * 0.90))
        key = "cache_active"
        results.append(Insight(
            text=f"Cache saving ~{delta_k:.0f}k tokens / 5 min — "
                 f"keeping effective cost ~{savings_pct:.0f}% below raw.",
            urgency=4,
            novelty=_novelty(key, memory),
            actionability=5,
            uniqueness=10,
            template_key=key,
        ))

    # ── Cost milestone ────────────────────────────────────────────────────────
    milestone = _next_milestone(obs.cost_usd)
    if milestone is not None and milestone not in obs.cost_milestones_hit:
        # Extrapolate to 5h using sanitised burn rates first, then a guarded
        # raw fallback so the milestone still fires for fresh sessions without
        # rolling data yet.
        rate = obs.burn_10m if obs.burn_10m is not None else obs.burn_session
        if rate is None and obs.session_duration_min >= 1.0 and obs.cost_usd > 0:
            raw = obs.cost_usd / (obs.session_duration_min / 60.0)
            if raw <= 200.0:  # sanity cap: nothing absurd
                rate = raw
        if rate is not None and rate > 0:
            projected = rate * 5.0
            key = f"milestone_{milestone}"
            results.append(Insight(
                text=f"You've crossed ${milestone:.0f} — at current rate, extrapolates to "
                     f"~${projected:.0f} by 5h mark. Worth it?",
                urgency=7,
                novelty=_novelty(key, memory),
                actionability=5,
                uniqueness=10,
                template_key=key,
            ))

    # ── Rate limit > 80 % ─────────────────────────────────────────────────────
    max_rl = max(obs.rate_limit_5h_pct, obs.rate_limit_7d_pct)
    if max_rl > 80:
        key = "rate_limit_high"
        results.append(Insight(
            text=f"Rate limit at {max_rl:.0f}% — close to cap. Plan break before compact.",
            urgency=10,
            novelty=_novelty(key, memory),
            actionability=10,
            uniqueness=10,
            template_key=key,
        ))

    # ── Peak hours + rate limit < 80 % ───────────────────────────────────────
    elif obs.is_peak and max_rl < 80:
        key = "peak_rate_ok"
        results.append(Insight(
            text=f"Peak hours — rate limits drain faster. Budget: {max_rl:.0f}% used.",
            urgency=7,
            novelty=_novelty(key, memory),
            actionability=5,
            uniqueness=5,
            template_key=key,
        ))

    # ── Off-peak + rate limit < 50 % ─────────────────────────────────────────
    elif not obs.is_peak and max_rl < 50:
        key = "off_peak_wide_open"
        results.append(Insight(
            text=f"Off-peak with wide-open limits — good moment for heavy refactors.",
            urgency=4,
            novelty=_novelty(key, memory),
            actionability=7,
            uniqueness=10,
            template_key=key,
        ))

    # ── Session management templates ──────────────────────────────────────────

    # ── 1. Long session (> 2h) ────────────────────────────────────────────────
    if obs.session_duration_min > 120:
        dur_h = int(obs.session_duration_min // 60)
        dur_m = int(obs.session_duration_min % 60)
        key = "long_session"
        results.append(Insight(
            text=(
                f"Long session ({dur_h}h {dur_m}m) — context rot starts compounding. "
                f"Consider /clear for a fresh start if you've moved past the original task."
            ),
            text_he=(
                f"סשן ארוך ({dur_h} שעות {dur_m} דקות) — "
                f"הקשב של המודל מתפזר על יותר מדי דברים ישנים. "
                f"שקול /clear אם עברת לנושא חדש ממה שהתחלת."
            ),
            urgency=4,
            novelty=_novelty(key, memory),
            actionability=8,
            uniqueness=10,
            template_key=key,
        ))

    # ── 2. High context + long session ───────────────────────────────────────
    if obs.ctx_pct > 70 and obs.session_duration_min > 60:
        key = "ctx_high_long_session"
        results.append(Insight(
            text=(
                f"Context {obs.ctx_pct:.0f}% full + {obs.session_duration_min:.0f} min of session — "
                f"noise accumulating. Try /compact with a directive ('keep the migration plan, "
                f"drop the debugging'), not plain auto-compact."
            ),
            text_he=(
                f"Context ב-{obs.ctx_pct:.0f}% ו-{obs.session_duration_min:.0f} דקות של סשן — "
                f"רעש מצטבר. עדיף /compact עם הנחיה ('תשמור את תכנית המיגרציה, תוריד את ה-debug') "
                f"במקום auto-compact."
            ),
            urgency=6,
            novelty=_novelty(key, memory),
            actionability=10,
            uniqueness=10,
            template_key=key,
        ))

    # ── 3. Very high context (> 90 %) ────────────────────────────────────────
    if obs.ctx_pct > 90:
        key = "ctx_very_high"
        results.append(Insight(
            text=(
                f"Context nearly full ({obs.ctx_pct:.0f}%). "
                f"Auto-compact will probably drop what's currently relevant — "
                f"it summarizes the main thread, not the latest pivot. "
                f"Manual /compact with 'focus on current task' is safer."
            ),
            text_he=(
                f"Context כמעט מלא ({obs.ctx_pct:.0f}%). "
                f"Auto-compact יכול לאבד את מה שחשוב עכשיו — "
                f"הוא מסכם לפי הקו המרכזי, לא לפי הכיוון האחרון. "
                f"עדיף /compact ידני עם 'תתמקד במשימה הנוכחית'."
            ),
            urgency=9,
            novelty=_novelty(key, memory),
            actionability=10,
            uniqueness=10,
            template_key=key,
        ))

    # ── 4. Many prompts in session (> 30) ────────────────────────────────────
    if obs.prompt_count > 30:
        key = "many_prompts"
        results.append(Insight(
            text=(
                f"{obs.prompt_count} prompts in this session. "
                f"If you're shifting to a new task, a fresh session is usually faster than "
                f"compacting — same advice Anthropic gives for 1M context."
            ),
            text_he=(
                f"{obs.prompt_count} פרומפטים בסשן הזה. "
                f"אם אתה עובר למשימה חדשה, סשן חדש בדרך כלל מהיר יותר מcompact — "
                f"אותה ההמלצה של Anthropic ל-1M context."
            ),
            urgency=3,
            novelty=_novelty(key, memory),
            actionability=8,
            uniqueness=8,
            template_key=key,
        ))

    # ── 5. Pivot suggestion (deep in session, no recent milestone) ────────────
    milestone = _next_milestone(obs.cost_usd)
    recent_milestone = milestone is not None and milestone not in obs.cost_milestones_hit
    if obs.ctx_pct > 50 and obs.prompt_count > 20 and not recent_milestone:
        key = "pivot_suggestion"
        results.append(Insight(
            text=(
                f"Deep in this session ({obs.ctx_pct:.0f}% context, {obs.prompt_count} prompts). "
                f"If this is turning into a new direction, consider rewind + fresh prompt "
                f"rather than pushing forward with all the prior dead-ends in context."
            ),
            text_he=(
                f"עמוק בתוך הסשן ({obs.ctx_pct:.0f}% context, {obs.prompt_count} פרומפטים). "
                f"אם זה נהיה כיוון חדש — עדיף rewind והמשך נקי, "
                f"במקום לגרור אחריך את כל הניסיונות שכבר לא רלוונטיים."
            ),
            urgency=5,
            novelty=_novelty(key, memory),
            actionability=7,
            uniqueness=9,
            template_key=key,
        ))

    # ── 6. Subagent suggestion (heavy work, early session) ───────────────────
    if obs.session_duration_min > 15 and obs.burn_10m is not None and obs.burn_10m > 8:
        key = "subagent_suggestion"
        results.append(Insight(
            text=(
                "Heavy work? Subagents keep the main session clean — "
                "spawn one for anything that generates lots of intermediate output you won't need back."
            ),
            text_he=(
                "עבודה כבדה? Subagents שומרים את הסשן הראשי נקי — "
                "שלח סוכן נפרד לכל משימה שמייצרת הרבה פלט ביניים שלא תצטרך בחזרה."
            ),
            urgency=2,
            novelty=_novelty(key, memory),
            actionability=6,
            uniqueness=7,
            template_key=key,
        ))

    return results


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def pick(obs: "Observation", memory: dict) -> list[Insight]:
    """Evaluate templates, score each, and return top 2 Insight objects."""
    try:
        insights = _build_insights(obs, memory)
        insights.sort(key=lambda i: i.score, reverse=True)
        return insights[:2]
    except Exception:
        return []
