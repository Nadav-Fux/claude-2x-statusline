# claude-2x-statusline

תוסף `statusline` מודולרי ל-Claude Code שמציג לוח בקרה חי בטרמינל עם מידע על המודל, ניצולת הקונטקסט, מגבלות הקצב, עלות הסשן, קצב שריפת הטוקנים, יעילות המטמון (cache) ומצב ה-`git`. בנוסף, המערכת כוללת מנגנון מספר (narrator) שמזריק המלצות ניהול קונטקסט בשפה טבעית מעל שורת הפקודה של המשתמש.

## מה התוסף עושה

במבט ראשון, ה-`statusline` מציג את כל מה שמשתמש Claude Code צריך כדי לנהל את הסשן שלו: איזה מודל פעיל, כמה קונטקסט נותר, האם מגבלות הקצב מתקרבות, כמה עלה הסשן, כמה מהר נשרפים טוקנים, והאם המטמון מנוצל ביעילות.

הפיצ'ר הכי חזק הוא עדכוני מדיניות מרחוק. קובץ `schedule.json` שמתארח ב-GitHub שולט בתוויות שעות השיא, באנרים פרסומיים והודעות על גרסאות חדשות. כשמתחזק הפרויקט מעדכן את הקובץ, כל הסטטוסליינים הפעילים קולטים את השינוי תוך 3 שעות, בלי צורך ב-`git pull` או התקנה מחדש.

המספר (narrator) הוא שכבה שנייה שיושבת מעל שורת הפקודה. הוא קורא את אותן מדידות שה-`statusline` מציג ומייצר תובנה קצרה בשפה טבעית, למשל: "Burning $18/hr, your 5-hour budget ends in ~40 min, consider Sonnet for simple steps." מנוע כללים מטפל במקרים הנפוצים בפחות מ-50ms. שכבת LLM אופציונלית מבוססת Haiku מוסיפה נרטיב עשיר יותר כשיש מפתח API של Anthropic זמין.

## למי זה מיועד

מפתחים שמשתמשים ב-Claude Code בטרמינל ורוצים נראות לכלכלת הסשן ולמגבלות הקצב. התוסף עובד על macOS, Linux ו-Windows, עם תוסף וי-אס-קוד נלווה למשתמשי Cursor, Windsurf ו-Antigravity.

## קישורים מהירים

- [ארכיטקטורה](architecture.md) ו[מתחילים](getting-started.md)
- [רמות ה-statusline](../features/statusline-tiers.md) ו[מדדים מתגלגלים](../features/rolling-metrics.md)
- [מערכת המספר](../features/narrator.md) ו[אבחון ה-doctor](../features/doctor.md)
- [ארכיטקטורת המנועים](../systems/engines.md) ו[זיהוי ה-runtime](../systems/runtime-resolution.md)
- [worker הטלמטריה](../apps/telemetry-worker.md) ו[תוסף ה-VS Code](../apps/vscode-extension.md)
- [מראה ההגדרות](../reference/configuration.md) ו[פורמט ה-schedule](../reference/schedule-format.md)
