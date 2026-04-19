"""narrator.scoring — 4-axis scoring and rules-template renderer.

Each template follows the observation → meaning → action pattern.
The pick() function returns up to 2 Insight objects, sorted by weighted score.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
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
