# Narrator hook — a co-pilot above the prompt

**Date:** 2026-04-19

---

## English

### Why the old line 5 was dropped

The original statusline had a fifth line that restated what was already on line 4 in slightly different words. It was verbose, it competed with line 4 for attention, and it didn't add meaning. It was removed.

The real narrator lives somewhere more useful: **above the user's next prompt**, injected via the `SessionStart` hook — the same mechanism that `borg /recall` uses to surface memory into the response stream.

### Hook mechanism

The hook emits a structured directive:

```
⟨ narrator ⟩ High context + active cache — extract before compaction. Cost velocity: $5.4/hr and climbing.
```

Claude Code captures this text and renders it at the top of its next response. The user sees it inline without any special UI — it's just text, but it arrives at the right moment.

### Two tiers, both additive

The narrator is **always on**. It has two layers:

#### Tier 1: Rules engine (always active)

A local scoring pass over the current session state. Four axes:

| Axis           | What it measures                                       |
|----------------|--------------------------------------------------------|
| **Urgency**    | Time pressure — context nearing limit, high burn rate  |
| **Novelty**    | Is this observation new vs. what was last narrated?    |
| **Actionability** | Can the user do something about it right now?       |
| **Uniqueness** | Is this different from the prior narrator message?     |

Each axis scores 0–3. Top 2 insights are selected and joined with ` · `:

```
Context 87% full — consider /compact · Cache active, 96% reuse saving $0.08 this window
```

The rules engine has no API cost. It fires on every `SessionStart` and `UserPromptSubmit`.

#### Tier 2: Haiku layer (opt-in, auto-enabled)

When `ANTHROPIC_API_KEY` is present in the environment, the Haiku layer activates automatically. It calls **claude-haiku-4-5** and adds 25–35 words of narrative context:

```
⟨ narrator ⟩ You're deep into a refactor — context is 87% full and the cache is working well. This is a good time to extract the current state before it compacts.
```

**Firing conditions** (both must pass):
- Every 5 prompts **or** 15 minutes have elapsed since the last Haiku call
- The session has at least $0.01 in cost (avoids firing on cold starts)

**Cost**: ~$0.0005/call. Average usage is roughly 2–3 calls/day = **~$0.06/week**. This is disclosed upfront and opt-outable.

To disable the Haiku layer while keeping the rules engine:

```json
// ~/.claude/statusline-config.json
{
  "narrator": {
    "haiku_enabled": false
  }
}
```

### Session memory

```
~/.claude/narrator-memory.json
```

| Field                 | Retention     | Purpose                              |
|-----------------------|---------------|--------------------------------------|
| `observations`        | 2-hour rolling | Recent session state snapshots       |
| `delivered_narratives`| Last 8        | Prevents repeating the same message  |
| `cost_milestones`     | Per-session   | Tracks when $X thresholds were hit   |
| `prompt_count`        | Per-session   | Triggers Haiku every 5 prompts       |
| `prior_sessions`      | Last 3        | Cross-session continuity             |

Cross-session: the last 3 sessions are retained so the narrator can open with context like "yesterday you were mid-refactor on the auth module."

### When it fires

| Event               | Tier       | Throttle                   |
|---------------------|------------|----------------------------|
| `SessionStart`      | Rules + Haiku | No throttle (session start) |
| `UserPromptSubmit`  | Rules      | Fires every prompt          |
| `UserPromptSubmit`  | Haiku      | ≥5 min since last call      |

### Example narrator outputs

**Critical context:**
```
⟨ narrator ⟩ Context window 94% full — next compaction will drop 60k tokens. Suggest /compact now or extract key state manually.
```

**High burn rate:**
```
⟨ narrator ⟩ Burn rate hit $12/hr (high) in the last 10 min — cache reuse is 34%, lower than usual. Large fresh inputs suspected.
```

**Cache actively saving:**
```
⟨ narrator ⟩ Cache working well this session: 96% reuse, $0.31 saved so far. Rolling rate $3.2/hr moderate.
```

