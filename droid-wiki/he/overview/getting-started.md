# מתחילים

## דרישות קדם

- Claude Code (CLI או טרמינל)
- אחד מאלה: Python 3.9+ (מומלץ, מאפשר את המספר), Node.js (כל גרסת LTS), או Bash 4+
- Git לשכפול המאגר

המתקין מזהה אוטומטית את ה-runtime הזמין והטוב ביותר. Python פותח את חבילת הפיצ'רים המלאה כולל המספר. Node.js מספק שוויון `statusline` מלא בלי המספר. Bash מרנדר `statusline` מינימלי בלבד.

## התקנה

### אפשרות 1: לבקש מ-Claude

להדביק לתוך Claude Code:

```
Install the claude-2x-statusline plugin from github.com/Nadav-Fux/claude-2x-statusline
```

Claude משכפל את המאגר, מריץ את המתקין, שואל איזו רמה אתם רוצים, ומגדיר הכל.

### אפשרות 2: שורה אחת (macOS / Linux)

```bash
git clone https://github.com/Nadav-Fux/claude-2x-statusline.git ~/.claude/cc-2x-statusline && bash ~/.claude/cc-2x-statusline/install.sh
```

### אפשרות 3: Windows (PowerShell)

```powershell
irm https://raw.githubusercontent.com/Nadav-Fux/claude-2x-statusline/main/install.ps1 | iex
```

המתקין כותב את `~/.claude/statusline-config.json`, מעדכן את `~/.claude/settings.json` עם סטנזת ה-`statusLine`, מתקין slash commands, ומושך את ה-schedule המרוחק ההתחלתי. יש להפעיל מחדש את Claude Code כדי להפעיל את התוסף.

## הרצת בדיקות

```bash
# בדיקות Python (מספר, ניקוד, שעות שיא, rolling state, memory וכו')
pip install pytest tzdata
python -m pytest tests/ -v

# בדיקת runtime של Node.js
node --test tests/node-runtime.test.mjs

# בדיקת ה-worker
node --test worker/worker.test.mjs
```

## החלפת רמות

| פקודה | אפקט |
|---------|--------|
| `/statusline-minimal` | תצוגה מינימלית בשורה אחת |
| `/statusline-standard` | תצוגה סטנדרטית בשתי שורות |
| `/statusline-full` | לוח בקרה מלא ב-4 שורות (מומלץ) |

## הגדרות

יש לערוך את `~/.claude/statusline-config.json` כדי לשנות רמה, מקטעים, כתובת schedule או הגדרות טלמטריה. ראו [מראה ההגדרות](../reference/configuration.md) לכל האפשרויות.

## עדכון

יש להריץ את `/statusline-update` בתוך Claude Code, או:

```bash
bash ~/.claude/cc-2x-statusline/update.sh
```

## פתרון בעיות

יש להריץ `/statusline-doctor` כדי לאבחן בעיות נפוצות. ה-doctor בודק את חיווט ה-`settings.json`, זמינות runtime, תקינות ההגדרות, ויכול לתקן בעיות אוטומטית. ראו [אבחון ה-doctor](../features/doctor.md).
