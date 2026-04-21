# Node parity + framed narrator notes + telemetry hard opt-out

**Date:** 2026-04-21

---

## English

### What landed

This release closes the remaining gap between the Python and Node runtime paths, documents the latest narrator UX changes, and tightens telemetry behavior so the hard opt-out is actually hard.

### Node path parity

- `engines/node-engine.js` now renders the same `vim_mode` and `agent` / worktree context that the Python engine already exposed in the standard and full presets.
- The Windows Git Bash narrator hooks no longer shell out through `node -e ...` with embedded Windows paths. They invoke `narrator/cli.js` directly instead, which avoids backslash escaping bugs on `C:\...` paths.
- macOS keeps using the same POSIX hook flow as Linux, while the Node engine retains its `process.platform === 'darwin'` branch for macOS-specific token lookup.

### Narrator output is now visibly statusline text

Narrator notes are now framed so they read like surfaced statusline output, not normal Claude prose:

```text
//// Statusline note ////
//// -> Burning $18/hr — at this rate your 5-hour budget ends in ~40 min. Consider Sonnet for simple steps. ////
```

The rules engine and the optional Haiku layer both render into the same framed format. Several generic templates (`burn_low`, `peak_rate_ok`, `off_peak_wide_open`) were also rewritten to be more actionable and less filler-heavy.

### Language behavior is now explicit in the docs

- Auto-detect order is: `STATUSLINE_NARRATOR_LANGS` override, then `LC_ALL`, then `LC_MESSAGES`, then `LANG`, then English fallback.
- `/narrator-lang en|he|en,he` is the quickest runtime switch.
- `STATUSLINE_NARRATOR_LANGS=en`, `he`, or `en,he` remains available for shell-level control.

### Telemetry hard opt-out now reaches doctor reports too

Automatic telemetry was already documented for install/update/heartbeat, but the explicit `doctor.sh --report` path needed one more guard. The repo now makes the distinction clear:

- `"telemetry": false` disables the automatic `install_result`, `update`, and `heartbeat` events.
- `STATUSLINE_DISABLE_TELEMETRY=1` is the hard kill switch. It now also blocks `doctor.sh --report`.
- `doctor.sh --report` sends only aggregate counts plus failed check IDs; never prompts, file contents, or conversation data.

### Validation

- `pytest tests/test_doctor.py -q`
- `pytest tests/test_narrator.py -q`
- `npm run test:runtime`

---

<div dir="rtl">

## עברית

### מה נכנס

הגרסה הזו סוגרת את הפערים האחרונים בין נתיב ה-Python ל-Node, מתעדת את שינויי ה-UX האחרונים של ה-narrator, ומקשיחה את התנהגות ה-telemetry כך שה-hard opt-out באמת יהיה קשיח.

### parity בנתיב ה-Node

- `engines/node-engine.js` מציג עכשיו גם `vim_mode` וגם `agent` / worktree כמו מנוע ה-Python ב-presets של standard ו-full.
- ב-Windows Git Bash ה-hooks של ה-narrator כבר לא משתמשים ב-`node -e ...` עם נתיבי Windows מוטמעים. במקום זה הם מריצים ישירות את `narrator/cli.js`, וכך נמנעות תקלות escaping בנתיבים כמו `C:\...`.
- macOS ממשיך להשתמש באותו זרם hooks POSIX של Linux, ובמנוע ה-Node נשאר גם ענף `darwin` לטיפול ב-token lookup של macOS.

### פלט ה-narrator עכשיו נראה כמו statusline

הודעות ה-narrator ממוסגרות עכשיו כך שייראו כמו פלט statusline surfaced, ולא כמו טקסט רגיל של Claude:

```text
//// Statusline note ////
//// -> Burning $18/hr — at this rate your 5-hour budget ends in ~40 min. Consider Sonnet for simple steps. ////
```

גם מנוע החוקים וגם שכבת Haiku האופציונלית משתמשים באותו פורמט ממוסגר. בנוסף, כמה תבניות כלליות (`burn_low`, `peak_rate_ok`, `off_peak_wide_open`) שוכתבו כדי להיות יותר שימושיות ופחות גנריות.

### התנהגות השפה עכשיו מפורשת בדוקס

- סדר הזיהוי האוטומטי הוא: override דרך `STATUSLINE_NARRATOR_LANGS`, אחר כך `LC_ALL`, אחר כך `LC_MESSAGES`, אחר כך `LANG`, ואז fallback לאנגלית.
- `/narrator-lang en|he|en,he` הוא המתג המהיר ביותר בזמן ריצה.
- `STATUSLINE_NARRATOR_LANGS=en`, `he`, או `en,he` עדיין זמינים לשליטה דרך ה-shell.

### hard opt-out של telemetry מכסה עכשיו גם doctor reports

ה-telemetry האוטומטי כבר היה מתועד עבור install/update/heartbeat, אבל הנתיב המפורש של `doctor.sh --report` היה צריך guard נוסף. עכשיו ההבחנה ברורה בריפו:

- `"telemetry": false` מכבה את אירועי ה-`install_result`, `update`, ו-`heartbeat` האוטומטיים.
- `STATUSLINE_DISABLE_TELEMETRY=1` הוא kill switch קשיח. עכשיו הוא חוסם גם את `doctor.sh --report`.
- `doctor.sh --report` שולח רק ספירות אגרגטיביות ו-IDs של בדיקות שנכשלו; לעולם לא prompts, תוכן קבצים, או נתוני שיחה.

### ולידציה

- `pytest tests/test_doctor.py -q`
- `pytest tests/test_narrator.py -q`
- `npm run test:runtime`

</div>
