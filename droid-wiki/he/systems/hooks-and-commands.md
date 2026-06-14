# Hooks and commands

## מטרה

שכבת אינטגרציה של Claude Code. hooks מחברים את ה-narrator למחזור החיים של הסשן ב-Claude Code. פקודות slash מאפשרות למשתמשים לשלוט בשורת המצב מתוך Claude Code. skills מספקים זרימות הגדרה מודרכות.

## Hooks

שני סקריפטי hook יורים באירועי מחזור חיים של Claude Code, רשומים דרך `hooks/hooks.json`:

```json
{
  "hooks": {
    "SessionStart": [{
      "hooks": [{
        "type": "command",
        "command": "bash \"${CLAUDE_PLUGIN_ROOT}/hooks/narrator-session-start.sh\""
      }]
    }],
    "UserPromptSubmit": [{
      "hooks": [{
        "type": "command",
        "command": "bash \"${CLAUDE_PLUGIN_ROOT}/hooks/narrator-prompt-submit.sh\""
      }]
    }]
  }
}
```

### dispatch של hook

שני סקריפטי ה-hook עוקבים אחר אותו דפוס:

1. טוענים את `lib/resolve-runtime.sh` כדי למצוא Python או Node
2. מנסים Python narrator תחילה (`narrator/engine.py` דרך `python -c`)
3. בכישלון Python, נופלים ל-Node.js narrator (`narrator/cli.js`)
4. תמיד יוצאים עם 0 (לעולם לא חוסמים את הסשן)

ה-hooks משתמשים ב-`cygpath -w` ב-Windows/Git Bash כדי להמיר נתיבי MSYS לצורה טבעית, מכיוון ש-Python אינו יכול לפתור נתיבים בסגנון `/c/Users/...`.

### מה hooks פולטים

ה-narrator פולט טקסט ממוסגר (`//// -> insight text ////`) ל-stdout. Claude Code מציג זאת מעל ה-prompt הבא של המשתמש. אם ה-narrator מחזיר כלום (throttled, מנוטרל, אין נתונים), ה-hook יוצא בשקט.

## פקודות slash

אחד-עשר הגדרות פקודה מתגוררות ב-`commands/`:

| פקודה | קובץ | מטרה |
|---------|------|---------|
| `/statusline-init` | `statusline-init.md` | התקנה מלאה מקובצי runtime של plugin |
| `/statusline-minimal` | `statusline-minimal.md` | מעבר ל-tier מינימלי |
| `/statusline-standard` | `statusline-standard.md` | מעבר ל-tier סטנדרטי |
| `/statusline-full` | `statusline-full.md` | מעבר ל-tier מלא |
| `/statusline-tier` | `statusline-tier.md` | בורר tier אינטראקטיבי |
| `/statusline-doctor` | `statusline-doctor.md` | הרצת אבחונים |
| `/statusline-update` | `statusline-update.md` | בדיקה והחלת עדכונים |
| `/statusline-onboarding` | `statusline-onboarding.md` | סיור מודרך לאחר התקנה |
| `/explain` | `explain.md` | הסברת מקטעי שורת המצב |
| `/narrate` | `narrate.md` | הפעלה ידנית של narrator |
| `/narrator-lang` | `narrator-lang.md` | החלפת שפת narrator |

פקודות הן קובצי markdown עם frontmatter של YAML המגדיר את התיאור, הכלים המותרים ורמזי ארגומנטים. Claude Code קורא אותם ומריץ את השלבים המוטמעים.

## Skills

חמישה skills מתגוררים ב-`skills/`:

| Skill | מטרה |
|-------|---------|
| `skills/setup/SKILL.md` | הגדרה ראשונית מודרכת עם בורר tier |
| `skills/onboarding/SKILL.md` | סיור הרצה ראשונה לאחר התקנה |
| `skills/full/SKILL.md` | מעבר ל-tier מלא |
| `skills/standard/SKILL.md` | מעבר ל-tier סטנדרטי |
| `skills/minimal/SKILL.md` | מעבר ל-tier מינימלי |

skills דומים לפקודות אך ניתנים להפעלה על ידי שפה טבעית. הם רשומים ב-`plugin.json` דרך `"skills": "./skills/"`.

## manifest של plugin

`plugin.json` רושם את ה-plugin עם Claude Code:

```json
{
  "name": "claude-2x-statusline",
  "version": "2.2.0",
  "commands": "./commands/",
  "skills": "./skills/",
  "hooks": "./hooks/"
}
```

כאשר מותקן דרך מערכת ה-plugin של Claude Code, commands, skills ו-hooks מתגלים אוטומטית מהספריות האלה.

## קובצי מקור עיקריים

| קובץ | מטרה |
|------|---------|
| `hooks/hooks.json` | רישום hook של Claude Code |
| `hooks/narrator-prompt-submit.sh` | hook של UserPromptSubmit |
| `hooks/narrator-session-start.sh` | hook של SessionStart |
| `commands/*.md` | 11 הגדרות פקודת slash |
| `skills/*/SKILL.md` | 5 הגדרות skill |
| `plugin.json` | manifest של plugin |

## עמודים קשורים

- [Narrator](../features/narrator.md) — מה ה-hooks מפעילים
- [Doctor diagnostics](../features/doctor.md) — פקודת `/statusline-doctor`
- [Installer pipeline](installer.md) — כיצד hooks מחוברים ל-`settings.json`
