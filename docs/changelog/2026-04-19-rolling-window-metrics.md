# Rolling-window metrics — spending & cache, not lifetime averages

**Date:** 2026-04-19

---

## English

### The problem with lifetime averages

The old burn-rate display showed something like `$6.3/hr`. That figure was computed as:

```
total_session_cost / elapsed_session_seconds * 3600
```

This is nearly useless in practice:

- During an expensive spike, the lifetime average is dragged down by the cheap early prompts.
- During a cheap exploratory session after a heavy one, the average is inflated by old data.
- If you opened Claude Code 6 hours ago and only just started a heavy task, the number is still low, giving no warning.

### The new behavior: 10-minute rolling window

Burn rate is now computed over a **rolling 10-minute window**. The label `(10m)` is always shown inline so the window is never ambiguous:

```
spending $5.4/hr moderate (10m)
```

**Warm-up fallback**: during the first 10 minutes of a session there isn't enough history for a rolling window. The system falls back automatically to `(session)` so there's always a number displayed — never a blank or an error.

```
spending $2.1/hr low (session)
```

### Severity word inline

A severity word — `low`, `moderate`, or `high` — is always rendered inline:

| Word       | Threshold (rolling rate) |
|------------|--------------------------|
| `low`      | < $2/hr                  |
| `moderate` | $2–$10/hr                |
| `high`     | > $10/hr                 |

This matters for users who have color perception differences or are running in a terminal without ANSI color. The meaning is in the text, not just the color.

### Cache segment

The cache display was reworked alongside the rate metrics.

**Active** (tokens being saved right now):

```
cache reuse 96% ↑2.3k saving
```

- `reuse 96%` = 96% of input tokens came from cache (cost ~10% of fresh input)
- `↑2.3k` = tokens saved in the last 5 minutes (the delta, not the lifetime total)
- `saving` = active state, tokens are being reused this window

**Idle** (cache exists but nothing new is being reused):

```
cache reuse 96% idle
```

The word `reuse` was chosen deliberately — it explains the mechanism (token reuse at ~10% of fresh input cost) rather than the opaque term "cache hit rate."

### Spike protection

Previous behavior allowed absurd numbers like `$813/hr` to appear from 30-second windows. Two guards now apply:

1. **Minimum span**: rolling rate requires at least 3 minutes of data. Shorter windows fall back to session rate.
2. **Hard cap**: any computed rate above **$200/hr** is clamped and flagged. This is a sanity cap — legitimate work does not cost $200/hr.

These two rules eliminated all observed cases of 3–4 digit dollar figures in testing.

### Sample storage

Rolling metrics need a history buffer. Storage is at:

```
~/.claude/statusline-state.json
```

Format: a 60-minute ring buffer of cost samples. Each sample is a `{ts, cost, tokens}` object. The file is written **atomically** (write to `.tmp`, then rename) to prevent corruption during concurrent processes.

On startup, if the file is corrupt (malformed JSON, missing fields), the engine discards it and starts fresh — no crash, no hang.

### Live example render

```
── claude ────────────────────────────────────────────────
 ctx  87k/200k ████████░░░░ 43%  3 files
 cost $0.42  spending $5.4/hr moderate (10m)
 cache reuse 96% ↑2.3k saving
 model claude-sonnet-4-5  session 00:47
──────────────────────────────────────────────────────────
```

---

<div dir="rtl">

## עברית

### הבעיה עם ממוצעי חיים

הנוסחה הישנה לקצב שריפה חישבה `$6.3/hr` — עלות כוללת של הסשן חלקי הזמן שעבר. המספר הזה כמעט חסר ערך:

- בזמן ספייק יקר, הממוצע ההיסטורי "מדלל" את הנזק.
- אחרי שעות של עבודה זולה, כל פרומפט חדש נראה יקר יותר ממה שהוא.
- פתחת Claude Code לפני שש שעות ועכשיו התחלת משהו כבד? המספר עדיין נמוך ולא מתריע.

### Rolling window של 10 דקות

מעכשיו קצב השריפה מחושב על **חלון גלילי של 10 דקות**. התווית `(10m)` מופיעה תמיד inline — אין ספק לגבי מה המספר מייצג:

```
spending $5.4/hr moderate (10m)
```

**Warm-up**: ב-10 הדקות הראשונות של סשן אין מספיק היסטוריה. המערכת נופלת אוטומטית ל-`(session)` — תמיד יש מספר, אף פעם לא ריק.

### מילת חומרה inline

`low` / `moderate` / `high` מופיעה ישירות בטקסט. חשוב לאנשים עם ירוד בראיית הצבעים, או לטרמינלים ללא ANSI color — המשמעות נמצאת בטקסט, לא רק בצבע.

### סגמנט ה-cache

`cache reuse 96% ↑2.3k saving` — המילה `reuse` מסבירה את המנגנון בפועל: 96% מה-input tokens הגיעו מ-cache, עלות ~10% ממחיר fresh. ה-`↑2.3k` הוא הדלתא של 5 הדקות האחרונות, לא ה-lifetime.

### הגנה מספייקים

שני גבולות:
1. **ספאן מינימלי**: חלון גלילי דורש לפחות 3 דקות. פחות — חוזרים ל-session rate.
2. **תקרה של $200/hr**: כל מה שמעל זה — מוגבל ומסומן. עבודה לגיטימית לא עולה $200/hr.

### אחסון

`~/.claude/statusline-state.json` — ring buffer של 60 דקות. כתיבה אטומית (קובץ tmp + rename). ב-startup אם הקובץ פגום — מתחילים מאפס, בלי קריסה.

</div>
