# הגדרות

קובץ ההגדרות הראשי הוא `~/.claude/statusline-config.json`. הוא נוצר על ידי ה-installer ונערך על ידי פקודות slash.

## דוגמה מלאה

```json
{
  "tier": "full",
  "mode": "full",
  "segments": {
    "peak_hours": true,
    "model": true,
    "context": true,
    "workflows": true,
    "git_branch": true,
    "git_dirty": true,
    "cost": true,
    "rate_limits": true,
    "effort": true,
    "env": true,
    "auth_mode": false,
    "sdk_meter": false
  },
  "schedule_url": "https://raw.githubusercontent.com/Nadav-Fux/claude-2x-statusline/main/schedule.json",
  "schedule_cache_hours": 3,
  "telemetry": true,
  "diagnostics": "full"
}
```

## שדות

| שדה | סוג | ברירת מחדל | תיאור |
|-------|------|---------|-------------|
| `tier` | string | `"standard"` | רמת תצוגה: `minimal`,‏ `standard`, או `full` |
| `mode` | string | `"minimal"` | מצב רינדור: `minimal`‏ (שורה 1 בלבד) או `full`‏ (כל שורות הדשבורד) |
| `segments` | object | תלוי ב-tier | עקיפות הפעלה/כיבוי לכל פלח |
| `schedule_url` | string | GitHub raw URL | כתובת URL לשליפת schedule מרוחק |
| `schedule_cache_hours` | number | `3` | שעות בין רענוני schedule |
| `telemetry` | boolean | `true` | הפעלה/כיבוי של כל הטלמטריה |
| `diagnostics` | string | `"full"` | פרטיות דוח doctor: `full`,‏ `minimal`, או `off` |

## מתגי פלחים

ניתן להפעיל או לכבות פלחים בודדים באמצעות אובייקט `segments`. כאשר פלח אינו מופיע ברשימה, קביעת ה-tier קובעת אם הוא ירונדר.

## משתני סביבה

| משתנה | ברירת מחדל | תיאור |
|----------|---------|-------------|
| `STATUSLINE_DEBUG` | unset | הגדר ל-`1` לפלט debug ב-stderr |
| `STATUSLINE_NARRATOR_ENABLED` | `1` | מתג כיבוי של ה-narrator |
| `STATUSLINE_NARRATOR_HAIKU` | `auto` | שכבת Haiku: `auto`,‏ `1`,‏ `0` |
| `STATUSLINE_NARRATOR_HAIKU_INTERVAL_MIN` | `15` | מקסימום דקות בין קריאות Haiku |
| `STATUSLINE_NARRATOR_THROTTLE_MIN` | `5` | מינימום דקות בין פליטות narrator |
| `STATUSLINE_NARRATOR_LANGS` | זיהוי אוטומטי | `en`,‏ `he`, או `en,he` |
| `STATUSLINE_DISABLE_TELEMETRY` | unset | הגדר ל-`1` להשבתת כל הטלמטריה |
| `ANTHROPIC_API_KEY` | unset | מפעיל שכבת narrator של Haiku |
| `CLAUDE_SESSION_ID` | מוגדר על ידי Claude Code | מזהה סשן לרוטציית זיכרון ה-narrator |
| `CLAUDE_PLUGIN_ROOT` | מוגדר על ידי Claude Code | תיקיית שורש הפלאגין לזיהוי hooks |

## קבצים קשורים

| קובץ | מיקום | מטרה |
|------|----------|---------|
| `statusline-config.json` | `~/.claude/` | הגדרות ראשיות (דף זה) |
| `statusline-state.json` | `~/.claude/` | state של חלון מתגלגל (ring buffer של 60 דקות) |
| `statusline-schedule.json` | `~/.claude/` | schedule מרוחק במטמון |
| `narrator-memory.json` | `~/.claude/` | זיכרון ה-narrator בין סשנים |
| `settings.json` | `~/.claude/` | הגדרות Claude Code‏ (סטנזת statusLine, hooks) |
| `.statusline-telemetry-id` | `~/.claude/` | מזהה טלמטריה אנונימי |
| `statusline-usage-cache.json` | `~/.claude/` | מטמון ניצול rate limit‏ (תוסף VS Code) |
