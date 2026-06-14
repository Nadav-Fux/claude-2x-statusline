# Engines

## מטרה

שלוש הטמעות עצמאיות של renderer שורת המצב, כל אחת מכוונת ל-runtime אחר. הן אינן מורבדות זו על זו. ה-dispatcher בוחר אחת על בסיס מה שזמין במכונה.

## זרימת dispatch

`statusline.sh` הוא נקודת הכניסה. הוא טוען את `lib/resolve-runtime.sh` ומנסה מפרשים לפי סדר עדיפות:

```bash
PY=$(resolve_runtime python)
NODE=$(resolve_runtime node)

if [ -n "$PY" ]; then
    exec "$PY" "$SCRIPT_DIR/engines/python-engine.py" "$@"
elif [ -n "$NODE" ]; then
    exec "$NODE" "$SCRIPT_DIR/engines/node-engine.js" "$@"
else
    exec bash "$SCRIPT_DIR/engines/bash-engine.sh" "$@"
fi
```

Claude Code מעביר אובייקט JSON ב-stdin המכיל metadata של הסשן. ה-engine שנבחר קורא אותו, מרנדר פלט עם צבעי ANSI, וכותב ל-stdout.

## השוואת engines

| היבט | Python | Node.js | Bash |
|--------|--------|---------|------|
| קובץ | `engines/python-engine.py` | `engines/node-engine.js` | `engines/bash-engine.sh` |
| שורות | 1670 | 915 | 406 |
| מקטעים | כולם | כולם | 4 בלבד (peak, model, context, git) |
| מדדים מתגלגלים | כן | כן | לא |
| תמיכה ב-narrator | כן (דרך package `narrator/`) | כן (דרך `narrator-narrator-node.js`) | לא |
| שליפת schedule | כן | כן | כן (מינימלי) |
| Telemetry | כן | כן | כן |
| תצוגת מגבלות קצב | כן | כן | לא |

## פנימיות Python engine

`engines/python-engine.py` הוא ההטמעה העיקרית. מקטעים עיקריים:

1. **קבועי ANSI** — פלטת צבעים משותפת
2. **קבועות tier** — רשימות מקטעים ל-minimal/standard/full
3. **טיפול ב-schedule** — שליפה, מטמון, נורמליזציה, המרת אזור זמן
4. **renderer-ים של מקטעים** — פונקציות נפרדות לכל מקטע (`render_model`, `render_context`, `render_cost` וכו')
5. **בונה ציר זמן** — פס schedule אופקי עם סמן מיקום
6. **שורת מגבלות קצב** — ויזואליזציית פס סוללה למגבלות 5h ושבועיות
7. **שורת מדדים** — קצב שריפה, דלדול context, שימוש חוזר במטמון
8. **לולאה ראשית** — קריאת JSON מ-stdin, טעינת config, רינדור מקטעים, הוספת דגימה מתגלגלת, פלט

ה-engine מייבא ספריות משותפות מ-`lib/`:
- `rolling_state` לקצב שריפה ומדדי מטמון
- `workflows` לזיהוי subagent חי

## פנימיות Node.js engine

`engines/node-engine.js` משקף את מבנה ה-Python engine. הוא מייבא את `lib/rolling_state.js` עבור החלון המתגלגל. ה-Node.js engine קיים עבור סביבות שבהן Python אינו זמין אך Node.js מותקן (נפוץ בסביבות פיתוח כבדות JavaScript).

## פנימיות Bash engine

`engines/bash-engine.sh` הוא ה-fallback האחרון. הוא מרנדר רק שעות peak, model, context, ענף git ו-git dirty. הוא כולל את ה-cascade שלו ליצירת telemetry ID ולוגיקת heartbeat. ללא מדדים מתגלגלים, ללא מגבלות קצב, ללא narrator.

## טעינת config

כל ה-engines קוראים את `~/.claude/statusline-config.json` עבור tier, mode, מתגי מקטעים, כתובת schedule והגדרות telemetry. config חסר או לא תקין נופל לברירת מחדל. השדה `tier` בוחר את preset המקטעים; `mode` שולט אם שורות dashboard מרונדרות.

## שליפת schedule

ה-engines של Python ו-Node שולפים `schedule.json` מהכתובת שהוגדרה (ברירת מחדל: GitHub raw). השליפה ממוטמנת ב-`~/.claude/statusline-schedule.json` עם TTL הניתן להגדרה (ברירת מחדל 3 שעות). כשלי שליפה נופלים למטמון או ל-`DEFAULT_SCHEDULE` המובנה. ראו [peak hours and schedule](../features/peak-hours-schedule.md).

## קובצי מקור עיקריים

| קובץ | שורות | מטרה |
|------|-------|---------|
| `statusline.sh` | 23 | נקודת כניסה ו-dispatcher של runtime |
| `engines/python-engine.py` | 1670 | Engine עיקרי עם כל התכונות |
| `engines/node-engine.js` | 915 | הטמעת parity ל-Node.js |
| `engines/bash-engine.sh` | 406 | Fallback מינימלי ל-Bash |

## עמודים קשורים

- [Runtime resolution](runtime-resolution.md) — כיצד ה-dispatcher מוצא מפרשים
- [Shared libraries](shared-libraries.md) — מצב מתגלגל וזיהוי workflow
- [Statusline tiers](../features/statusline-tiers.md) — מערכת מקטעים ורינדור
