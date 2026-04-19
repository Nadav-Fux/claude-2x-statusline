# `/explain` + doctor — know your statusline

**Date:** 2026-04-19

---

## English

### The problem: segments without documentation

The statusline has 18 segments. Some are self-explanatory (`model`, `session`). Others are not — what exactly is `cache_reuse_pct`? How is `burn_rate` computed? What triggers `peak_price`? None of this was documented in the display itself.

Two new tools fix this.

### `/explain <segment>`

The `/explain` slash command gives a detailed breakdown of any named segment. Example:

```
/explain burn_rate
```

Output:

```
burn_rate — spending rate (rolling 10-min window)

  What it shows:  Cost per hour based on the last 10 minutes of samples.
                  Falls back to session average during warm-up (< 10 min).
  How computed:   (cost_delta / time_delta_seconds) * 3600
  Unit:           USD/hr
  Severity:       low < $2/hr · moderate $2–10/hr · high > $10/hr
  Color:          green (low) · yellow (moderate) · red (high)
  Hides when:     session cost is $0.00 (no tokens consumed yet)
  Label suffix:   (10m) rolling · (session) fallback
  Spike guard:    min 3-min span · $200/hr hard cap
```

Another example:

```
/explain cache_hit
```

Output:

```
cache_hit — cache reuse percentage

  What it shows:  Percentage of input tokens served from Anthropic's
                  prompt cache rather than being processed fresh.
  How computed:   cache_read_tokens / (cache_read_tokens + input_tokens)
  Unit:           0–100%
  State words:    saving (delta > 0 in last 5 min) · idle (no recent delta)
  Delta:          ↑N = tokens saved in last 5 min
  Color:          green ≥ 80% · yellow 40–79% · grey < 40%
  Hides when:     no cache data in API response
  Note:           Cache tokens cost ~10% of fresh input. 96% reuse on a
                  100k-token context = ~$0.08 saved per prompt.
```

### `/explain` with no argument

Without an argument, `/explain` prints a 20-row segment table:

```
/explain
```

Output (truncated):

```
Segment           Description
──────────────────────────────────────────────────────────────────
ctx_tokens        Input tokens used vs. context window limit
ctx_bar           Visual bar for context fill %
ctx_pct           Context fill percentage
ctx_files         Number of files currently in context
cost_total        Cumulative session cost in USD
burn_rate         Rolling 10-min spending rate with severity label
cache_hit         Cache reuse % with delta and state word
cache_delta       Token-save delta for last 5 min
model             Current model name (abbreviated)
session_time      Session elapsed time (HH:MM)
peak_price        Peak-hours pricing indicator (if applicable)
narrator          Last narrator message (from hook)
temperature       Model temperature if non-default
tool_use_count    Number of tool calls this session
compaction_alert  Warning when context > 90%
cost_milestone    Banner when cost crosses $0.10/$0.50/$1/$5
rate_change       Alert when burn rate changes tier
daily_budget      Budget tracker (if configured)
──────────────────────────────────────────────────────────────────
Run /explain <segment> for full details on any segment.
```

### `/statusline-doctor --explain`

The existing `/statusline-doctor` command now accepts `--explain` as a mode flag. It produces the same segment table as `/explain` with no argument, but formatted for terminal output and integrated with the doctor's existing health check:

```
/statusline-doctor --explain
```

This is useful when `--fix` mode has already been run and the user wants to understand what each thing is, without switching to a separate slash command.

### `/statusline-doctor --fix`

Interactive repair for 8 common issues:

| # | Issue | Repair action |
|---|-------|---------------|
| 1 | Hook not registered | Adds `SessionStart` entry to `settings.json` |
| 2 | Engine not found | Runs `lib/resolve-runtime.sh` and patches config |
| 3 | State file corrupt | Deletes `statusline-state.json`, triggers rebuild |
| 4 | Narrator memory corrupt | Deletes `narrator-memory.json`, rebuilds |
| 5 | Config JSON invalid | Shows parse error with line number, prompts re-edit |
| 6 | WindowsApps stub detected | Guides to portable install or Store app unblock |
| 7 | Python stdout encoding error | Sets `PYTHONIOENCODING=utf-8` in hook env |
| 8 | Telemetry blocked by firewall | Verifies endpoint, offers opt-out toggle |

Each repair is confirmed before it runs (`y/n` prompt). `--fix --yes` skips all confirmations for scripted use.

### Segment detail reference (all 18)

For reference, here are all 18 segments with one-line descriptions:

| Segment            | Description                                                  |
|--------------------|--------------------------------------------------------------|
| `ctx_tokens`       | Tokens used vs. limit (e.g., `87k/200k`)                    |
| `ctx_bar`          | ASCII progress bar for context fill                          |
| `ctx_pct`          | Context fill as percentage                                   |
| `ctx_files`        | Files currently loaded in context                            |
| `cost_total`       | Cumulative session cost in USD                               |
| `burn_rate`        | Rolling 10-min rate with severity word                       |
| `cache_hit`        | Cache reuse % with state word (`saving`/`idle`)              |
| `cache_delta`      | Token-save delta for last 5 min (`↑2.3k`)                   |
| `model`            | Current model name                                           |
| `session_time`     | Session elapsed time                                         |
| `peak_price`       | Peak pricing active indicator                                |
| `narrator`         | Latest narrator hook message                                 |
| `temperature`      | Model temperature (hidden when default)                      |
| `tool_use_count`   | Total tool calls this session                                |
| `compaction_alert` | Warning at > 90% context fill                                |
| `cost_milestone`   | Banner at $0.10/$0.50/$1/$5 thresholds                       |
| `rate_change`      | Alert on tier change (low→moderate, moderate→high)           |
| `daily_budget`     | Budget tracker vs. `daily_budget_usd` in config              |

---

<div dir="rtl">

## עברית

### הבעיה: סגמנטים ללא תיעוד

לסטטוסליין יש 18 סגמנטים. חלקם ברורים (`model`, `session`). אחרים לא — מה בדיוק `cache_reuse_pct`? איך מחשבים `burn_rate`? שתי כלים חדשים פותרים את זה.

### `/explain <segment>`

`/explain burn_rate` — מחזיר פירוט מלא: מה המספר מייצג, איך מחושב, יחידות, צבעים, מתי מסתתר, ואיזה spike guards פעילים.

`/explain cache_hit` — מסביר מה המאחוז אומר, מה ה-delta `↑2.3k`, ומה ההפרש בעלות בין cache לפרש.

### `/explain` ללא ארגומנט

מדפיס טבלה של 20 שורות עם תיאור שורה אחת לכל סגמנט. שימושי בפעם הראשונה שמישהו רואה את הסטטוסליין ולא יודע מה כל דבר אומר.

### `/statusline-doctor --explain`

אותה טבלה, מאוחדת בתוך ה-doctor. שימושי אחרי `--fix` כשרוצים להבין מה תוקן ולמה.

### `/statusline-doctor --fix`

תיקון אינטראקטיבי ל-8 בעיות נפוצות: hook לא רשום, engine לא נמצא, קובץ state פגום, memory של narrator פגום, config JSON שבור, WindowsApps stub, בעיית encoding ב-Python, ו-telemetry חסום בפיירוול.

כל תיקון מאושר לפני הריצה. `--fix --yes` עוקף את כל האישורים לשימוש בסקריפטים.

</div>
