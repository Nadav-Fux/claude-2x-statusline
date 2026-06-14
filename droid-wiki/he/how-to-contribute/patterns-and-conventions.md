# תבניות ומוסכמות

## לעולם לא לקרוס את הקורא

כל מנוע, hook וסקריפט עוטף את הלוגיקה שלו בטיפול בשגיאות שנכשל בשקט. ה-statusline רץ כתהליך בן של Claude Code; קריסה תשבית את ה-session של המשתמש. תבנית זו מופיעה בכל מקום:

- `engines/python-engine.py` עוטף את כל rendering ה-segments ב-try/except
- `narrator/engine.py` תופס את כל החריגות ומחזיר `None`
- `hooks/narrator-*.sh` תמיד מסתיים ב-exit 0
- `doctor/doctor.sh` תמיד מסתיים ב-exit 0 (ערך שונה מאפס יחסום session hooks)
- פונקציות שמירת rolling state מדלגות בשקט על כשל בכתיבה

## כתיבה אטומית של קבצים

קבצי state (`statusline-state.json`, `narrator-memory.json`, `settings.json`) נכתבים אטומית: כותבים לקובץ `.tmp`, ואז `os.replace()` (Python) או `fs.renameSync()` (Node.js) מחליף את היעד. זה מונע פגם אם התהליך מופרע באמצע הכתיבה.

## זהות בין שלושה מנועים

מנועי Python ו-Node.js חייבים להישאר מסונכרנים. הגדרות segments, presets של tier, פענוח schedule ולוגיקת rolling-state זהים מבחינה מושגית בין `engines/python-engine.py` ל-`engines/node-engine.js`. מנוע Bash מצומצם בכוונה (peak hours, model, context, git בלבד). בעת הוספת תכונה, ממשו אותה גם ב-Python וגם ב-Node.js.

## תמיכה דו-לשונית

כל טקסט הפונה למשתמש תומך באנגלית ובעברית. ה-narrator מזהה locale ממשתני הסביבה `$LANG`/`$LC_ALL`/`$LC_MESSAGES`. כל תבנית ניקוד ב-`narrator/scoring.py` נושאת שדה `text_he`. ניתן לעקוף עם `STATUSLINE_NARRATOR_LANGS=en`, `=he`, או `=en,he`.

## תאימות ל-Windows

- דחו stubs של app-execution alias של Microsoft Store (`WindowsApps/*.exe`) ב-`lib/resolve-runtime.sh`
- בדקו מיקומי התקנה ניידים (`~/tools/python-*/`, `AppData/Local/Programs/Python/`)
- המירו נתיבי MSYS באמצעות `cygpath -w` בסקריפטי hook
- אלצו UTF-8 ב-stdout כדי למנוע קריסות encoding של cp1252

## מוסכמות צבע ANSI

כל שלושת המנועים חולקים את אותה פלטת צבעי ANSI:

| קבוע | קוד | שימוש |
|----------|------|-------|
| `RST` | `\033[0m` | Reset |
| `BOLD` | `\033[1m` | הדגשה |
| `DIM` | `\033[2m` | מידע משני |
| `GREEN` | `\033[32m` | תקין / off-peak |
| `YELLOW` | `\033[33m` | אזהרה / peak |
| `RED` | `\033[31m` | קריטי / שגיאה |
| `CYAN` | `\033[36m` | מידע / model |
| `BG_GREEN` | `\033[38;5;255;48;5;28m` | תג ירוק |
| `BG_YELLOW` | `\033[38;5;16;48;5;220m` | תג צהוב |
| `BG_RED` | `\033[38;5;255;48;5;124m` | תג אדום |

## שקיפות טלמטריה

טלמטריה היא opt-out, לא opt-in, אך ה-payload מינימלי ומתועד. שלוש רמות פרטיות: `full` (ברירת מחדל, כולל דוחות doctor מטוהרים), `minimal` (תקציר בלבד), `off` (כלום לא נשלח). כל ההגשות מטוהרות בצד הלקוח לפני upload. ראו [טלמטריה](../features/telemetry.md).

## Spike guards

חישובי rolling-rate כוללים בדיקות שפיות למניעת ערכים אבסורדיים מפגימת התצוגה:

- טווח חלון מינימלי: 3 דקות (180 שניות) לפני שניתן לסמוך על קצב
- קצב מקסימלי סביר: $200/hr (כל דבר גבוה יותר נחשב ל-spike)
- delta עלות שלילי מחזיר `None` (איפוס session או פגם)
- delta של cache דורש לפחות 60 שניות span
