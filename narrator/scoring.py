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

_COST_MILESTONES = [5, 10, 25, 50, 100]


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


def _usage_pct(window) -> Optional[float]:
    if not isinstance(window, dict):
        return None
    try:
        pct = float(window.get("used_pct"))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(pct):
        return None
    return max(0.0, min(100.0, pct))


def _record_label(record: dict) -> str:
    label = str(record.get("label") or record.get("provider") or "").strip()
    return label or "provider"


def _window_label(window, fallback: str) -> str:
    if isinstance(window, dict):
        label = str(window.get("label") or "").strip()
        if label:
            return label
    return fallback


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
            text_he=f"ה-context מתמלא תוך ~{n} דקות — /compact עכשיו, אחרת ההיסטוריה תיחתך.",
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
            text_he=f"Context ב-~{ctx:.0f}% — {n} דקות עד שהוא מתמלא. "
                    f"סיים את הנושא הנוכחי לפני שמתחילים משהו חדש.",
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
            text_he=f"Context ב-{ctx:.0f}% — המרווח מצטמצם, תתכנן עצירה טבעית בקרוב.",
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
            text_he=f"שורף ${rate_display:.1f}/hr — בקצב הזה תגמור את budget 5 השעות בעוד ~{mins_left} דקות. "
                    f"שקול Sonnet לצעדים פשוטים.",
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
            text_he=f"מוציא ${effective_burn:.1f}/hr {label} — קצב יציב לעבודה מורכבת. Budget בסדר.",
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
            text=f"Spending ${effective_burn:.1f}/hr — cheap session, cache doing its job. "
                 f"Good time to batch cleanup, tests, and mechanical follow-through.",
            text_he=f"מוציא ${effective_burn:.1f}/hr — סשן זול, ה-cache עושה את שלו. "
                    f"זה זמן טוב לסגור cleanup, בדיקות ומשימות מכניות של follow-through.",
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
            text_he=f"אחוז ה-cache hit הוא {obs.cache_pct:.0f}% — רוב הטוקנים נוצרים מחדש. "
                    f"אם חוזרים על אותם קבצים, ה-cache יתחמם בקרוב.",
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
            text_he=f"Cache חוסך ~{delta_k:.0f}k טוקנים ב-5 דקות — "
                    f"העלות האפקטיבית נמוכה ב-~{savings_pct:.0f}% ממה שהייתה בלי cache.",
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
                text_he=f"חצית את ה-${milestone:.0f} — בקצב הנוכחי זה מתורגם ל-~${projected:.0f} "
                        f"עד סוף 5 שעות. שווה את זה?",
                urgency=7,
                novelty=_novelty(key, memory),
                actionability=5,
                uniqueness=10,
                template_key=key,
            ))

    # ── Rate limit (cycle-aware tiers) ────────────────────────────────────────
    # The 7-day weekly window has a "day in the cycle" concept: 30% used on day 1
    # is very different from 30% on day 6. We position the current utilisation
    # against the EVEN pace you'd expect by now (elapsed fraction of the 7 days).
    # The 5-hour window is a rolling window (no day concept) — it only gets the
    # blunt near-cap tier. Tiers are mutually exclusive, evaluated in precedence.
    pct5 = obs.rate_limit_5h_pct
    pct7 = obs.rate_limit_7d_pct
    max_rl = max(pct5, pct7)
    hours_left = obs.rate_limit_7d_hours_left  # None when no reset data
    if hours_left is not None:
        days_left = hours_left / 24.0
        elapsed_frac = max(0.0, min(1.0, 1.0 - days_left / 7.0))
        pace = elapsed_frac * 100.0
    else:
        days_left = None
        pace = None

    rate_limit_fired = False

    # Tier 1 — NEAR CAP: the safety net, regardless of where we are in the cycle.
    # Fires at >=90% on either window, OR (when we have no reset data to reason
    # about the cycle) the old >80% behaviour.
    if max_rl >= 90 or (hours_left is None and max_rl > 80):
        key = "rate_limit_high"
        results.append(Insight(
            text=f"Rate limit at {max_rl:.0f}% — close to cap. Plan break before compact.",
            text_he=f"ה-rate limit הגיע ל-{max_rl:.0f}% — קרוב לתקרה. תכנן הפסקה לפני /compact.",
            urgency=10,
            novelty=_novelty(key, memory),
            actionability=10,
            uniqueness=10,
            template_key=key,
        ))
        rate_limit_fired = True

    # Tier 2 — AHEAD OF PACE (firm, not alarmist): meaningful 7-day usage, still
    # at least a day from reset, and running notably hotter than the even pace
    # line (100%/7d ≈ 14.3%/day) → on track to cap out before reset. Generalised
    # to ANY day in the cycle, not just early.
    elif (hours_left is not None and pct7 >= 40 and days_left >= 1.0
          and (pct7 - pace) >= 15):
        key = "rate_limit_ahead_of_pace"
        results.append(Insight(
            text=(
                f"Weekly cap {pct7:.0f}% used with ~{days_left:.0f}d to reset — ahead of an "
                f"even {pace:.0f}% pace. Ease off or you'll cap out before reset."
            ),
            text_he=(
                f"מכסת השבוע ב-{pct7:.0f}% ונשארו ~{days_left:.0f} ימים לאיפוס — "
                f"אתה לפני הקצב ({pace:.0f}%). תוריד הילוך, אחרת תיגמר לפני האיפוס."
            ),
            urgency=7,
            novelty=_novelty(key, memory),
            actionability=8,
            uniqueness=10,
            template_key=key,
        ))
        rate_limit_fired = True

    # ON-PACE (neutral, lowest urgency): tracking roughly along the even line.
    # Just a calm "you're fine" cue — must be rare (low urgency + novelty
    # cooldown) so it never nags. Sits between AHEAD and BEHIND in precedence.
    elif (hours_left is not None and abs(pct7 - pace) < 12 and pct7 >= 20):
        headroom = 100.0 - pct7
        key = "rate_limit_on_pace"
        results.append(Insight(
            text=(
                f"Tracking right on an even weekly pace — ~{days_left:.0f}d and "
                f"~{headroom:.0f}% left."
            ),
            text_he=(
                f"אתה בדיוק על הקצב השבועי האחיד — נשארו ~{days_left:.0f} ימים "
                f"ו-~{headroom:.0f}% מהמכסה."
            ),
            urgency=2,
            novelty=_novelty(key, memory),
            actionability=2,
            uniqueness=5,
            template_key=key,
        ))
        rate_limit_fired = True

    # BEHIND / HEADROOM (gentle, encouraging): under the even pace line on ANY
    # day → plenty of unused budget. Low urgency + novelty cooldown so it speaks
    # occasionally, never nags. Two phrasings: a calm general one, and a punchier
    # "use it before it resets" on the last day.
    elif (hours_left is not None and (pace - pct7) >= 12
          and (100.0 - pct7) >= 12):
        headroom = 100.0 - pct7
        key = "rate_limit_headroom_near_reset"
        if days_left <= 1.0:
            text = (
                f"Weekly cap resets in ~{hours_left:.0f}h and you're only at {pct7:.0f}% — "
                f"~{headroom:.0f}% headroom left; put it to use before it resets."
            )
            text_he = (
                f"מכסת השבוע מתאפסת בעוד ~{hours_left:.0f} שעות ואתה רק ב-{pct7:.0f}% — "
                f"נשאר ~{headroom:.0f}% מרווח, נצל אותו עד הסוף לפני האיפוס. :)"
            )
        else:
            text = (
                f"You're under an even weekly pace — ~{pace:.0f}% expected by now, you're "
                f"at {pct7:.0f}%. ~{days_left:.0f}d to reset, plenty of headroom."
            )
            text_he = (
                f"אתה מתחת לקצב השבועי האחיד — היו אמורים ~{pace:.0f}% עד עכשיו ואתה "
                f"ב-{pct7:.0f}%. נשארו ~{days_left:.0f} ימים לאיפוס, יש לך מרווח בנוח."
            )
        results.append(Insight(
            text=text,
            text_he=text_he,
            urgency=3,
            novelty=_novelty(key, memory),
            actionability=2,
            uniqueness=5,
            template_key=key,
        ))
        rate_limit_fired = True

    # Tier 4 — 5-HOUR ROLLING NEAR CAP: the short rolling window is hot and none
    # of the weekly tiers above already spoke. A short pause refills it.
    elif pct5 > 85:
        key = "rate_limit_5h_rolling"
        results.append(Insight(
            text=(
                f"5-hour rolling window at {pct5:.0f}% — close to the short-window cap; "
                f"a short pause refills it."
            ),
            text_he=(
                f"חלון 5 השעות המתגלגל ב-{pct5:.0f}% — קרוב לתקרת החלון הקצר; "
                f"הפסקה קצרה ממלאת אותו מחדש."
            ),
            urgency=9,
            novelty=_novelty(key, memory),
            actionability=8,
            uniqueness=10,
            template_key=key,
        ))
        rate_limit_fired = True

    # ── Peak hours + rate limit < 80 % ───────────────────────────────────────
    if not rate_limit_fired and obs.is_peak and max_rl < 80:
        key = "peak_rate_ok"
        results.append(Insight(
            text=f"Historical peak schedule is active in your custom tier. Budget: {max_rl:.0f}% used. "
                 f"Use this as a local schedule cue, not a faster-drain warning.",
            text_he=f"לוח שעות שיא היסטורי פעיל ב-custom tier שלך. Budget: {max_rl:.0f}% בשימוש. "
                    f"תתייחס לזה כסימון לוח זמנים מקומי, לא כאזהרת צריכה מהירה יותר.",
            urgency=7,
            novelty=_novelty(key, memory),
            actionability=5,
            uniqueness=5,
            template_key=key,
        ))

    # ── Cross-CLI usage: capped external provider ────────────────────────────
    external_usage = getattr(obs, "external_usage", []) or []
    if isinstance(external_usage, list):
        capped = []
        for record in external_usage:
            if not isinstance(record, dict):
                continue
            label = _record_label(record)
            five_window = record.get("five_hour")
            five_pct = _usage_pct(five_window)
            if five_pct is not None and five_pct >= 95:
                capped.append((five_pct, label, _window_label(five_window, "5h"), "prompt"))
            weekly_window = record.get("weekly")
            weekly_pct = _usage_pct(weekly_window)
            weekly_label = _window_label(weekly_window, "7d")
            if weekly_pct is not None and weekly_pct >= 95:
                capped.append((weekly_pct, label, weekly_label, "token"))

        if capped:
            pct, label, window, kind = max(capped, key=lambda item: item[0])
            pct_text = f"{pct:.0f}"
            kind_he = "טוקנים" if kind == "token" else "פרומפטים"
            key = "cross_cli_capped"
            results.append(Insight(
                text=(
                    f"{label} {window} quota is maxed ({pct_text}%) — route {kind}-heavy "
                    f"work to another CLI until it resets."
                ),
                text_he=(
                    f"{label} {window} quota מלאה ({pct_text}%) — העבר עבודה עתירת "
                    f"{kind_he} ל-CLI אחר עד שהיא מתאפסת."
                ),
                urgency=7,
                novelty=_novelty(key, memory),
                actionability=8,
                uniqueness=10,
                template_key=key,
            ))

    # ── Cross-CLI usage: offload when Claude weekly is warm ──────────────────
    if isinstance(external_usage, list) and obs.rate_limit_7d_pct >= 60:
        offload_candidates = []
        for record in external_usage:
            if not isinstance(record, dict):
                continue
            windows = []
            five_pct = _usage_pct(record.get("five_hour"))
            weekly_pct = _usage_pct(record.get("weekly"))
            if five_pct is not None:
                windows.append(five_pct)
            if weekly_pct is not None:
                windows.append(weekly_pct)
            if not windows:
                continue
            busiest = max(windows)
            # Only suggest a provider with real headroom on EVERY window — a tool
            # warm on any window (e.g. Codex 5h at 90%) is a bad offload target.
            if busiest > 50:
                continue
            offload_candidates.append((busiest, _record_label(record)))

        if offload_candidates:
            coolest_pct, label = min(offload_candidates, key=lambda item: (item[0], item[1]))
            key = "cross_cli_offload"
            results.append(Insight(
                text=(
                    f"Claude weekly at {obs.rate_limit_7d_pct:.0f}% — offload mechanical "
                    f"passes to {label} ({coolest_pct:.0f}% used) and save Claude for the hard parts."
                ),
                text_he=(
                    f"Claude weekly ב-{obs.rate_limit_7d_pct:.0f}% — העבר משימות מכניות "
                    f"ל-{label} ({coolest_pct:.0f}% בשימוש) ושמור את Claude לחלקים הקשים."
                ),
                urgency=6,
                novelty=_novelty(key, memory),
                actionability=8,
                uniqueness=9,
                template_key=key,
            ))

    # ── Session management templates ──────────────────────────────────────────

    # ── 1. Long session (> 2h) AND context genuinely filling ─────────────────
    # Duration alone is a poor proxy: a 3h session at 19% of a 1M window has no
    # pressure. Gate on real context fill (true window, 1M-aware) so this only
    # fires when older context is actually crowding things out.
    if obs.session_duration_min > 120 and obs.ctx_pct > 60:
        dur_h = int(obs.session_duration_min // 60)
        dur_m = int(obs.session_duration_min % 60)
        key = "long_session"
        results.append(Insight(
            text=(
                f"Long session ({dur_h}h {dur_m}m) and context {obs.ctx_pct:.0f}% full — older "
                f"context is starting to crowd out what matters now. Consider /clear for a clean "
                f"restart if you've moved past the original task."
            ),
            text_he=(
                f"סשן ארוך ({dur_h} שעות {dur_m} דקות) וה-context ב-{obs.ctx_pct:.0f}% — "
                f"מצטבר יותר מדי הקשר ישן. "
                f"כדאי /clear לפתיחה נקייה אם כבר עברת מהמשימה המקורית."
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
                f"Context nearly full ({obs.ctx_pct:.0f}%). Enable auto-compact as a safety net so "
                f"you never hit the limit mid-task — or run /compact now with 'focus on current task' "
                f"to keep more control over what survives (manual preserves the latest pivot better)."
            ),
            text_he=(
                f"Context כמעט מלא ({obs.ctx_pct:.0f}%). הפעל auto-compact כרשת ביטחון כדי לא "
                f"להיתקע באמצע משימה — או הרץ /compact עכשיו עם 'תתמקד במשימה הנוכחית' לשליטה טובה "
                f"יותר על מה שנשמר (ידני שומר טוב יותר את הכיוון האחרון)."
            ),
            urgency=9,
            novelty=_novelty(key, memory),
            actionability=10,
            uniqueness=10,
            template_key=key,
        ))

    # ── 4. Many prompts in session (> 30) AND context genuinely filling ──────
    # Prompt count alone is a poor proxy (30 small edits can sit at 10%). Gate
    # on real context fill so this fires only under actual pressure.
    if obs.prompt_count > 30 and obs.ctx_pct > 60:
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

    # ── 7. CLAUDE.md hygiene (Boris Cherny: ~60 optimal, 200 ceiling) ────────
    if obs.claude_md_lines > 200:
        key = "claude_md_oversized"
        results.append(Insight(
            text=(
                f"CLAUDE.md is {obs.claude_md_lines} lines — past the ~200 ceiling, so rules near "
                f"the bottom get quietly deprioritized. Trim toward ~60 lines and move the rest into "
                f".claude/rules/ with paths: scoping (Boris Cherny / Anthropic guidance)."
            ),
            text_he=(
                f"CLAUDE.md הוא {obs.claude_md_lines} שורות — מעבר לתקרת ~200, וחוקים בתחתית מודחקים "
                f"בשקט. כדאי לקצר ל~60 שורות ולהעביר את השאר ל-.claude/rules/ עם paths: "
                f"(לפי Boris Cherny / Anthropic)."
            ),
            urgency=2,
            novelty=_novelty(key, memory),
            actionability=7,
            uniqueness=9,
            template_key=key,
        ))

    if obs.active_workflow_agents > 0 and obs.subagent_tokens_live > 100_000:
        tok_str = (
            f"{obs.subagent_tokens_live / 1_000_000:.1f}M"
            if obs.subagent_tokens_live >= 1_000_000
            else f"{obs.subagent_tokens_live // 1000}K"
        )
        key = "workflow_background_drain"
        results.append(Insight(
            text=(
                f"Workflows running {obs.active_workflow_agents} agents ({tok_str} ctx) in the background — "
                f"your main context looks clean but account quota is draining. "
                f"Rate-limit bars reflect this, not the cost line."
            ),
            text_he=(
                f"Workflows מריצים {obs.active_workflow_agents} סוכנים ({tok_str} ctx) ברקע — "
                f"ה-context הראשי נראה נקי אבל המכסה נצרכת. "
                f"בר rate-limit משקף את זה, לא שורת העלות."
            ),
            urgency=7,
            novelty=_novelty(key, memory),
            actionability=5,
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
