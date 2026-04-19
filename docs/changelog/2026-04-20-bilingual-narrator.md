# Bilingual narrator — Hebrew auto-detect and full translation coverage

**Date:** 2026-04-20

---

## English

### Why Hebrew?

GitHub traffic analysis shows the majority of organic installs come from Israeli users. The narrator was already producing useful advisory text, but it was English-only — fine for reading but less natural when your working language is Hebrew. This release makes Hebrew a first-class output mode.

### Locale auto-detect

`_languages()` in `narrator/engine.py` now checks three environment variables in priority order before falling back to English:

| Priority | Source | Condition |
|:---------|:-------|:----------|
| 1 | `STATUSLINE_NARRATOR_LANGS` | Explicit override — always wins |
| 2 | `LC_ALL` | First two chars == `he` → Hebrew |
| 3 | `LC_MESSAGES` | First two chars == `he` → Hebrew |
| 4 | `LANG` | First two chars == `he` → Hebrew |
| 5 | Fallback | English |

If your system is set to `he_IL.UTF-8` (standard Israeli locale), the narrator switches to Hebrew automatically on first run — no configuration needed.

### Three output modes

```bash
# English only (default unless locale is Hebrew)
export STATUSLINE_NARRATOR_LANGS=en

# Hebrew only (default when locale is Hebrew)
export STATUSLINE_NARRATOR_LANGS=he

# Both — two lines per emission, English first
export STATUSLINE_NARRATOR_LANGS=en,he
```

When both languages are selected, the narrator emits two lines separated by a newline:

```
Burning $14.2/hr — at this rate your 5-hour budget ends in ~47m. Consider Sonnet for simple steps.
שורף $14.2/hr — בקצב הזה תגמור את budget 5 השעות בעוד ~47 דקות. שקול Sonnet לצעדים פשוטים.
```

### All templates now have Hebrew

Every insight template in `narrator/scoring.py` carries a `text_he` field. The 12 pre-existing templates now translated:

| Template key | English (excerpt) | Hebrew (excerpt) |
|:-------------|:------------------|:-----------------|
| `ctx_critical` | "Context fills in ~Nm — compact now…" | "ה-context מתמלא תוך ~N דקות — /compact עכשיו…" |
| `ctx_warning` | "Context at ~X% with Nm until full…" | "Context ב-~X% — N דקות עד שהוא מתמלא…" |
| `ctx_80_headroom` | "Context at X% — headroom shrinking…" | "Context ב-X% — המרווח מצטמצם…" |
| `burn_high` | "Burning $X/hr — budget ends in ~Nm…" | "שורף $X/hr — בקצב הזה תגמור את budget…" |
| `burn_moderate` | "Spending $X/hr (10m) — steady pace…" | "מוציא $X/hr (10m) — קצב יציב…" |
| `burn_low` | "Spending $X/hr — cheap session…" | "מוציא $X/hr — סשן זול…" |
| `cache_low` | "Cache hit ratio is X%…" | "אחוז ה-cache hit הוא X%…" |
| `cache_active` | "Cache saving ~Xk tokens / 5 min…" | "Cache חוסך ~Xk טוקנים ב-5 דקות…" |
| `milestone_X` | "You've crossed $X — extrapolates to ~$Y…" | "חצית את ה-$X — בקצב הנוכחי זה מתורגם ל-~$Y…" |
| `rate_limit_high` | "Rate limit at X% — close to cap…" | "ה-rate limit הגיע ל-X%…" |
| `peak_rate_ok` | "Peak hours — rate limits drain faster…" | "שעות שיא — ה-rate limits נצרכים מהר יותר…" |
| `off_peak_wide_open` | "Off-peak with wide-open limits…" | "מחוץ לשעות השיא עם מכסות פתוחות…" |

The 6 session-management templates added in the previous release (`long_session`, `ctx_high_long_session`, `ctx_very_high`, `many_prompts`, `pivot_suggestion`, `subagent_suggestion`) already had `text_he`.

### Translation guidelines

Technical terms that remain in English intentionally: `/compact`, `/clear`, `rewind`, `context`, `token`, `cache`, `Sonnet`, `Opus`, `Haiku`, `subagent`, `budget`, `rate limit`. These are product names and UI keywords — transliterating them would make the message harder to act on.

The translation style is direct and practical: observation → meaning → action, matching the English register. No fluff, no over-explanation.

