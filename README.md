<div align="center">

![claude-2x-statusline](assets/header.svg)

# claude-2x-statusline

### v2.2 &mdash; Modular Statusline for Claude Code

Peak hours &bull; Rate limits &bull; Burn rate &bull; Context &bull; Git &mdash; all live, all auto-updating.

[![License: PolyForm Noncommercial 1.0.0](https://img.shields.io/badge/License-PolyForm%20Noncommercial%201.0.0-blue.svg)](LICENSE)
[![Claude Code Plugin](https://img.shields.io/badge/Claude_Code-plugin-blueviolet)](#installation--30-seconds)
[![Platform](https://img.shields.io/badge/Platform-macOS%20%7C%20Linux%20%7C%20Windows-green)](#engines-auto-detected)
[![Works in](https://img.shields.io/badge/Works_in-CLI%20%7C%20Terminal-blue)](#)
[![Version](https://img.shields.io/badge/version-2.2.0-orange)](#)

**[Live Preview & Tier Picker](https://statusline.nvision.me)** &nbsp;&bull;&nbsp; by [Nadav Fux](https://github.com/Nadav-Fux)

<br>

</div>

---

<div dir="rtl" align="right">

## עברית

**ניווט מהיר:**
[מה זה?](#מה-זה) &bull;
[3 רמות תצוגה](#3-רמות-תצוגה) &bull;
[התקנה](#התקנה--30-שניות) &bull;
[מדדים ו-Rolling Window](#מדדים-ו-rolling-window) &bull;
[Narrator Hook](#narrator-hook--הודעה-מעל-הפרומפט) &bull;
[פקודת /explain](#פקודת-explain) &bull;
[עדכון אוטומטי](#עדכון-אוטומטי-מרחוק) &bull;
[Telemetry](#telemetry--שקיפות-מלאה) &bull;
[Windows](#תמיכה-ב-windows) &bull;
[בדיקות](#בדיקות)

---

### מה זה?

תוסף ל-Claude Code שמציג **שורת סטטוס חיה** בתחתית הטרמינל.
רואים במבט אחד: האם עכשיו שעות עומס, כמה context נשאר, מה ה-rate limit, כמה עולה הסשן, ומה מצב ה-git.

**הקילר-פיצ'ר:** שעות העומס מתעדכנות אוטומטית מ-GitHub &mdash; אם Anthropic ישנו את המדיניות, אתה מקבל את העדכון בלי לגעת בתוסף.

### רישיון ושימוש מסחרי

הקוד בריפו הזה זמין תחת `PolyForm Noncommercial 1.0.0`.

מותר להשתמש, לשנות ולהפיץ אותו למטרות לא־מסחריות, בכפוף לתנאי הרישיון.

שימוש מסחרי, שילוב במוצר או שירות בתשלום, הפצה בתשלום, או פריסה פנימית בארגון מסחרי דורשים אישור כתוב נפרד מ-Nadav Fux.

`Copyright (c) 2026 Nadav Fux.` אלא אם צוין אחרת עבור חומר צד שלישי. זהו רישיון source-available ולא רישיון open-source מאושר OSI, משום ששימוש מסחרי מוגבל.

### 3 רמות תצוגה

<div dir="ltr" align="left">

**Minimal** &mdash; שורה אחת, מינימלי ונקי:

![Minimal](assets/tier-minimal.svg)

פיק/לא-פיק, מודל, אחוז context, אחוז מכסה 5 שעות, סביבה, git.

**Standard** &mdash; 2 שורות, כולל עלות ו-rate limits:

![Standard](assets/tier-standard.svg)

טוקנים מפורטים, עלות סשן, ושורה שנייה עם ברי rate limit גרפיים וזמני איפוס.

**Full** (מומלץ) &mdash; 4 שורות, דשבורד מלא:

![Full](assets/tier-full.svg)

שורה 1: סטטוס נקי. שורה 2: ציר זמן ויזואלי. שורה 3: ברי rate limit. שורה 4: קצב שריפה, זמן עד שה-context ייגמר, ואחוז cache.

</div>

### התקנה &mdash; 30 שניות

**הדרך הכי קלה &mdash; תגיד ל-Claude:**

<div dir="ltr" align="left">

```
תתקין לי את claude-2x-statusline מ-github.com/Nadav-Fux/claude-2x-statusline
```

</div>

Claude יריץ clone, install, ישאל איזה רמה אתה רוצה, ויגדיר הכל.

**או שורה אחת בטרמינל:**

<div dir="ltr" align="left">

```bash
git clone https://github.com/Nadav-Fux/claude-2x-statusline.git ~/.claude/cc-2x-statusline && bash ~/.claude/cc-2x-statusline/install.sh
```

</div>

**Windows (PowerShell):**

<div dir="ltr" align="left">

```powershell
irm https://raw.githubusercontent.com/Nadav-Fux/claude-2x-statusline/main/install.ps1 | iex
```

</div>

ה-installer מדפיס בדיוק איזה runtime הוא בוחר (Python / Node.js / Bash) &mdash; שקוף לגמרי. על Windows הוא דוחה stubs של Microsoft Store ומחפש Python נייד ב-`~/tools/` ו-`AppData`.

**Narrator פועל עם Python 3.9+ או Node.js.** עם Bash בלבד אין Narrator, ועל Windows התקנת PowerShell-only מדלגת על ה-hooks עד ש-Git Bash או WSL זמינים.

אם התקנת דרך plugin בלבד ועדיין אין statusline, הרץ `/statusline-init` כדי להשלים את ה-wiring המלא של `settings.json` וה-hooks.
אחרי install או update, הרץ `/statusline-onboarding` כדי לקבל quickstart קצר עם הפקודות החשובות באמת.
אם ההתקנה שלך ישנה, ה-statusline עצמו יציג badge של `Update available` או `Update required` מתוך ה-schedule המרוחק.

### שינוי רמה

<div dir="ltr" align="left">

| פקודה                  | מה עושה             |
| ---------------------- | ------------------- |
| `/statusline-minimal`  | עובר ל-Minimal      |
| `/statusline-standard` | עובר ל-Standard     |
| `/statusline-full`     | עובר ל-Full (מומלץ) |

</div>

### עדכון התוסף

<div dir="ltr" align="left">

```bash
bash ~/.claude/cc-2x-statusline/update.sh
```

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "$env:USERPROFILE\.claude\cc-2x-statusline\update.ps1"
```

</div>

אפשר גם מתוך Claude דרך `/statusline-update`.

### Troubleshooting מהיר

<div dir="ltr" align="left">

```bash
bash ~/.claude/cc-2x-statusline/doctor/doctor.sh
bash ~/.claude/cc-2x-statusline/doctor/doctor.sh --fix
bash ~/.claude/cc-2x-statusline/doctor/doctor.sh --report
```

</div>

`--report` שולח סיכום health אנונימי חד-פעמי של ספירת `ok/warn/fail` ומזהי הבדיקות שנכשלו בלבד.

---

### מדדים ו-Rolling Window

שורה 4 ב-Full tier מציגה נתונים על חלון נע של **10 דקות אחרונות**, לא על כל הסשן. כך ספייק רגעי לא מעוות את המספר.

<div dir="ltr" align="left">

```
spending $5.4/hr moderate (10m) · ctx full ~47m · cache reuse 96% ↑2.3k saving
```

</div>

- **spending**: קצב שריפה. המילה `low` / `moderate` / `high` מוטמעת ישירות בתצוגה. `(10m)` = החלון של החישוב.
- **cache reuse**: כשיש קריאות מה-cache פעיל &mdash; `↑2.3k saving` מציין כמה טוקנים נחסכו ב-5 דקות האחרונות. כשה-cache בסרק &mdash; `cache reuse 96% idle`. המילה "reuse" מדגישה שקריאות cache עולות כ-10% מה-input הרגיל.
- **הנתונים**: נשמרים ב-`~/.claude/statusline-state.json` כ-ring buffer של 60 דקות. כתיבה אטומית. קובץ פגום? נכתב מחדש מאפס.
- **Sanity checks**: מינימום חלון של 3 דקות + תקרה של $200/שעה כדי שספייקים לא ישגעו את המספר.

---

### Narrator Hook &mdash; הודעה מעל הפרומפט

ה-Narrator מוסיף הודעה קצרה **מעל הפרומפט הבא שלך**, בדיוק כמו ש-Borg עושה. הוא קורא את הדשבורד ואומר מה זה אומר ומה כדאי לעשות.

כל פליטה ממוסגרת במכוון כדי שיהיה ברור שזו הודעת statusline ולא טקסט רגיל של Claude:

<div dir="ltr" align="left">

```text
//// Statusline note ////
//// -> Burning $18/hr — at this rate your 5-hour budget ends in ~40 min. Consider Sonnet for simple steps. ////
```

</div>

**שתי שכבות, אדיטיביות (מוצגות ביחד כשעוברים את הסף):**

**שכבה 1 &mdash; Rules Engine** (תמיד פעיל, מתחת ל-50ms, בחינם):

- ניתוח על-פי 4 צירים: דחיפות × חדשנות × ניתנות-לפעולה × ייחודיות
- 15+ תבניות שמכסות: context שמתמלא, burn rate גבוה, cache, rate limits, שעות שיא/עמק, אבני דרך עלות

<div dir="ltr" align="left">

> Burning $18/hr &mdash; at this rate your 5-hour budget ends in ~40 min. Consider Sonnet for simple steps.

</div>

**שכבה 2 &mdash; Haiku** (opt-in, פועל אוטומטית אם `ANTHROPIC_API_KEY` מוגדר):

- `claude-haiku-4-5`, נורה כל 5 פרומפטים **או** 15 דקות (המוקדם מביניהם)
- מוסיף 25-35 מילים של נרטיב על הסשן
- עלות: ~$0.0005 לקריאה

<div dir="ltr" align="left">

> Since last check you refactored three components while your cache warmed from 62% to 94%. Rate limits at 23%, peak ended &mdash; wide-open runway ahead.

</div>

**מתי נורה:**

- התחלת סשן / compact / resume (תמיד)
- כל פרומפט (throttle: ≥ 5 דקות בין הודעות)

**זיכרון בין סשנים:** `~/.claude/narrator-memory.json` &mdash; תצפיות עד 2 שעות, 8 נרטיבים אחרונים, 3 סשנים קודמים, ספירת פרומפטים, אבני דרך עלות.

### שפת ה-narrator

זיהוי אוטומטי: אם `LC_ALL` / `LC_MESSAGES` / `LANG` מתחילים ב-`he` (`he_IL.UTF-8` וכו') — ה-narrator מדבר עברית. אחרת אנגלית.

שינוי מהיר בזמן ריצה: `/narrator-lang en` / `/narrator-lang he` / `/narrator-lang en,he`.

עקיפה ידנית: `STATUSLINE_NARRATOR_LANGS=en` / `=he` / `=en,he`.

**כיוונון:**

<div dir="ltr" align="left">

```bash
export STATUSLINE_NARRATOR_ENABLED=1               # kill switch (ברירת מחדל: on)
export STATUSLINE_NARRATOR_HAIKU=auto              # auto = on אם ANTHROPIC_API_KEY קיים
export STATUSLINE_NARRATOR_HAIKU_INTERVAL_MIN=15   # כל כמה דקות מקסימום
export STATUSLINE_NARRATOR_THROTTLE_MIN=5          # מינימום בין הודעות
```

</div>

הרץ `/narrate` כדי להפעיל ידנית (עוקף throttle).

אין צורך בריסטארט אחרי שינוי השפה; ה-hook קורא את משתני הסביבה בכל invocation.

**מגבלה:** Bash-only = בלי Narrator. על Windows, אם ההתקנה נפלה ל-PowerShell-only, ה-hooks של Narrator ידולגו עד ש-Git Bash או WSL זמינים.

---

### פקודת /explain

<div dir="ltr" align="left">

```
/explain burn_rate
/explain cache_hit
/explain context_depletion
/explain          # ← בלי ארגומנט: טבלת כל הסגמנטים
```

</div>

מסביר בדיוק מה הסגמנט מציג, איך חושב, אילו צבעים משמשים, ומתי הוא מסתתר. 18 סגמנטים מתועדים. אפשר גם דרך `/statusline-doctor --explain <segment>`.

---

### תוסף VS Code / Cursor / Windsurf / Antigravity

ה-installer מזהה אוטומטית עורכים נתמכים ומתקין תוסף לשורת הסטטוס:

<div dir="ltr" align="left">

**Off-Peak &mdash; הכל ירוק:**

![Off-Peak](assets/vscode-offpeak.svg)

**Peak &mdash; שעות שיא:**

![Peak](assets/vscode-peak.svg)

**שימוש גבוה &mdash; אזהרה:**

![High Usage](assets/vscode-high.svg)

</div>

- **שעות שיא** עם ספירה לאחור ואינדיקציה צבעונית
- **Rate limits** עם ברי בטריה ויזואליים &mdash; 5 שעות ו-7 ימים בנפרד, כל אחד עם צבע משלו
- **Context window** &mdash; קורא נתונים חיים מהטרמינל statusline
- **Effort level** &mdash; HI / MED / LO עם צבע

<div dir="ltr" align="left">

| צבע                  | משמעות                                  |
| -------------------- | --------------------------------------- |
| **ירוק (teal)**      | בריא &mdash; שימוש נמוך / מחוץ לשיא     |
| **צהוב** (רקע אזהרה) | בינוני &mdash; 50-79% שימוש או שעות שיא |
| **אדום** (רקע שגיאה) | קריטי &mdash; 80%+ שימוש                |

</div>

**עורכים נתמכים:** VS Code, Cursor, Windsurf, Antigravity (Google). כל עורך מבוסס VS Code נתמך.

### שעות עומס (Peak Hours)

Anthropic מגבילה את קצב הצריכה של מכסת ה-5 שעות בשעות שיא. **שימו לב:** Peak = צריכה מהירה יותר של המכסה. Off-Peak = צריכה רגילה.

<div dir="ltr" align="left">

| מתי                 |  סטטוס   | שעון Pacific              |
| ------------------- | :------: | :------------------------ |
| ימי חול, שעות שיא   | **Peak** | 5:00am &ndash; 11:00am PT |
| שאר השעות           | Off-Peak | &mdash;                   |
| סופ"ש (שבת + ראשון) | Off-Peak | כל היום                   |

</div>

השעות מתורגמות **אוטומטית** לאזור הזמן שלך (ישראל, ארה"ב, אירופה, אוסטרליה &mdash; כולל שעון קיץ/חורף).

**תיקון cross-timezone:** Peak של שבת בשעון Pacific שמגיע לתוך יום ראשון בשעון +UTC3 (ישראל) &mdash; מזוהה ומוצג נכון. גרסאות קודמות לא זיהו את הספיל הזה.

> **חשוב:** מכסות שבועיות לא משתנות. רק הקצב שבו מכסת ה-5 שעות נצרכת עולה בזמן Peak.

### עדכון אוטומטי מרחוק

התוסף מושך קובץ `schedule.json` מ-GitHub כל 6 שעות. אם Anthropic משנים את שעות העומס, אני מעדכן את הקובץ ב-repo &mdash; וכל המשתמשים מקבלים את העדכון **אוטומטית**, בלי `git pull`, בלי התקנה מחדש.

---

### Telemetry &mdash; שקיפות מלאה

**מה נשלח, מתי, ולמה:**

| אירוע            | מתי                               | TTL       |
| ---------------- | --------------------------------- | --------- |
| `install`        | פעם אחת למכונה, בזמן התקנה ראשונה | ללא תפוגה |
| `install_result` | בסוף התקנה                        | 90 יום    |
| `update`         | בסוף ריצת עדכון דרך המתקין        | 90 יום    |
| `heartbeat`      | פעם ביום בזמן שימוש שוטף          | 90 יום    |
| `doctor`         | רק אם מריצים `doctor.sh --report` | 90 יום    |

**Payload:**

<div dir="ltr" align="left">

```json
{
  "id": "random 16-char hex id stored in ~/.claude/.statusline-telemetry-id",
  "v": "2.2",
  "engine": "python",
  "tier": "full",
  "os": "linux",
  "event": "install"
}
```

</div>

**Endpoint:** `https://statusline-telemetry.nadavf.workers.dev/ping`

**מה לא נשלח:** תוכן קבצים, נתוני שיחות, זהות אמיתית, session IDs, כתובות IP (מעבר למה ש-Cloudflare edge רואה). המזהה היחיד הוא מזהה אקראי מקומי בן 16 תווי hex שנשמר ב-`~/.claude/.statusline-telemetry-id`.

אירוע `doctor` שולח רק סיכום אנונימי: ספירת `ok/warn/fail`, מערכת הפעלה, ו-IDs של הבדיקות שנכשלו. אין בו תוכן שיחה, תוכן קבצים, או promptים.

**סטטיסטיקות חיות (שקיפות):** `https://statusline-telemetry.nadavf.workers.dev/stats`

**ביטול:**

<div dir="ltr" align="left">

```json
// ~/.claude/statusline-config.json
{
  "tier": "full",
  "telemetry": false
}
```

</div>

`"telemetry": false` מכבה את ה-`install_result` / `update` / `heartbeat` האוטומטיים.

לכיבוי קשיח של **כל** ערוצי ה-telemetry, כולל `doctor.sh --report`:

<div dir="ltr" align="left">

```bash
export STATUSLINE_DISABLE_TELEMETRY=1
```

</div>

זה שימושי ל-CI, לסביבות בדיקה, או אם רוצים לוודא שהמכונה לא מוציאה שום ping בכלל.

---

### תמיכה ב-Windows

- `lib/resolve-runtime.sh` דוחה `C:\Program Files\WindowsApps\*.exe` &mdash; Microsoft Store stubs שרק פותחים דיאלוג התקנה.
- בדיקת Python נייד: `~/tools/python-*/`, `AppData/Local/Programs/Python/Python3*/` ועוד.
- Hook scripts משתמשים ב-`cygpath -w` לתרגום נתיבי `/c/Users/...` ל-`C:\Users\...`.
- UTF-8 מאולץ ב-stdout של ה-hooks כדי שתווי Narrator לא יינפצו ב-cp1252.

---

### דרישות

<div dir="ltr" align="left">

- Claude Code (CLI / terminal)
- **אחד מ:** Python 3.9+ (מומלץ, Narrator + כל הפיצ'רים) | Python 3 | Node.js | Bash
- **Narrator**: Python 3.9+ או Node.js. Bash = statusline מינימלי בלבד. PowerShell-only על Windows = בלי Narrator עד ש-Git Bash או WSL זמינים.

</div>

---

### בדיקות

<div dir="ltr" align="left">

```bash
pip install pytest tzdata
python -m pytest tests/ -v

# Worker telemetry tests
npm run test:worker
```

</div>

107 בדיקות pytest עוברות (שעות שיא, DST, cross-timezone, rolling state, narrator scoring, memory, install ping, JSON wiring) + 3 בדיקות Node ל-worker telemetry.

</div>

---

<br>

## English

**Quick navigation:**
[What is it?](#what-is-it) &bull;
[What it looks like](#what-it-looks-like) &bull;
[Installation](#installation--30-seconds) &bull;
[Rolling-window metrics](#rolling-window-metrics) &bull;
[Narrator hook](#narrator-hook) &bull;
[/explain command](#explaining-any-segment) &bull;
[Telemetry](#telemetry--transparency) &bull;
[Windows support](#windows-support) &bull;
[Testing](#testing)

---

### What is this?

A modular statusline plugin for Claude Code that shows a **live dashboard** at the bottom of your terminal. At a glance you see: peak hours status, model info, context usage, rate limits, session cost, burn rate, cache efficiency, and git status.

**The killer feature:** Peak hours schedule auto-updates from GitHub. When Anthropic changes their policy, the maintainer updates one JSON file and every user gets the new schedule automatically &mdash; no `git pull`, no reinstall.

### License and Commercial Use

This repository is available under `PolyForm Noncommercial 1.0.0`.

Noncommercial use, modification, and redistribution are allowed, subject to the license terms.

Commercial use, paid distribution, inclusion in a paid product or service, or internal deployment inside a commercial organization require separate written permission from Nadav Fux.

`Copyright (c) 2026 Nadav Fux.` Unless noted otherwise for third-party material, this repository is published as source-available rather than an OSI-approved open-source project, because commercial use is restricted.

---

## What It Looks Like

### Minimal &mdash; 1 line

![Minimal](assets/tier-minimal.svg)

Peak status, model, context %, 5-hour limit %, environment, and git.

### Standard &mdash; 2 lines

![Standard](assets/tier-standard.svg)

Full token counts, session cost, and a second line with graphical rate limit bars and reset times.

### Full &mdash; 4 lines (recommended)

![Full](assets/tier-full.svg)

Line 1: Clean status bar. Line 2: Visual timeline of peak/off-peak. Line 3: Rate limit bars with resets. Line 4: Burn rate ($/hr), context depletion estimate, and cache hit ratio.

The **Peak** badge turns **red** (lots of peak time left), **yellow** (1-2 hours remaining), or **green** (under 30 min &mdash; almost over), with a countdown showing exactly when peak ends.

---

## Editor Extension (VS Code / Cursor / Windsurf / Antigravity)

The installer automatically detects supported editors and installs a companion status bar extension with live data and color coding.

**Off-Peak &mdash; all green:**

![Off-Peak](assets/vscode-offpeak.svg)

**Peak hours:**

![Peak](assets/vscode-peak.svg)

**High usage &mdash; warning:**

![High Usage](assets/vscode-high.svg)

**Features:**

- **Peak/Off-Peak** with countdown and next-peak timer (color-coded)
- **Rate limits** with battery bars &mdash; separate 5h and 7d, each with its own color
- **Context window** &mdash; reads live data from the terminal statusline
- **Effort level** &mdash; HI / MED / LO with color coding

**Colors:**

| Color                   | Meaning                                     |
| ----------------------- | ------------------------------------------- |
| **Teal**                | Healthy &mdash; low usage / off-peak        |
| **Yellow** (warning bg) | Moderate &mdash; 50-79% usage or peak hours |
| **Red** (error bg)      | Critical &mdash; 80%+ usage                 |

**Supported editors:** VS Code, Cursor, Windsurf, Antigravity (Google). Any VS Code&ndash;based editor should work.

If no editor is detected, the extension step is simply skipped. You can install later by running `npm run package` in the `vscode/` folder.

---

## Installation &mdash; 30 Seconds

### Option 1: Ask Claude (easiest)

Paste this into Claude Code:

```
Install the claude-2x-statusline plugin from github.com/Nadav-Fux/claude-2x-statusline
```

Claude will clone the repo, run the installer, ask which tier you want, and configure everything. Restart Claude Code when done.

### Option 2: One-liner

**macOS / Linux:**

```bash
git clone https://github.com/Nadav-Fux/claude-2x-statusline.git ~/.claude/cc-2x-statusline && bash ~/.claude/cc-2x-statusline/install.sh
```

**Windows (PowerShell):**

```powershell
irm https://raw.githubusercontent.com/Nadav-Fux/claude-2x-statusline/main/install.ps1 | iex
```

The installer asks which tier you want, writes the config, updates `settings.json`, installs slash commands, and fetches the initial peak hours schedule. It prints exactly which runtime it selected before proceeding. **Restart Claude Code to activate.**

After install or update, run `/statusline-onboarding` for a short quickstart. If your local install falls behind the version advertised by the remote schedule, the statusline now shows an `Update available` or `Update required` badge directly in the first line.

### Runtime requirements

| Engine           | Features                             | Minimum version |
| :--------------- | :----------------------------------- | :-------------- |
| Python 3.9+      | Full features including Narrator     | Recommended     |
| Python 3 (older) | All statusline features, no Narrator | 3.6+            |
| Node.js          | All statusline features + Narrator   | Any LTS         |
| Bash             | Minimal statusline only              | 4+              |

The installer uses a shared runtime resolver (`lib/resolve-runtime.sh`) that rejects Microsoft Store app-execution alias stubs and probes portable install locations before falling back to system PATH.

---

## 3 Tiers

> **Recommendation:** Start with **Full**. You get everything &mdash; timeline, rate limits, burn rate, cache stats. You can always switch down.

| Tier     | Lines | Segments                                                                       |
| -------- | ----- | ------------------------------------------------------------------------------ |
| minimal  | 1     | peak_hours, model, context, git_branch, git_dirty, rate_limits, env            |
| standard | 1     | peak_hours, model, context, vim_mode, agent, git_branch, git_dirty, cost,      |
|          |       | effort, env                                                                    |
| full     | 4     | Same segments as standard on line 1, plus: timeline (line 2), rate_limits bars |
|          |       | (line 3), burn_rate + cache_hit + metrics (line 4)                             |

On off-peak days (weekdays not in the peak schedule, and all-day normal-mode schedules), the timeline line is auto-hidden; rate limit bars and metrics still render.

### Switch Anytime

Use slash commands inside Claude Code:

| Command                | Effect                             |
| :--------------------- | :--------------------------------- |
| `/statusline-minimal`  | Switch to Minimal (1 line)         |
| `/statusline-standard` | Switch to Standard (2 lines)       |
| `/statusline-full`     | Switch to Full dashboard (4 lines) |

Or edit the config directly:

```bash
# Config file location:
~/.claude/statusline-config.json
```

```json
{
  "tier": "full",
  "schedule_url": "https://raw.githubusercontent.com/Nadav-Fux/claude-2x-statusline/main/schedule.json",
  "schedule_cache_hours": 3
}
```

---

## Rolling-Window Metrics

Line 4 of the Full tier computes burn rate and cache stats over a **rolling 10-minute window**, not lifetime totals. A one-off spike does not distort the reading.

### Burn rate

```
spending $5.4/hr moderate (10m)
```

- The `(10m)` label makes the window explicit.
- Severity word (`low` / `moderate` / `high`) is inline, no separate indicator needed.
- Colors: RED if extrapolated session cost would exceed $50, YELLOW >$20, dim otherwise.
- Sanity bounds: minimum 3-minute window span required; hard cap at $200/hr to prevent divide-by-small-interval spikes.

### Cache display

```
cache reuse 96% ↑2.3k saving     ← cache is actively being read
cache reuse 96% idle              ← nothing read from cache this tick
```

- "reuse" is intentional: cache reads cost roughly 10% of fresh input tokens, so knowing the reuse ratio tells you the actual saving.
- `↑2.3k` = tokens read from cache in the last 5 minutes.
- `saving` / `idle` indicates whether those reads are happening right now.

### State storage

Rolling samples are persisted to `~/.claude/statusline-state.json`:

- 60-minute ring buffer of timestamped samples.
- Atomic write (temp file + rename) so a crash cannot corrupt the file.
- If the file is corrupt or unreadable, it is silently replaced with an empty buffer.

---

## What Everything Means

This statusline is dense by design &mdash; each segment answers a specific question. If you see a segment you don't recognize, run `/explain <segment>` (or the legacy path `/statusline-doctor --explain <segment>`) inside Claude Code.

### Main Status Line

```
 Off-Peak  ▸ peak in 3h 22m ▸ Opus 4.6 ▸ 360K/1.0M 36% ▸ $4.20 ▸ REMOTE ▸ main 2 unsaved
 ╰─ peak ─╯  ╰─ countdown ─╯  ╰ model ╯  ╰── context ──╯  ╰ $$ ╯  ╰ env ╯  ╰─── git ───╯
```

| Segment               | What it shows       | Details                                                               |
| :-------------------- | :------------------ | :-------------------------------------------------------------------- |
| `Off-Peak` / `Peak`   | Current peak status | Green = Off-Peak (normal). Red/yellow = Peak (limits consumed faster) |
| `peak in 3h 22m`      | Countdown           | Time until the next peak window starts (or ends, during peak)         |
| `3pm-9pm`             | Peak window         | Peak hours converted to your local timezone                           |
| `Opus 4.6`            | Active model        | The model Claude Code is currently using                              |
| `360K/1.0M 36%`       | Context usage       | Tokens used / window size and percentage                              |
| `$4.20`               | Session cost        | Total cost in USD for this session                                    |
| `LOCAL` / `REMOTE`    | Environment         | Cyan = local machine. Magenta = SSH/remote server                     |
| `main`                | Git branch          | Current branch name                                                   |
| `saved` / `2 unsaved` | Git status          | Green "saved" = clean. Yellow = uncommitted changes                   |

When you see `$4.20`: cumulative session cost. Compare against your per-session budget. There's no auto-stop at any threshold.

### Conditional Segments (appear only when active)

| Segment             | When it appears                   |
| :------------------ | :-------------------------------- |
| `NORMAL` / `INSERT` | Vim mode is active in Claude Code |
| Agent name          | Running inside a subagent         |
| `wt:name`           | Running inside a git worktree     |

When you see `NORMAL` or `INSERT`: Vim keybindings are active in Claude Code. If this is unexpected, check your settings.json for `"vim": true`.
When you see `wt:name`: you are working in a linked git worktree. Run `/explain worktree` for details.

### Rate Limits (Standard + Full)

```
│ ▸ 5h ▰▰▱▱▱▱▱▱▱▱ 20% ⟳ 5:00pm · weekly ▰▰▰▰▱▱▱▱▱▱ 42% ⟳ 4/4 11:00pm │
```

| Part             | Meaning                                                |
| :--------------- | :----------------------------------------------------- |
| `5h`             | 5-hour rolling window limit                            |
| `▰▰▱▱▱▱▱▱▱▱ 20%` | Graphical bar + percentage consumed                    |
| `⟳ 5:00pm`       | When this limit resets (local time)                    |
| `⚡ peak`        | Appears during peak &mdash; consumption rate is higher |
| `weekly`         | Weekly limit (does not change during peak)             |
| `⟳ 4/4 11:00pm`  | Weekly reset date and time                             |

### Spending & Cache (Full only)

```
│ spending $5.4/hr moderate (10m) · ctx full ~47m · cache reuse 96% ↑2.3k saving │
```

| Part                              | Meaning                                                                      |
| :-------------------------------- | :--------------------------------------------------------------------------- |
| `spending $5.4/hr moderate (10m)` | Burn rate over last 10 min. Severity word inline.                            |
| `ctx full ~47m`                   | Estimated time until context window is full (red < 30m, yellow < 60m)        |
| `cache reuse 96% ↑2.3k saving`    | Cache read ratio + tokens saved this window. `idle` when nothing being read. |

When you see `$6.3/hr moderate (10m)`: spending rate over the last 10 minutes. The `(10m)` clarifies the window. If sustained, multiply by estimated remaining session hours to forecast total. Colors: RED if extrapolated session cost would exceed $50, YELLOW >$20, DIM otherwise.

When you see `CTX full 37m`: at the current token-generation rate (last 10 min), your context window fills in ~37 minutes. **RED <30m = compact NOW.** YELLOW <60m = plan to compact soon. Hidden above 180m.

When you see `cache reuse 96% ↑2.3k saving`: 96% of cache tokens this tick came from cheap reads (good). `↑2.3k` = tokens read from cache in last 5 min, representing active cost savings. `cache reuse 96% idle` = cache warm but no reads happening this tick.

### Timeline (Full only)

```
│ ━━━━━━━━━━━━━━━━━━━●━━━━━━━━━━━━━━━━━━━━━━━━ │  ━ off-peak  ━ peak (3pm-9pm)
```

A visual representation of today's peak/off-peak windows with a marker showing where you are now. The legend shows the peak hours in your local timezone. On all-day-free (`schedule.mode == "normal"`) days the bar shows a solid off-peak band with the label `Off-Peak all day ✔`.

---

## Explaining Any Segment

Run `/explain <segment>` (or `/statusline-doctor --explain <segment>`) to get a detailed in-terminal breakdown of what a segment shows, how it's computed, its color thresholds, and when it hides.

```
/explain burn_rate
/explain cache_hit
/explain context_depletion
/explain peak_hours
/explain rate_limits
/explain timeline
```

Run `/explain` with no argument to print a table of all 18 documented segments.

The two invocation paths are equivalent:

| Path                 | Command                                  |
| :------------------- | :--------------------------------------- |
| Direct slash command | `/explain <segment>`                     |
| Via doctor (legacy)  | `/statusline-doctor --explain <segment>` |

---

## Narrator Hook

The statusline shows what's happening right now. The narrator hook tells you what it _means_ and what to do &mdash; as a brief message injected above your next prompt, like a co-pilot reading the dashboard and summarizing.

Every emitted line is intentionally framed so Claude surfaces it as statusline text rather than ordinary chat prose:

```text
//// Statusline note ////
//// -> Burning $18/hr — at this rate your 5-hour budget ends in ~40 min. Consider Sonnet for simple steps. ////
```

**Two tiers, additive** (both shown together when the Haiku gate passes):

### Tier 1: Rules Engine (always on)

- Runs on every hook fire.
- Under 50ms. No API call. No cost.
- 4-axis scoring: urgency x novelty x actionability x uniqueness.
- 15+ templates covering: context depletion, burn rate milestones, cache efficiency, rate limit thresholds, peak vs off-peak windows, cost milestones.
- Output: one advisory sentence matching your current state.

```
Burning $18/hr — at this rate your 5-hour budget ends in ~40 min. Consider Sonnet for simple steps.
```

### Tier 2: Haiku Layer (opt-in)

- Model: `claude-haiku-4-5`.
- Fires every **5 prompts OR 15 minutes** (whichever comes first). Both thresholds are tunable.
- Adds 25-35 words of session narrative reasoning over recent observations.
- Cost: approximately $0.0005 per call.
- Default: **auto-on** when `ANTHROPIC_API_KEY` is set in the environment. Not enabled otherwise.
- Requires internet access to the Anthropic API.

```
Since last check you refactored three components while your cache warmed from 62% to 94%.
Rate limits at 23%, peak hours ended — wide-open runway ahead.
```

**Limitation:** the Haiku layer requires `ANTHROPIC_API_KEY`. Python 3.9+ and Node.js can both call it. Bash-only installs do not run the narrator.

### When it fires

| Event                            | Frequency                                  |
| :------------------------------- | :----------------------------------------- |
| Session start / compact / resume | Always, no throttle                        |
| User prompt submit               | Throttled: minimum 5 min between emissions |

### Session memory

`~/.claude/narrator-memory.json` stores:

- Rolling observations from the last 2 hours
- Last 8 delivered narratives (deduplication)
- Cost milestones crossed this session
- Prompt count
- Summaries of the last 3 prior sessions

This lets the narrator say things like "last time you were working on the auth module" when you resume.

### Narrator language

Auto-detect: if `$LC_ALL` / `$LC_MESSAGES` / `$LANG` starts with `he` (Hebrew locale),
narrator emits Hebrew. Otherwise English.

Runtime switch: `/narrator-lang en`, `/narrator-lang he`, `/narrator-lang en,he`.

Override:

```bash
export STATUSLINE_NARRATOR_LANGS=en      # English only
export STATUSLINE_NARRATOR_LANGS=he      # Hebrew only
export STATUSLINE_NARRATOR_LANGS=en,he   # Both (two lines per emission)
```

### Tuning

```bash
export STATUSLINE_NARRATOR_ENABLED=1               # set to 0 to disable entirely
export STATUSLINE_NARRATOR_HAIKU=auto              # "auto" = on if API key present; "off" = disabled
export STATUSLINE_NARRATOR_HAIKU_INTERVAL_MIN=15   # minimum minutes between Haiku calls
export STATUSLINE_NARRATOR_THROTTLE_MIN=5          # minimum minutes between any narrator message
```

Run `/narrate` to invoke the narrator manually, bypassing the throttle.

No restart is required after changing the language; the hook reads the environment on each invocation.

---

## Telemetry &mdash; Transparency

This plugin sends installer telemetry events, an optional one-shot doctor report, and a daily heartbeat. This section documents exactly what is sent, when, and how to stop it.

### What is sent

#### Install ping

Sent **once per machine at first install time** by the installer flow. Updates emit a separate `update` event, and runtime engines send only the daily heartbeat.

```json
{
  "id": "random 16-char hex id stored in ~/.claude/.statusline-telemetry-id",
  "v": "2.2",
  "engine": "python",
  "tier": "full",
  "os": "linux",
  "event": "install"
}
```

Stored as `install:<id>` in Cloudflare KV. **First-seen-only**: if the key already exists, the new ping is silently discarded. No TTL (permanent record of "this machine installed").

#### Installer result / update events

The installer also emits `install_result` after a fresh install and `update` after an update run. These events carry doctor results and runtime availability flags, and are stored with a 90-day TTL like other telemetry events.

#### Doctor report

Running `doctor.sh --report` sends a one-shot anonymous `doctor` event. It contains only aggregate health counts (`ok` / `warn` / `fail`), the host OS, and the IDs of failed checks.

#### Daily heartbeat

Same payload with `"event": "heartbeat"`, once per calendar day per machine. TTL: 90 days (old machines that stop using the plugin age out automatically).

### What is NOT collected

- No file contents or conversation data.
- No real names, email addresses, or any directly identifying information.
- No session IDs or per-prompt telemetry.
- No IP addresses beyond what the Cloudflare edge sees as part of normal HTTP (and Cloudflare does not log IPs to KV).
- The `id` field is a random 16-character hex value generated once locally and stored in `~/.claude/.statusline-telemetry-id`.

### Endpoint

```
https://statusline-telemetry.nadavf.workers.dev/ping
```

Live stats (public, for transparency):

```
https://statusline-telemetry.nadavf.workers.dev/stats
```

### How to opt out

Set `"telemetry": false` in your config file to disable automatic `install_result`, `update`, and `heartbeat` pings from that machine.

```json
// ~/.claude/statusline-config.json
{
  "tier": "full",
  "telemetry": false
}
```

For a hard override that also blocks `doctor.sh --report`, set:

```bash
export STATUSLINE_DISABLE_TELEMETRY=1
```

This is useful for CI, test harnesses, and machines that must never emit telemetry under any circumstance.

After setting this, the engine checks the flag before every ping attempt. Nothing is queued or deferred.

---

## Color Guide

| Color   | Where          | Meaning                                  |
| :------ | :------------- | :--------------------------------------- |
| Green   | Peak badge     | Off-Peak &mdash; normal rate             |
| Red     | Peak badge     | Deep into peak hours (lots of time left) |
| Yellow  | Peak badge     | Peak ending soon (1-2 hours)             |
| Green   | Peak badge     | Peak almost over (< 30 minutes)          |
| Green   | Git status     | Clean &mdash; all saved                  |
| Yellow  | Git status     | Uncommitted changes                      |
| Cyan    | Environment    | LOCAL                                    |
| Magenta | Environment    | REMOTE (SSH)                             |
| Green   | Cache %        | Excellent reuse (>= 80%)                 |
| Yellow  | Cache %        | Moderate reuse (>= 50%)                  |
| Red     | Cache %        | Low reuse / context depletion warning    |
| Green   | Separators (▸) | Off-Peak                                 |
| Yellow  | Separators (▸) | During Peak                              |

---

## Peak Hours &mdash; How It Works

Anthropic's rate limiting policy adjusts **5-hour session limit** consumption during peak hours. This does **not** change your weekly limit &mdash; only how fast the 5-hour window quota is consumed.

| When                  |  Status  | Pacific Time                | Your time               |
| :-------------------- | :------: | :-------------------------- | :---------------------- |
| Weekdays, peak hours  | **Peak** | 5:00 AM &ndash; 11:00 AM PT | Auto-converted to local |
| Weekdays, other hours | Off-Peak | &mdash;                     | &mdash;                 |
| Weekends (Sat & Sun)  | Off-Peak | All day                     | &mdash;                 |

> **Key insight:** Peak = bad for heavy usage. Your 5-hour limit gets consumed faster. If you have limit-intensive work, consider scheduling it for Off-Peak hours.

### Auto-Timezone

The plugin detects your timezone automatically and converts peak hours to your local time. Handles DST transitions worldwide &mdash; Israel, US (all zones), Europe, Australia, Japan, and everywhere else.

**Examples of the same peak window in different timezones:**

| Timezone              | Peak window displayed as      |
| :-------------------- | :---------------------------- |
| US Pacific (PT)       | 5:00 AM &ndash; 11:00 AM      |
| US Eastern (ET)       | 8:00 AM &ndash; 2:00 PM       |
| Israel (IST)          | 3:00 PM &ndash; 9:00 PM       |
| Central Europe (CET)  | 2:00 PM &ndash; 8:00 PM       |
| Australia East (AEST) | 11:00 PM &ndash; 5:00 AM (+1) |

### Cross-timezone edge case (fixed)

Previous versions failed to detect peak when a Saturday UTC peak window spilled over into Sunday local time for users in positive-offset timezones (e.g. UTC+3). The fix uses a `peak_day_offset` value returned by `peak_hours_to_local()` so the day-of-week check accounts for the date rollover correctly.

---

## Remote Schedule &mdash; Auto-Updating

This is the core innovation of the plugin. Instead of hardcoding peak hours, the plugin fetches a `schedule.json` file from GitHub:

```
https://raw.githubusercontent.com/Nadav-Fux/claude-2x-statusline/main/schedule.json
```

**How it works:**

1. Every **6 hours**, the plugin checks for a new schedule (configurable via `schedule_cache_hours`)
2. The fetched schedule is cached locally at `~/.claude/statusline-schedule.json`
3. If the fetch fails, the cached version is used
4. If no cache exists, a hardcoded fallback is used
5. The schedule controls: peak hours, labels, feature flags, and optional banner messages

**What this means for you:** If Anthropic changes peak hours from 5-11 AM to 6 AM-12 PM, or adds weekend peaks, or removes peak hours entirely &mdash; the maintainer updates `schedule.json` on GitHub and your statusline reflects the change on the next refresh. Zero action required from you.

**What the schedule controls:**

| Field                                    | Purpose                                   |
| :--------------------------------------- | :---------------------------------------- |
| `peak.start` / `peak.end`                | Peak hour range (in PT)                   |
| `peak.days`                              | Which days have peak hours (1=Mon, 7=Sun) |
| `peak.label_peak` / `peak.label_offpeak` | Display labels                            |
| `default_tier`                           | Recommended tier for new installs         |
| `banner.text`                            | Optional announcement shown to all users  |
| `banner.expires`                         | Auto-expiry date for the banner           |
| `features.*`                             | Toggle segments on/off remotely           |

---

## Engines (Auto-Detected)

The plugin ships with 4 engine implementations. The wrapper script auto-detects the best available runtime:

| Priority | Engine         | Platform              | Dependencies                                                                 |
| :------: | :------------- | :-------------------- | :--------------------------------------------------------------------------- |
|    1     | **Python**     | macOS, Linux, Windows | Python 3 (no pip packages required for core; `tzdata` for full DST coverage) |
|    2     | **Node.js**    | All                   | Node.js                                                                      |
|    3     | **Bash**       | macOS, Linux          | None                                                                         |
|    4     | **PowerShell** | Windows               | PowerShell 5.1+ (built-in)                                                   |

Detection order: Python &rarr; Node.js &rarr; Bash. On Windows, the installer prefers **Git Bash + `statusline.sh`** when available, and falls back to **PowerShell + `statusline.ps1`** when Bash is missing. Feature parity table:

| Feature                |   Python   | Node.js |  Bash   | PowerShell |
| :--------------------- | :--------: | :-----: | :-----: | :--------: |
| Full statusline        |    Yes     |   Yes   |   Yes   |    Yes     |
| Narrator hook          | Yes (3.9+) |   Yes   |   No    |     No     |
| Rolling-window metrics |    Yes     |   Yes   | Partial |  Partial   |
| `/explain` command     |    Yes     |   Yes   |   No    |     No     |

**Confirmed for CLI / terminal.** VS Code and JetBrains extensions may also work (they share `~/.claude/settings.json`) but are not officially documented yet.

---

## Windows Support

Windows requires a few extra accommodations that the installer and hook scripts handle automatically.

### Install paths

- If Git Bash is installed, `install.ps1` wires the main statusline through `bash.exe statusline.sh` so Windows gets the same runtime resolver and narrator path as macOS/Linux.
- If Git Bash is not installed, `install.ps1` falls back to `statusline.ps1`. The statusline still works, but narrator hooks are skipped until Git Bash or WSL is available.
- `update.ps1` supports both git-clone installs and legacy non-git installs by bootstrapping a fresh source tree when needed.

### Runtime resolver

`lib/resolve-runtime.sh` rejects `C:\Program Files\WindowsApps\*.exe` paths. These are Microsoft Store app-execution aliases: the files appear to exist and are named `python.exe`, but when invoked without the Store app installed they print a nag message and exit with a non-zero code instead of running Python. The resolver detects this pattern and skips to the next candidate.

### Portable Python probing

After rejecting Store stubs, the resolver checks these locations in order:

```
~/tools/python-*/python.exe
~/AppData/Local/Programs/Python/Python3*/python.exe
~/AppData/Local/Microsoft/WindowsApps/python.exe   ← rejected if Store stub
C:/Python3*/python.exe
```

### Path conversion in hooks

Hook scripts run under Git Bash, where paths use `/c/Users/...` notation. When passing paths to Python or other Windows-native tools, hooks use `cygpath -w` to convert to `C:\Users\...` so the tool can locate modules correctly.

### UTF-8 enforcement

Hook scripts force UTF-8 on stdout before invoking Python. Without this, on systems using the default cp1252 code page, non-ASCII characters in narrator messages (arrows, box-drawing characters) can cause UnicodeEncodeError and silently kill the narrator output.

---

## Testing

The test suite covers the most complex and historically bug-prone parts of the plugin:

```bash
# Install dependencies
pip install pytest tzdata

# Run all tests
python -m pytest tests/ -v

# Run worker telemetry tests
npm run test:worker
```

Current status: **106 pytest passes, 1 expected skip, plus 3 Node worker tests**.

Coverage areas:

| Area             | What's tested                                                                       |
| :--------------- | :---------------------------------------------------------------------------------- |
| Peak hours       | Edge cases: exact boundary minutes, overnight windows (AEST), DST transitions       |
| Cross-timezone   | Saturday UTC peak spilling into Sunday UTC+3, negative-offset zones                 |
| Rolling state    | Ring buffer overflow, corrupt file recovery, atomic write simulation                |
| Narrator scoring | 4-axis scoring, template selection, deduplication, throttle logic                   |
| Narrator memory  | Rolling observations, session boundary, prior-session retention                     |
| JSON wiring      | Installer merge/query helpers for settings.json, config.json, and doctor failed IDs |
| Telemetry        | Installer install-event flow, runtime heartbeat opt-out, persisted anonymous ID     |
| Worker failures  | `/failures` auth, per-OS aggregation, fail-index rollups, update/install summaries  |

---

## File Layout

```
~/.claude/cc-2x-statusline/
  statusline.sh          # Entry point (engine selector)
  statusline.ps1         # Windows entry point
  lib/
    resolve-runtime.sh   # Shared runtime resolver (rejects Store stubs, probes portables)
  engines/
    python-engine.py     # Primary engine (full features + Narrator)
    node-engine.js       # Node.js engine
    bash-engine.sh       # Pure bash fallback
  commands/
    statusline-onboarding.md
    statusline-minimal.md
    statusline-standard.md
    statusline-full.md
    statusline-tier.md
  skills/                # Skills for setup, onboarding, and tier changes
  tests/                 # 107 pytest cases
  schedule.json          # Bundled schedule (fallback)
  plugin.json            # Plugin metadata
  install.sh             # Interactive installer
  install.ps1            # Windows installer
  uninstall.sh           # Clean uninstaller

~/.claude/
  statusline-config.json      # Your config (tier, schedule URL, telemetry flag)
  statusline-schedule.json    # Cached remote schedule
  statusline-state.json       # Rolling 60-min metrics ring buffer
  narrator-memory.json        # Narrator session memory
  settings.json               # Claude Code settings (statusLine entry)
```

---

## Debug

```bash
STATUSLINE_DEBUG=1 echo '{}' | bash ~/.claude/cc-2x-statusline/statusline.sh
```

This runs the statusline with debug output to stderr, showing config loading, schedule resolution, timezone detection, runtime selection, and segment rendering.

## Uninstall

```bash
bash ~/.claude/cc-2x-statusline/uninstall.sh
```

Removes the plugin files, config, cached schedule, state files, narrator memory, and the `statusLine` entry from `settings.json`.

---

## For Claude Code Agents

If you are a Claude Code instance and a user asks you to install this plugin, here is the procedure:

1. Clone: `git clone https://github.com/Nadav-Fux/claude-2x-statusline.git ~/.claude/cc-2x-statusline`
2. Run: `bash ~/.claude/cc-2x-statusline/install.sh` (or follow the manual steps below)
3. The installer will ask which tier the user wants (default: Full)
4. Tell the user to restart Claude Code

**Manual install (if the interactive installer is not suitable):**

```bash
# Copy files
mkdir -p ~/.claude/cc-2x-statusline
cp -r /path/to/repo/* ~/.claude/cc-2x-statusline/
chmod +x ~/.claude/cc-2x-statusline/statusline.sh

# Write config
cat > ~/.claude/statusline-config.json << 'EOF'
{
  "tier": "full",
  "schedule_url": "https://raw.githubusercontent.com/Nadav-Fux/claude-2x-statusline/main/schedule.json",
  "schedule_cache_hours": 3
}
EOF

# Update settings.json to register the statusline
python3 -c "
import json
p = '$HOME/.claude/settings.json'
with open(p) as f: s = json.load(f)
s['statusLine'] = {'type': 'command', 'command': 'bash $HOME/.claude/cc-2x-statusline/statusline.sh'}
with open(p, 'w') as f: json.dump(s, f, indent=2)
"

# Install slash commands
cp ~/.claude/cc-2x-statusline/commands/statusline-*.md ~/.claude/commands/
```

---

<div align="center">

**[Live Preview & Tier Picker](https://statusline.nvision.me)** &nbsp;&bull;&nbsp; [PolyForm Noncommercial 1.0.0](LICENSE) &nbsp;&bull;&nbsp; [Copyright](COPYRIGHT.md) &nbsp;&bull;&nbsp; by [Nadav Fux](https://github.com/Nadav-Fux)

</div>
