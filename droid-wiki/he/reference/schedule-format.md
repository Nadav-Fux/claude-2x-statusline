# פורמט schedule

הקובץ `schedule.json` בשורש ה-repository נשלף על ידי כל שורות הסטטוס הפעילות כל 3 שעות. הוא שולט בתוויות שעות שיא, באנרים, הודעות גרסה ו-feature flags.

## ה-schedule הנוכחי

```json
{
  "v": 5,
  "updated": "2026-06-10",
  "cache_hours": 3,
  "mode": "normal",
  "default_tier": "full",
  "peak": {
    "enabled": true,
    "tz": "UTC",
    "days": [1, 2, 3, 4, 5],
    "start": 13,
    "end": 19,
    "label_peak": "Peak",
    "label_offpeak": "Off-Peak",
    "note": "Peak hours removed 2026-05-06..."
  },
  "labels": {
    "five_hour": "5h interactive",
    "weekly": "weekly interactive"
  },
  "banners": [
    {
      "text": "SDK credit cutover Jun 15 - claim it or claude -p stops",
      "expires": "2026-06-15",
      "color": "red"
    }
  ],
  "release": {
    "latest_version": "2.2.0",
    "minimum_version": "2.1.0",
    "command": "/statusline-update"
  },
  "features": {
    "show_peak_segment": true,
    "show_rate_limits": true,
    "show_timeline": true
  }
}
```

## מראה שדות

### שדות ברמה העליונה

| שדה | סוג | תיאור |
|-------|------|-------------|
| `v` | number | גרסת סכמה‏ (נכון לעתה 5) |
| `updated` | string | תאריך בו schedule זה שונה לאחרונה‏ (YYYY-MM-DD) |
| `cache_hours` | number | משך מטמון מוצע ללקוחות |
| `mode` | string | `"normal"`‏ (ללא throttling בשיא) או `"peak_hours"` |
| `default_tier` | string | Tier מוצע להתקנות חדשות |
| `peak` | object | תצורת חלון שעות שיא |
| `labels` | object | תוויות מותאמות אישית לפלחי rate limit |
| `banner` | object | באנר יחיד מדור קודם‏ (הוצא משימוש, השתמש ב-`banners`) |
| `banners` | array | באנרים פרסומיים פעילים עם תפוגה |
| `release` | object | בדיקת גרסה והודעת עדכון |
| `features` | object | מתגי feature flags לרינדור |

### תצורת peak

| שדה | סוג | תיאור |
|-------|------|-------------|
| `enabled` | boolean | האם פלח peak מרונדר |
| `tz` | string | אזור זמן מקור‏ (למשל `"UTC"`, `"America/Los_Angeles"`) |
| `days` | number[] | ימי השבוע‏ (1=שני עד 5=שישי) |
| `start` | number | שעת התחלה‏ (24ש, באזור הזמן המקור) |
| `end` | number | שעת סיום‏ (24ש, באזור הזמן המקור) |
| `label_peak` | string | טקסט המוצג במהלך שעות שיא |
| `label_offpeak` | string | טקסט המוצג מחוץ לשעות שיא |
| `note` | string | הערה פנימית‏ (אינה מוצגת) |

### פורמט banner

| שדה | סוג | תיאור |
|-------|------|-------------|
| `text` | string | טקסט הודעת הבאנר |
| `expires` | string | תאריך תפוגה‏ (YYYY-MM-DD) |
| `color` | string | `"red"`‏ (דחוף), `"yellow"`‏ (מידע) |

### תצורת release

| שדה | סוג | תיאור |
|-------|------|-------------|
| `latest_version` | string | גרסת השחרור הנוכחית |
| `minimum_version` | string | גרסה מינימלית נדרשת |
| `command` | string | פקודת עדכון להצעה |
| `available_text` | string | הודעה לעדכון אופציונלי |
| `required_text` | string | הודעה לעדכון נדרש |

### Feature flags

| Flag | ברירת מחדל | השפעה |
|------|---------|--------|
| `show_peak_segment` | `true` | מתג פלח שעות שיא |
| `show_rate_limits` | `true` | מתג פסי rate limit |
| `show_timeline` | `true` | מתג timeline של schedule |

## נורמליזציה

המנועים מנרמלים את ה-schedule בעת טעינה, וממלאים שדות חסרים מערכי ברירת מחדל מובנים. schedule null, חסר או פגום נופל ל-`DEFAULT_SCHEDULE` במקום לקרוס.

## דפים קשורים

- [שעות שיא ו-schedule](../features/peak-hours-schedule.md) — כיצד ה-schedule מנוצל
- [הגדרות](configuration.md) — הגדרות מקומיות כולל `schedule_url` ו-`schedule_cache_hours`
