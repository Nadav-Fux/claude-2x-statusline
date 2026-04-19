# Bug fixes — Saturday peak spillover + numeric spike cleanup

**Date:** 2026-04-19

---

## English

### Bug 1: Saturday peak spillover across timezones

#### The problem

Anthropic's peak pricing runs Saturday 22:00 → Sunday 04:00 UTC. The statusline used `peak_days = ["Sat"]` and checked the user's **local** weekday.

For a user in **UTC+3** (Israel, for example):

```
UTC:   Sat 22:00  →  Sun 04:00
Local: Sun 01:00  →  Sun 07:00
```

On local Sunday 01:00, the user is inside peak hours — but `local_weekday == "Sun"` does not match `peak_days = ["Sat"]`, so the peak indicator never fires. The user gets no warning that they're in the most expensive pricing window of the week.

The same bug applies in reverse for UTC-offset users: they can see a false positive "peak" on Saturday local time when the UTC peak hasn't started yet.

#### The diagram

```
UTC timeline:
  Fri 00:00 ── Sat 00:00 ── Sat 22:00 ─[PEAK]─ Sun 04:00 ── Sun 00:00

UTC+3 local view:
  Fri 03:00 ── Sat 03:00 ── Sun 01:00 ─[PEAK]─ Sun 07:00 ── Mon 03:00
                                          ↑
                            local weekday = Sunday
                            peak_days check = ["Sat"] → NO MATCH → BUG
```

#### The fix

`peak_hours_to_local()` now returns a `peak_day_offset` — the number of calendar days the peak window shifts when converting from UTC to the local timezone. The peak-days check is expanded to cover the full offset range:

```python
# Before:
if local_weekday in peak_days:
    ...

# After:
for offset in range(peak_day_offset + 1):
    adjusted_day = (utc_peak_start_day + offset) % 7
    if adjusted_day == local_weekday:
        in_peak = True
        break
```

This correctly catches the UTC Saturday → local Sunday case for any forward timezone, and the UTC Saturday → local Saturday case for UTC-offset timezones.

---

### Bug 2: Numeric spikes

Four separate places in the codebase could produce absurd numbers. Each is documented below.

#### 2a. Session burn rate: `$1,249,986/hr`

**Cause:** on sessions under 1 minute, `elapsed_seconds` was very small (e.g., 8 seconds). Dividing session cost by 8 seconds and multiplying by 3600 produced enormous numbers.

```python
# Bad (before):
rate = (total_cost / elapsed_seconds) * 3600  # elapsed_seconds could be 8

# Fixed:
if elapsed_seconds < 60:
    rate = None  # don't show rate yet
elif rate > 200:
    rate = 200   # hard cap
```

#### 2b. Cost milestone extrapolation: `$55B projected`

**Cause:** the milestone banner computed a "projected daily cost" using the unsanitized burn rate. If the rate was `$1.2M/hr`, the daily projection became `$28.8M` — rendered in the banner as a nonsensical number.

**Fix:** milestone extrapolation now uses the sanitized burn rate (capped at $200/hr). If no valid rate is available, projection is omitted from the banner.

#### 2c. Cache savings percentage: `29,647,800%`

**Cause:** a division bug where `cache_savings_pct` was computed as:

```python
saved_tokens / fresh_cost_per_token  # accidentally divided by cost, not tokens
```

This produced values in the millions on high-cache sessions.

**Fix:** rewritten to:

```python
cache_savings_pct = min(90, (cache_read_tokens / max(1, total_input_tokens)) * 100)
```

Clamped 0–90% (theoretical max for Anthropic's cache pricing).

#### 2d. Rolling rate spike: `$813/hr` on 30-second windows

**Cause:** the rolling window allowed any span ≥ 1 sample. A single expensive prompt in a 30-second window produced absurd hourly projections.

**Fix:** two guards applied together:
1. Minimum 3-minute span before a rolling rate is shown.
2. Any computed rolling rate > $200/hr is clamped.

#### Summary table

| Bug                         | Observed value       | Fix                                  |
|-----------------------------|----------------------|--------------------------------------|
| Session burn rate (short)   | `$1,249,986/hr`      | Require ≥ 1-min session              |
| Cost extrapolation          | `$55B projected`     | Use sanitized rate, omit if invalid  |
| Cache savings pct           | `29,647,800%`        | Fix division, clamp 0–90%            |
| Rolling rate (short window) | `$813/hr`            | 3-min min span + $200/hr cap         |

---

<div dir="rtl">

## עברית

### באג 1: שבת peak overflow בין אזורי זמן

**הבעיה**: peak pricing של Anthropic רץ שבת 22:00 → ראשון 04:00 UTC. הקוד הישן בדק את היום המקומי של המשתמש. משתמש ב-UTC+3 נכנס ל-peak ביום ראשון המקומי — אבל `peak_days = ["Sat"]` לא מכיל `"Sun"`, אז אין אזהרה.

**התיקון**: `peak_hours_to_local()` מחזירה עכשיו `peak_day_offset` — כמה ימים קלנדריים ה-peak window זז מ-UTC לשעון המקומי. בדיקת ה-peak מכסה את כל ה-offset range.

### באג 2: ספייקים נומריים

**ארבעה מקרים שתוקנו:**

- **`$1,249,986/hr`** — סשן של 8 שניות חילק בזמן קטן מאוד. תיקון: require ≥ 1 דקה + hard cap של $200/hr.
- **`$55B projected`** — banner של milestone השתמש ב-rate לא מסונטז. תיקון: rate מסונטז בלבד, בלי rate = fallback.
- **`29,647,800%`** — באג חלוקה ב-cache savings. תיקון: נוסחה נכתבה מחדש, clamped 0–90%.
- **`$813/hr`** על חלון של 30 שניות — תיקון: מינימום ספאן של 3 דקות + hard cap.

כל ארבעת הבאגים האלה נמצאו בטסטים על סשנים אמיתיים ועכשיו נמנעים.

</div>
