# רמות סטטוס ליין

## מטרה

סטטוס הליין מרונדר באחת משלוש רמות, כאשר כל רמה מציגה יותר מידע. מערכת הרמות מאפשרת למשתמשים לאזן בין צפיפות מידע לבין מקום בטרמינל.

## פריסטים לרמות

כל רמה ממופה לרשימת מקטעים המרונדרים בשורה 1. רשימות המקטעים מוגדרות באופן זהה גם ב-`engines/python-engine.py` וגם ב-`engines/node-engine.js`:

| רמה | שורות | מקטעים בשורה 1 | שורות נוספות |
|------|-------|---------------------|-------------|
| `minimal` | 1 | `model`, `context`, `git_branch`, `git_dirty`, `rate_limits`, `env` | אין |
| `standard` | 1-2 | `model`, `context`, `vim_mode`, `agent`, `workflows`, `git_branch`, `git_dirty`, `cost`, `effort`, `env` | פסי מגבלות תעריף |
| `full` | 4 | כמו `standard` בתוספת `usage_credits` | ציר זמן, פסי מגבלות תעריף, מדדי שריפה/מטמון |

רמת `full` מפעילה שלושה מעברי רינדור נוספים בלולאה הראשית:
- **שורה 2**: ציר זמן ויזואלי של לוח הזמנים (`build_timeline`)
- **שורה 3**: פסי מגבלות תעריף (`build_rate_limits_line`)
- **שורה 4**: קצב שריפה, דלדול הקשר, מדדי מטמון (`build_metrics_line`)

שורות 2-4 מוגנות על ידי דגלי תכונות מלוח הזמנים המרוחק (`features.show_timeline`, `features.show_rate_limits`).

## קטלוג מקטעים

המנועים תומכים במקטעים הבאים:

| מקטע | תיאור | רמות |
|---------|-------------|-------|
| `model` | שם המודל הנוכחי עם מחוון מאמץ | כולן |
| `context` | אחוז ניצול חלון הקשר עם קידוד צבעים | כולן |
| `git_branch` | שם ענף ה-git הנוכחי | כולן |
| `git_dirty` | מחוון מלוכלך/נקי (כוכבית או וי) | כולן |
| `rate_limits` | ניצול מגבלות תעריף ל-5 שעות ולשבוע | כולן |
| `env` | מחוון סביבה (מצב אימות, API מול OAuth) | כולן |
| `vim_mode` | מחוון מצב Vim אם פעיל | `standard`, `full` |
| `agent` | מחוון סוכן/כלי פעיל | `standard`, `full` |
| `workflows` | ספירת תת-סוכני workflow חיים ושימוש בטוקנים | `standard`, `full` |
| `cost` | עלות מצטברת של הסשן בדולר | `standard`, `full` |
| `usage_credits` | מד קרדיט SDK | `full` |
| `effort` | רמת מאמץ חשיבה (HI/MED/LO) | `standard`, `full` |

## מצב מול רמה

השדה `mode` ב-`~/.claude/statusline-config.json` שולט האם שורות הדשבורד מרונדרות:

- `mode: "minimal"` — רק שורה 1 מרונדרת, אפילו ברמת `full`
- `mode: "full"` — כל השורות מרונדרות עבור הרמה שנבחרה

זה מאפשר למשתמשים להשתמש בסט המקטעים המלא בשורה 1 בלי שורות הדשבורד שמתחת.

## החלפת רמות

שלוש פקודות סלאש מחליפות רמות מיידית:

- `/statusline-minimal` — כותב `"tier": "minimal", "mode": "minimal"`
- `/statusline-standard` — כותב `"tier": "standard", "mode": "minimal"`
- `/statusline-full` — כותב `"tier": "full", "mode": "full"`

כל פקודה קוראת את `~/.claude/statusline-config.json`, מעדכנת את שדות הרמה והמצב, וכותבת בחזרה.

## רינדור ANSI

מקטעים משתמשים בפלטת צבעים משותפת (ראו [דפוסים ומוסכמות](../how-to-contribute/patterns-and-conventions.md)). פסי מגבלות תעריף משתמשים בתווי בלוק יוניקוד (`▰▱`) כמחווני סוללה ויזואליים. ציר הזמן משתמש בתווים `━` ו-`●` לתצוגה אופקית של לוח הזמנים.

## קובצי מקור מרכזיים

| קובץ | מטרה |
|------|---------|
| `engines/python-engine.py` | הגדרות מקטעים, לולאת רינדור, פריסטים לרמות |
| `engines/node-engine.js` | מימוש שקול ב-Node.js |
| `engines/bash-engine.sh` | גיבוי Bash מינימלי (4 מקטעים בלבד) |
| `config.example.json` | קונפיגורציה לדוגמה עם כל מתגי המקטעים |
| `skills/full/SKILL.md` | מיומנות Claude Code למעבר לרמת `full` |
| `skills/standard/SKILL.md` | מיומנות Claude Code למעבר לרמת `standard` |
| `skills/minimal/SKILL.md` | מיומנות Claude Code למעבר לרמת `minimal` |
