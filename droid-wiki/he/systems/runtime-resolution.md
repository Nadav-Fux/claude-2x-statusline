# Runtime resolution

## מטרה

`lib/resolve-runtime.sh` מוצא מפרש Python או Node.js עובד בכל פלטפורמה. הוא מטפל במקרי קצה ששוברים lookup נאיבי של `command -v`, במיוחד ב-Windows שבו stubs של Microsoft Store מתחזים למפרשים מותקנים.

## סדר רזולוציה

עבור כל סוג מבוקש (`python` או `node`), ה-resolver מנסה:

1. **PATH lookup** — `command -v python3` (או `python`, `node`), תוך דילוג על כל נתיב המכיל `WindowsApps`
2. **מיקומי התקנה ניידת** — בודק ספריות נפוצות עבור התקנות ניידות (רק כאשר PATH לא נותן כלום)

### דחיית stub של Windows Store

ב-Windows, הפקודות `python3` ו-`python` ב-`C:\Users\...\AppData\Local\Microsoft\WindowsApps\` אינן מפרשים אמיתיים. אלו app-execution aliases שפותחים את דיאלוג ההתקנה של Microsoft Store במקום להריץ Python. ה-resolver דוחה מפורשות כל נתיב המכיל `WindowsApps`:

```bash
case "$p" in
    */WindowsApps/*|*\\WindowsApps\\*) continue ;;
esac
```

### בדיקת מיקומי התקנה ניידת

כאשר PATH lookup נכשל, ה-resolver בודק את המיקומים הבאים:

**Python:**
- `~/tools/python-*/python.exe`
- `~/tools/python/python.exe`
- `~/AppData/Local/Programs/Python/Python3*/python.exe`
- `/c/Python3*/python.exe`
- `/c/Program Files/Python3*/python.exe`

**Node.js:**
- `~/tools/node-*/node.exe`
- `~/tools/node/node.exe`
- `~/AppData/Roaming/nvm/v*/node.exe`
- `/c/Program Files/nodejs/node.exe`

## המרת נתיב עבור Windows

ה-resolver ממיר נתיבים בסגנון Windows (`C:\Users\...`) לסגנון MSYS (`/c/Users/...`) עבור התאמת glob:

```bash
case "$home_win" in
    [A-Za-z]:\\*) home_win="/${home_win:0:1}/${home_win:3}"; home_win="${home_win//\\//}" ;;
esac
```

## צרכנים

| צרכן | כיצד משתמש ב-resolver |
|----------|-------------------------|
| `statusline.sh` | בוחר Python או Node עבור ה-engine |
| `hooks/narrator-*.sh` | בוחר Python או Node עבור ה-narrator |
| `install.sh` | מזהה runtime זמין עבור feature gating |
| `doctor/doctor.sh` | בודק זמינות runtime כאבחון |
| `doctor/fixes.sh` | משתמש ב-runtime לתיקוני config |
| `lib/wire-json.sh` | בוחר backend למניפולציית JSON |

## קובצי מקור עיקריים

| קובץ | מטרה |
|------|---------|
| `lib/resolve-runtime.sh` | ה-resolver עצמו (נטען, לא מורץ) |
| `statusline.sh` | צרכן עיקרי |
| `hooks/narrator-prompt-submit.sh` | צרכן dispatch של narrator |
| `hooks/narrator-session-start.sh` | צרכן dispatch של narrator |

## עמודים קשורים

- [Engines](engines.md) — כיצד ה-resolver מזין את dispatch של engines
- [Patterns and conventions](../how-to-contribute/patterns-and-conventions.md) — דפוסי תאימות Windows
