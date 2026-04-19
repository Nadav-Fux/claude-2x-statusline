# Plugin manifest fix + /narrator-lang — 2026-04-20

## English

### Plugin manifest fix (`"hooks"` field + version bump to 2.2.0)

**Why this matters**: when a user installs this plugin via the Claude Code marketplace (once available) or the plugin subsystem, the hooks directory wasn't being auto-wired because `plugin.json` had no `"hooks"` field. This silently meant the narrator never fired on marketplace installs — it only worked if you cloned the repo manually and ran `install.sh`. Fixed by adding `"hooks": "./hooks/"` to both `plugin.json` and `.claude-plugin/plugin.json`.

Version bumped to `2.2.0` to reflect the accumulated changes since `2.1.0`:

- Rolling-window burn rate + cache reuse + context depletion segments
- Narrator hook (rules engine always-on + optional Haiku layer + 18 bilingual insight templates)
- `/explain` + `/narrator-lang` slash commands
- Cross-timezone Saturday peak spillover fix
- Retroactive install-ping
- Full Windows support (WindowsApps stubs, cygpath, UTF-8, embeddable Python `_pth` patch)

### New slash command: `/narrator-lang`

Quickly switch the narrator's output language between English, Hebrew, or both — without hunting for environment variables.

**Usage:**

```
/narrator-lang en       # English only
/narrator-lang he       # Hebrew only
/narrator-lang en,he    # Both languages on each emission
```

The command validates your input, confirms the selection in the target language, and prints the exact `export STATUSLINE_NARRATOR_LANGS=<value>` command to add to your shell profile (or run for the current session only).

**Locale auto-detect still works** — if you leave `STATUSLINE_NARRATOR_LANGS` unset, the narrator reads `$LANG` / `$LC_ALL` at invocation time (e.g. `LANG=he_IL.UTF-8` → Hebrew by default).

The command does not write to any files; the user retains full control over their shell profile.

---

<div dir="rtl">

## עברית

### תיקון ה-manifest של הפלאגין (שדה `"hooks"` + bump לגרסה 2.2.0)

**למה זה חשוב**: עד עכשיו ה-manifest של הפלאגין (`plugin.json`) לא הכיל את השדה `"hooks"`. כתוצאה מכך, התקנה דרך ה-marketplace (או כל מערכת plugin אחרת) לא חיברה את תיקיית ה-hooks — ה-narrator פשוט לא הופעל. הבעיה תוקנה: הוסף `"hooks": "./hooks/"` לשני קבצי `plugin.json` (בשורש ובתיקיית `.claude-plugin`).

גרסה `2.2.0` מסכמת את כל השינויים שנצברו מאז `2.1.0`:

- מטריקות rolling-window לקצב שריפה, שימוש חוזר בקאש ודלדול קונטקסט
- ה-narrator hook (מנוע חוקים תמיד פועל + שכבת Haiku אופציונלית + 18 תבניות insight דו-לשוניות)
- פקודות slash `/explain` ו-`/narrator-lang`
- תיקון spillover לשבת UTC עבור משתמשי UTC+3
- install-ping רטרואקטיבי
- תמיכה מלאה ב-Windows (stub-ים של WindowsApps, cygpath, UTF-8, תיקון `_pth` ל-Python embeddable)

### פקודה חדשה: `/narrator-lang`

מאפשרת לעבור במהירות בין עברית, אנגלית, או שתיהן — בלי לחפש משתני סביבה.

**שימוש:**

```
/narrator-lang en       # אנגלית בלבד
/narrator-lang he       # עברית בלבד
/narrator-lang en,he    # שתי השפות בכל פלט
```

הפקודה מאמתת את הקלט, מאשרת את הבחירה בשפת היעד, ומדפיסה את פקודת ה-export המדויקת להוספה לפרופיל ה-shell (או להרצה בסשן הנוכחי בלבד).

**זיהוי locale אוטומטי עדיין עובד** — אם `STATUSLINE_NARRATOR_LANGS` לא מוגדר, ה-narrator קורא את `$LANG` / `$LC_ALL` בזמן ההפעלה (לדוגמה: `LANG=he_IL.UTF-8` → עברית כברירת מחדל).

הפקודה לא כותבת לאף קובץ — המשתמש שומר שליטה מלאה על פרופיל ה-shell שלו.

</div>
