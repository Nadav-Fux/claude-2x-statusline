# Installer pipeline

## מטרה

הגדרה חוצת-פלטפורמות שמזהה את ה-runtime, שואלת העדפת tier, כותבת config, מחברת hooks ל-`settings.json`, מתקינה פקודות slash, ושולפת schedule ראשוני. הטמעות נפרדות ל-bash (macOS/Linux) ו-PowerShell (Windows).

## זרימת התקנה (install.sh)

ה-`install.sh` בן 611 השורות עושה:

1. **פרסור ארגומנטים** — דגלי `--tier`, `--update`, `--quiet`
2. **זיהוי runtime** — טעינת `lib/resolve-runtime.sh`, בדיקת Python 3.9+ מול Python ישן מול Node מול Bash
3. **העתקת קבצים** — clone או העתקה של ה-repo ל-`~/.claude/cc-2x-statusline/`
4. **שאלת tier** — prompt אינטראקטיבי (או שימוש בדגל `--tier`)
5. **כתיבת config** — `~/.claude/statusline-config.json` עם tier, mode וכתובת schedule שנבחרו
6. **חיבור settings.json** — הוספת סטנזת `statusLine` דרך `lib/wire-json.sh` (אטומית)
7. **חיבור hooks** — הוספת narrator hooks לסעיף hooks ב-`settings.json`
8. **התקנת פקודות** — העתקת קובצי `.md` של פקודות או רישום plugin
9. **שליפת schedule** — הורדת `schedule.json` ל-`~/.claude/statusline-schedule.json`
10. **התקנת תוסף VS Code** — זיהוי עורכים נתמכים, התקנת תוסף
11. **שליחת telemetry** — ping התקנה עם engine, tier, OS
12. **הדפסת סיכום** — runtime שנבחר, tier שנבחר, תזכורת הפעלה מחדש

## זרימת התקנה (install.ps1)

ה-installer של PowerShell (`install.ps1`, 535 שורות) משקף את זרימת bash. הוא מטפל בשיקולים ספציפיים ל-Windows:

- מוצא Python דרך רישום ונתיבי התקנה נפוצים
- דוחה stubs של Microsoft Store
- משתמש ב-`lib/Wire-Json.ps1` למניפולציה של settings.json
- מזהה VS Code, Cursor, Windsurf, Antigravity דרך `--list-extensions`

## זרימת עדכון

`update.sh` (ו-`update.ps1`) מבצעים עדכונים במקום:

1. `cd` לספריית ההתקנה
2. `git pull origin main`
3. הרצת installer מחדש במצב `--update --quiet`
4. דיווח שינוי גרסה

הפקודה `/statusline-update` מפעילה את הזרימה הזו.

## זרימת הסרה

`uninstall.sh` מסיר את כל העקבות:

1. הסרת ספריית `~/.claude/cc-2x-statusline/`
2. הסרת `~/.claude/statusline-config.json`
3. הסרת `~/.claude/statusline-schedule.json`
4. הסרת פקודות slash מ-`~/.claude/commands/`
5. הסרת מפתח `statusLine` מ-`settings.json`
6. הסרת רשומת `enabledPlugins` מ-`settings.json`
7. הסרת narrator hooks מ-`settings.json`
8. הסרת תוסף VS Code (לולאה על `code`, `cursor`, `windsurf`, `agy`)
9. הסרת קובץ telemetry ID

כל שינויי `settings.json` אטומיים. סקריפט ההסרה נבדק וכל הפערים תוקנו (ראו `UNINSTALL-GAPS.md`).

## חיווט settings.json

ה-installer כותב את הסטנזה הבאה ל-`~/.claude/settings.json`:

```json
{
  "statusLine": {
    "type": "command",
    "command": "bash /path/to/cc-2x-statusline/statusline.sh"
  }
}
```

חיווט hooks מוסיף רשומות למערכי `hooks.SessionStart` ו-`hooks.UserPromptSubmit`, תוך שימוש בפורמט wrapper של `{type: "command", command: "..."}`.

## קובצי מקור עיקריים

| קובץ | שורות | מטרה |
|------|-------|---------|
| `install.sh` | 611 | Installer ל-Bash (macOS/Linux) |
| `install.ps1` | 535 | Installer ל-PowerShell (Windows) |
| `uninstall.sh` | ~100 | סקריפט הסרה |
| `update.sh` | ~40 | updater ל-Bash |
| `update.ps1` | ~50 | updater ל-PowerShell |
| `lib/wire-json.sh` | 365 | מניפולציית JSON ל-bash |
| `lib/Wire-Json.ps1` | 213 | מניפולציית JSON ל-PowerShell |
| `bin.js` | 35 | wrapper של npx שמריץ installer מתאים לפלטפורמה |

## עמודים קשורים

- [Runtime resolution](runtime-resolution.md) — כיצד ה-installer מזהה מפרשים
- [Doctor diagnostics](../features/doctor.md) — מאמת תוצאות installer
- [Hooks and commands](hooks-and-commands.md) — מה ה-installer מחבר
- [Getting started](../overview/getting-started.md) — הוראות התקנה למשתמש