### Side-by-side example

Given a high-burn, context-filling session:

**English (`STATUSLINE_NARRATOR_LANGS=en`):**
```
⟨ narrator ⟩ Context fills in ~18m — compact now or history gets truncated. · Burning $14.2/hr — at this rate your 5-hour budget ends in ~47m. Consider Sonnet for simple steps.
```

**Hebrew (`STATUSLINE_NARRATOR_LANGS=he`):**
```
⟨ narrator ⟩ ה-context מתמלא תוך ~18 דקות — /compact עכשיו, אחרת ההיסטוריה תיחתך. · שורף $14.2/hr — בקצב הזה תגמור את budget 5 השעות בעוד ~47 דקות. שקול Sonnet לצעדים פשוטים.
```

**Both (`STATUSLINE_NARRATOR_LANGS=en,he`):**
```
⟨ narrator ⟩ Context fills in ~18m — compact now or history gets truncated. · Burning $14.2/hr — at this rate your 5-hour budget ends in ~47m. Consider Sonnet for simple steps.
ה-context מתמלא תוך ~18 דקות — /compact עכשיו, אחרת ההיסטוריה תיחתך. · שורף $14.2/hr — בקצב הזה תגמור את budget 5 השעות בעוד ~47 דקות. שקול Sonnet לצעדים פשוטים.
```

### Note for contributors

The structural test `TestEveryTemplateHasHebrew.test_every_template_has_hebrew` in `tests/test_narrator_scoring.py` will fail if you add a new `Insight` without a `text_he` field. This is intentional — it enforces the bilingual contract. When adding a new template:

1. Add `text_he=f"..."` alongside `text=f"..."`.
2. Keep technical terms (listed above) in English.
3. The test exercises a "universal observation" that triggers every template — make sure your new template's conditions are reachable from it, or add a separate targeted test.

---

<div dir="rtl">

## עברית

### למה עברית?

ניתוח תנועה ב-GitHub מראה שרוב ההתקנות האורגניות מגיעות ממשתמשים ישראלים. ה-narrator כבר ייצר טקסט שימושי, אבל היה באנגלית בלבד. הגרסה הזו הופכת עברית למצב פלט ראשוני מלא.

### זיהוי locale אוטומטי

`_languages()` ב-`narrator/engine.py` בודק שלושה משתני סביבה לפני ש-fallback לאנגלית:

| עדיפות | מקור | תנאי |
|:-------|:-----|:------|
| 1 | `STATUSLINE_NARRATOR_LANGS` | עקיפה ידנית — תמיד מנצחת |
| 2 | `LC_ALL` | מתחיל ב-`he` → עברית |
| 3 | `LC_MESSAGES` | מתחיל ב-`he` → עברית |
| 4 | `LANG` | מתחיל ב-`he` → עברית |
| 5 | ברירת מחדל | אנגלית |

אם המערכת שלך `he_IL.UTF-8` (locale ישראלי סטנדרטי), ה-narrator עובר לעברית אוטומטית — בלי הגדרות.

### שלושה מצבי פלט

```bash
export STATUSLINE_NARRATOR_LANGS=en      # אנגלית בלבד
export STATUSLINE_NARRATOR_LANGS=he      # עברית בלבד
export STATUSLINE_NARRATOR_LANGS=en,he   # שתי שורות — אנגלית ואחריה עברית
```

### כל התבניות עכשיו בעברית

כל `Insight` ב-`narrator/scoring.py` נושא `text_he`. 12 התבניות הישנות תורגמו. 6 תבניות ניהול הסשן שנוספו לאחרונה כבר היו מתורגמות.

מונחים טכניים שנשארו באנגלית בכוונה: `/compact`, `/clear`, `rewind`, `context`, `token`, `cache`, `Sonnet`, `Opus`, `Haiku`, `subagent`, `budget`, `rate limit`.

### הערה לתורמים

בדיקת המבנה `TestEveryTemplateHasHebrew.test_every_template_has_hebrew` תיכשל אם תוסיף `Insight` חדש בלי `text_he`. זה מכוון — היא אוכפת את החוזה הדו-לשוני. בעת הוספת תבנית חדשה: הוסף `text_he=f"..."` ביחד עם `text=f"..."`, ושמור מונחים טכניים באנגלית.

</div>
