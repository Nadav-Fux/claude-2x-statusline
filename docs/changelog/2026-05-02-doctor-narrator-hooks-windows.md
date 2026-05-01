# Doctor narrator hook detection — fix Windows/Git Bash false positive

**Date:** 2026-05-02

---

## English

### The bug

`doctor.sh` could report:

```text
⚠ Narrator hooks not wired in settings.json
```

even when the hooks were correctly installed and Claude Code was already running them.

This showed up mainly on Windows + Git Bash installs, where the narrator worked in practice but doctor still warned users to rerun `install.sh`.

### Why it happened

There were two separate issues in the validation path:

1. The checker only looked for `command` values at the top level of each hook entry.
   Claude Code stores hooks in a nested shape like:

```json
{
  "SessionStart": [
    {
      "matcher": "*",
      "hooks": [
        { "type": "command", "command": "bash .../narrator-session-start.sh" }
      ]
    }
  ]
}
```

So the real command strings lived one level deeper than the old check expected.

2. On Windows, Git Bash uses MSYS paths like `/c/Users/...`, but a Windows-native Python interpreter expects `C:/Users/...` or `C:\Users\...`.
   Passing `settings.json` as an argv path could fail before the checker even parsed the file, which then fell back to `0` and emitted the warning.

### The fix

- `doctor.sh` now reads `settings.json` from stdin instead of passing the path as argv.
- The validator now walks both nested Claude Code hook entries and older flatter shapes for backward compatibility.
- Command matching now normalizes:
  - optional `bash ` prefixes
  - `/c/...` MSYS paths to `C:/...`
  - slash direction and case

That makes the check compare the same canonical command on both sides.

### Result

On Windows / Git Bash, doctor now reports the real state:

```text
✓ Narrator hooks installed and wired
```

instead of a misleading false positive.

### Validation

- `doctor/doctor.sh` now returns the success line on a Windows Git Bash install with hooks already present.
- Shell syntax remains valid.

---

<div dir="rtl">

## עברית

### הבאג

`doctor.sh` היה יכול להציג:

```text
⚠ Narrator hooks not wired in settings.json
```

גם כשה-hooks היו מותקנים נכון ו-Claude Code כבר הריץ אותם בפועל.

זה קרה בעיקר ב-Windows עם Git Bash: ה-narrator עבד בפועל, אבל doctor עדיין הפחיד את המשתמש ואמר להריץ שוב `install.sh`.

### למה זה קרה

היו כאן שתי בעיות נפרדות:

1. הבדיקה חיפשה `command` רק ברמה העליונה של כל hook entry.
   בפועל Claude Code שומר hooks במבנה מקונן, שבו הפקודות עצמן יושבות בתוך `hooks: [...]`.

2. ב-Windows, Git Bash משתמש בנתיבי MSYS כמו `/c/Users/...`, אבל Python מקומי של Windows מצפה ל-`C:/Users/...` או `C:\Users\...`.
   כשה-path של `settings.json` הועבר כ-argv, הסקריפט היה עלול להיכשל עוד לפני קריאת הקובץ, ליפול ל-`0`, ולייצר warning שגוי.

### התיקון

- `doctor.sh` קורא עכשיו את `settings.json` דרך stdin במקום להעביר path ב-argv.
- הולכים עכשיו גם על המבנה המקונן של Claude Code וגם על מבנים ישנים/שטוחים לצורכי תאימות לאחור.
- השוואת הפקודות מנרמלת:
  - prefix אופציונלי של `bash `
  - המרה של נתיבי `/c/...` ל-`C:/...`
  - כיוון slashes ו-case

כך שני הצדדים מושווים באותה צורה קנונית.

### התוצאה

ב-Windows / Git Bash, doctor מציג עכשיו את המצב האמיתי:

```text
✓ Narrator hooks installed and wired
```

במקום false positive מבלבל.

### ולידציה

- `doctor/doctor.sh` מחזיר את שורת ההצלחה על התקנת Windows Git Bash שבה ה-hooks כבר קיימים.
- תחביר ה-shell נשאר תקין.

</div>