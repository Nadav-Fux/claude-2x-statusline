# דיבאגינג

## ה-statusline אינו מופיע

1. הריצו את `/statusline-doctor` לבדיקת בריאות ההתקנה
2. בדקו ש-`~/.claude/settings.json` מכיל stanza של `statusLine` שמצביע ל-`cc-2x-statusline/statusline.sh`
3. ודאו שה-runtime זמין: `python3 --version` או `node --version`
4. ב-Windows, ודאו שה-interpreter אינו stub של WindowsApps

## ה-statusline מציג נתונים שגויים

1. הגדירו `STATUSLINE_DEBUG=1` כדי לאפשר פלט debug ל-stderr במנוע Python
2. בדקו את `~/.claude/statusline-state.json` ל-rolling state פגום (מחקו כדי לאפס)
3. בדקו את `~/.claude/statusline-schedule.json` ל-schedule מיושן (מחקו כדי לאלץ רענון)
4. ודאו ש-URL ה-schedule ב-`~/.claude/statusline-config.json` נגיש

## ה-narrator אינו פועל

1. בדקו ש-`STATUSLINE_NARRATOR_ENABLED` אינו מוגדר ל-`0`
2. ודאו ש-hooks מחוברים ב-`~/.claude/settings.json` (הריצו `/statusline-doctor`)
3. לשכבת Haiku: ודאו ש-`ANTHROPIC_API_KEY` מוגדר ושהחבילה `anthropic` מותקנת
4. בדקו throttle: ה-narrator ממתין לפחות 5 דקות בין emissions של prompt_submit
5. ב-Windows: ודאו ש-`cygpath` זמין להמרת נתיבים

## מצב debug

```bash
# פלט debug של מנוע Python
STATUSLINE_DEBUG=1 python3 engines/python-engine.py < /dev/null

# בדיקת rendering של statusline ישירות
echo '{"model":"opus","context_window":{"pct":45}}' | python3 engines/python-engine.py

# בדיקת narrator ישירות
python3 -c "from narrator.engine import run; print(run('prompt_submit'))"

# בדיקת narrator של Node.js
node narrator/cli.js prompt_submit
```

## שגיאות נפוצות

| שגיאה | סיבה | פתרון |
|-------|-------|-----|
| Statusline ריק | מנוע קרס בשקט | בדקו פלט של `STATUSLINE_DEBUG=1` |
| `$800/hr burn rate` | spike guard חסר | לא אמור לקרות לאחר v2.1; ודאו קבועי rolling_state |
| שעות peak בזמן שגוי | באג בהמרת אזור זמן | בדקו שדה `tz` ב-schedule ואזור הזמן המקומי |
| Hooks של narrator אינם מחוברים | התקנה חלקית | הריצו `/statusline-doctor --fix` |
| שגיאת JSON parse ב-config | קובץ config פגום | מחקו את `~/.claude/statusline-config.json` והגדירו מחדש |
| שגיאות נתיב ב-Windows | אי-התאמה בין MSYS לנתיב native | ודאו ש-`cygpath` זמין ב-Git Bash |

## ה-doctor ככלי דיבאגינג

ה-doctor הוא כלי הדיבאגינג הראשון בשורה. הוא בודק:

- זמינות runtime
- חיווט settings.json
- תקינות קובץ config
- הרצת dry-run של statusline (לוכד exit code, שורות פלט, timing)
- רישום hooks

הריצו `bash doctor/doctor.sh --json` לפלט קריא-מכונה שניתן להעביר לכלים אחרים.
