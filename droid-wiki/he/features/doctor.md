# דיאגנוסטיקת דוקטור

## מטרה

הדוקטור הוא כלי אבחון שבודק את תקינות ההתקנה, מסביר מקטעי סטטוס ליין, ויכול לתקן אוטומטית בעיות נפוצות. הוא פועל כסקריפט עצמאי המופעל על ידי פקודת `/statusline-doctor` או ישירות מהטרמינל.

## מצבים

| מצב | פקודה | פלט |
|------|---------|--------|
| אבחון | `doctor.sh` | דוח קריא לאדם עם ספירות עבר/אזהרה/כשל |
| JSON | `doctor.sh --json` | JSON קריא מכונה לכלים |
| תיקון | `doctor.sh --fix` | פרומפטים אינטראקטיביים להחלת תיקונים |
| הסבר הכל | `doctor.sh --explain` | טבלה של כל 18 המקטעים עם תיאורים בני שורה |
| הסבר אחד | `doctor.sh --explain <segment>` | הסבר מפורט: פורמט, חישוב, צבעים, תנאי הסתרה |
| דוח | `doctor.sh --report` | שליחת ping טלמטריה אנונימי (מוצא משימוש, כעת no-op) |

הדוקטור תמיד יוצא עם 0. יציאה שונה מאפס הייתה חוסמת את hooks של Claude Code.

## בדיקות שמבוצעות

ה-`doctor/doctor.sh` בן 1338 השורות בודק:

1. של-`settings.json` יש סטנזת `statusLine`
2. שהסטנזה מצביעה על cc-2x-statusline (לא נחטף על ידי פלאגין אחר, למשל token-optimizer)
3. `PATH=... bash ...` inline env ייחודי ל-Windows (cmd.exe לא יכול לנתח את זה)
4. נוכחות ותקינות JSON של `statusline-config.json`
5. זמינות זמן ריצה של Python / Node / bash (כולל התקנות ניידות)
6. ביצוע dry-run של פקודת statusLine (קוד יציאה, ספירת שורות, מילישניות)
7. ש-git origin מצביע על `Nadav-Fux/claude-2x-statusline`
8. ש-hooks של נרטור מחוברים ב-`settings.json` (מטפל במבנה hook מקונן של Claude Code)
9. פקודות סלאש לכל רמה מיותרות

## מנוע תיקון אוטומטי

`doctor/fixes.sh` מחיל תיקון אחד לכל הפעלה. רמזי תיקון ידועים:

| רמז | מה זה מתקן |
|------|---------------|
| `add-statusline` | ל-`settings.json` אין סטנזת `statusLine` |
| `restore-statusline` | statusLine נחטף על ידי פלאגין אחר |
| `wrap-command` | Windows: הסרת `VAR=val bash ...` inline וניתוב דרך wrapper |
| `create-config` | `statusline-config.json` חסק; כתיבת ברירת מחדל |

כל שינויי `settings.json` אטומיים (כתיבה ל-`.tmp`, שינוי שם על היעד).

## הסברי מקטעים

הדוקטור מאחסן הסברי מקטע מפורטים כמערך אסוציאטיבי של bash (`SEG_DETAIL`). כל רשומה היא מחרוזת מרובת שורות שמכסה:

- **מה זה מציג** — תיאור בשפה טבעית
- **איך זה מחושב** — לוגיקת החישוב
- **ערכי תצוגה** — ערכים אפשריים ומשמעויותיהם
- **צבעים** — מה כל צבע אומר
- **מתי זה מוסתר** — תנאים שמדכאים את המקטע

18 מקטעים מתועדים: `peak_hours`, `model`, `context`, `vim_mode`, `agent`, `workflows`, `git_branch`, `git_dirty`, `cost`, `rate_limits`, `burn_rate`, `cache_hit`, `context_depletion`, `effort`, `env`, `usage_credits`, `auth_mode`, `sdk_meter`.

## קוד דיאגנוסטי

כל הרצת דוקטור (כשטלמטריה מופעלת) מציגה קוד hex יציב לכל מכונה:

```
Diagnostic code: abc12345 (telemetry: full — see README to change privacy)
```

הקוד הזה נגזר מגיבוב חד-כיווני של hostname + username. הוא יציב לאורך הרצות, ומאפשר למתחזק לתאם דוחות מאותה מכונה בלי לזהות את המשתמש.

## רמות פרטיות

| רמה | מה נשלח | מתי |
|-------|----------------|------|
| `full` (ברירת מחדל) | סיכום + דוח מלא מחוטא בעת כשל | אוטומטי |
| `minimal` | סיכום בלבד | אוטומטי |
| `off` | כלום | לעולם לא |

דוחות מלאים מחוטאים בצד הלקוח: נתיבי home הופכים ל-`~/`, שמות משתמש הופכים ל-`<user>`, hostnames הופכים ל-`<host>`. דוחות נמחקים אוטומטית אחרי 30 יום.

## קובצי מקור מרכזיים

| קובץ | מטרה |
|------|---------|
| `doctor/doctor.sh` | מנוע אבחון ראשי (1338 שורות) |
| `doctor/fixes.sh` | החלת תיקונים אוטומטית (215 שורות) |
| `commands/statusline-doctor.md` | הגדרת פקודת סלאש `/statusline-doctor` |
| `commands/explain.md` | הגדרת פקודת סלאש `/explain` |
| `tests/test_doctor.py` | בדיקות בדיקות דוקטור |
| `tests/test_doctor_telemetry.py` | בדיקות טלמטריה וקוד דיאגנוסטי של דוקטור |

## עמודים קשורים

- [טלמטריה](telemetry.md) — כיצד נתוני דיאגנוסטיקה נאספים ומועברים
- [pipeline מתקין](../systems/installer.md) — מה הדוקטור מוודא
- [סיכום קונפיגורציה](../reference/configuration.md) — קובץ קונפיגורציה שהדוקטור בודק