**Off-peak quiet session:**
```
⟨ narrator ⟩ Low-cost session, $0.04 in 20 min. Context at 12%, cache cold. Good time for exploratory work.
```

**Cross-session continuity (Haiku):**
```
⟨ narrator ⟩ Picking up from yesterday — you were debugging the narrator hook firing logic. Context starts clean, $0 so far.
```

### `/narrate` slash command

`/narrate` bypasses all throttles and fires the narrator immediately. Useful when you want a manual check-in without waiting for the next scheduled fire.

```
/narrate
```

### Language support

The narrator ships with full bilingual support (English + Hebrew). Language is auto-detected from your system locale (`$LC_ALL` / `$LC_MESSAGES` / `$LANG`): if the locale starts with `he`, the narrator speaks Hebrew; otherwise English. Override with `STATUSLINE_NARRATOR_LANGS`. See [2026-04-20 — Bilingual narrator](2026-04-20-bilingual-narrator.md) for the full write-up.

### Environment variables

| Variable                      | Default | Effect                                  |
|-------------------------------|---------|------------------------------------------|
| `STATUSLINE_NARRATOR`         | `1`     | Set to `0` to disable narrator entirely  |
| `STATUSLINE_NARRATOR_HAIKU`   | auto    | Set to `0` to disable Haiku layer only   |
| `STATUSLINE_NARRATOR_INTERVAL`| `5`     | Prompts between Haiku calls              |
| `STATUSLINE_NARRATOR_WINDOW`  | `15`    | Minutes between Haiku calls              |

---

<div dir="rtl">

## עברית

### למה שורה 5 נמחקה

שורה 5 המקורית חזרה על מה שכבר היה בשורה 4, בניסוח קצת שונה. ביטלנו אותה.

ה-narrator האמיתי חי במקום שיותר שימושי: **מעל הפרומפט הבא של המשתמש**, מוזרק דרך hook של `SessionStart` — אותו מנגנון שבו משתמש `borg /recall` כדי לטעון זיכרון לתוך זרם התגובה.

### מנגנון ה-hook

ה-hook פולט directive:

```
⟨ narrator ⟩ Context גבוה + cache פעיל — כדאי לחלץ לפני compaction. קצב עלות: $5.4/hr ועולה.
```

Claude Code תופס את הטקסט ומציג אותו בראש התגובה הבאה — ללא UI מיוחד, רק טקסט, אבל מגיע בזמן הנכון.

### שני שכבות, שתיהן additive

ה-narrator תמיד פעיל. יש לו שתי שכבות:

**Rules engine** (תמיד): pass מקומי על מצב הסשן. ארבעה צירים — urgency, novelty, actionability, uniqueness. כל ציר 0–3. שני ה-insights הכי גבוהים מחוברים עם ` · `. אין עלות API.

**Haiku layer** (opt-in, מופעל אוטומטית): כש-`ANTHROPIC_API_KEY` קיים בסביבה, מופעל `claude-haiku-4-5` כל 5 פרומפטים או 15 דקות. מוסיף 25–35 מילים של נרטיב. עלות ~$0.0005 לקריאה, ממוצע ~$0.06 לשבוע. פתוח, מוצהר, ניתן לכיבוי.

### זיכרון סשן

`~/.claude/narrator-memory.json` — observations של שעתיים אחורה, 8 narratives אחרונים (מניעת חזרות), cost milestones, ספירת פרומפטים, ו-3 סשנים קודמים לרצף חוצה-סשן.

### `/narrate`

עוקף את כל ה-throttles ומפעיל את ה-narrator מיד. שימושי כשרוצים check-in ידני.

### תמיכת שפות

ה-narrator תומך בעברית ואנגלית. זיהוי אוטומטי מה-locale של המערכת (`$LANG` / `$LC_ALL`): אם מתחיל ב-`he` — עברית; אחרת אנגלית. עקיפה עם `STATUSLINE_NARRATOR_LANGS`. פרטים נוספים: [2026-04-20 — Bilingual narrator](2026-04-20-bilingual-narrator.md).

</div>
