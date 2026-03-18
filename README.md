<div align="center">

```
     ___  __  __     ___  ___  ___  ___     ___   ___   ___   ___
    / __|| | / _ \  | _ || _ \| __|  _ \   / __| / _ \ |   \ | __|
   | (__ | || (_) | |   ||   /| _| | |_)  | (__ | (_) || |) || _|
    \___||_| \___/  |_|_||_|_\|___||___/   \___| \___/ |___/ |___|

    ╔══════════════════════════════════════════════════════════════╗
    ║  ⚡ 2x ACTIVE  5h left ▸ Opus 4.6 ▸ 27% ▸ $7.96 ▸ main   ║
    ║  │ ━━━━━━━━━━━━━●━━━━━━━━━━━━ │  ━ 2x ━ peak              ║
    ║  │ ▸ 5h 17%  ·  weekly 34%   │                            ║
    ╚══════════════════════════════════════════════════════════════╝
```

# claude-2x-statusline

### שורת סטטוס מודולרית ל-Claude Code

מעקב אחרי מבצע ה-2X, מידע על המודל, ניצול context, rate limits — הכל בשורה אחת.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Claude Code](https://img.shields.io/badge/Claude_Code-plugin-blueviolet)](#)
[![Cross-platform](https://img.shields.io/badge/Platform-macOS%20%7C%20Linux%20%7C%20Windows-green)](#דרישות)

---

</div>

## מה זה?

תוסף ל-Claude Code שמציג שורת סטטוס חיה בתחתית הטרמינל. רואים במבט אחד:
- האם מבצע ה-**2X** פעיל וכמה זמן נשאר
- איזה **מודל** רץ (Opus, Sonnet...)
- כמה **tokens** ניצלת מה-context window
- כמה **עלה** הסשן הנוכחי בדולרים
- מצב ה-**git** — קבצים שלא נשמרו / לא נדחפו
- **LOCAL** / **REMOTE** — רואים אם רצים מקומית או על שרת

## תצוגה חיה — איך זה נראה

### Standard (מומלץ)
![Standard](assets/preview-standard.svg)

### Full — עם דשבורד מורחב
![Full Dashboard](assets/preview-full.svg)

### שעות שיא — 1X
![Peak](assets/preview-peak.svg)

### נגמר בקרוב!
![Urgent](assets/preview-urgent.svg)

---

## התקנה — 30 שניות

### הדרך הכי קלה: תגיד ל-Claude

פשוט תדביק ב-Claude Code:

```
תתקין לי את claude-2x-statusline מ-github.com/Nadav-Fux/claude-2x-statusline
```

Claude יריץ clone, install, יגדיר הכל וישאל איזה טיר אתה רוצה.

### או: שורה אחת בטרמינל

**macOS / Linux:**
```bash
git clone https://github.com/Nadav-Fux/claude-2x-statusline.git ~/.claude/cc-2x-statusline && bash ~/.claude/cc-2x-statusline/install.sh
```

**Windows (PowerShell):**
```powershell
irm https://raw.githubusercontent.com/Nadav-Fux/claude-2x-statusline/main/install.ps1 | iex
```

ה-installer שואל איזה טיר, מגדיר את ה-statusline, ומתקין slash commands. **רק צריך לאתחל את Claude Code.**

---

## 3 טירים — בחר מה שמתאים לך

> **המלצה:** התחל עם **Full** — מקבלים הכל כולל דשבורד עם timeline ו-rate limits. תמיד אפשר להוריד.

| טיר | מה מוצג | למי זה |
|-----|---------|--------|
| **Minimal** | 2X + מודל + CTX% + 5H% + git | מי שרוצה נקי ומינימלי |
| **Standard** | + tokens מפורט + עלות + בר rate limit | שימוש יומיומי |
| **Full** ⭐ | + timeline + rate limits דשבורד | **מומלץ** — רואים הכל |

### Minimal
```
⚡ 2x ACTIVE 5h left ▸ Opus 4.6 ▸ CTX 27% ▸ 17% 5H ▸ LOCAL ▸ main saved
```

### Standard
```
⚡ 2x ACTIVE 5h left ▸ Opus 4.6 ▸ 270K/1.0M 27% ▸ $7.96 ▸ ▰▱▱▱▱▱▱▱▱▱ 17% ▸ LOCAL ▸ main 2 unsaved
```

### Full (מומלץ)
```
⚡ 2x ACTIVE 5h left ▸ Opus 4.6 ▸ 270K/1.0M 27% ▸ $7.96 ▸ LOCAL ▸ main 2 unsaved
│ ━━━━━━━━━━━━━━━━━━━●━━━━━━━━━━━━━━━━━━━━━━━━ │  ━ 2x ━ peak
│ ▸ 5h ▰▱▱▱▱▱▱▱▱▱ 17% ⟳ 3:00pm · weekly ▰▰▰▱▱▱▱▱▱▱ 34% ⟳ 19/3 11:00pm │
```

---

## שינוי טיר — Slash Commands

אחרי התקנה, אפשר להחליף בכל רגע מתוך Claude Code:

| פקודה | מה עושה |
|-------|---------|
| `/statusline-minimal` | עובר ל-Minimal |
| `/statusline-standard` | עובר ל-Standard |
| `/statusline-full` | עובר ל-Full עם דשבורד |

או לערוך ישירות:
```bash
~/.claude/statusline-config.json
```

---

## הסברים — מה כל דבר אומר

### שורה ראשית

```
 2x ACTIVE  10h 50m left 9d left ▸ Opus 4.6 ▸ 350K/1.0M 35% ▸ $12.50 ▸ LOCAL ▸ main 2 unsaved
 ╰── 2X ──╯ ╰── זמן ──╯ ╰ימים╯   ╰ מודל ╯   ╰── tokens ──╯  ╰$$╯    ╰סביבה╯  ╰── git ──╯
```

| חלק | משמעות |
|------|--------|
| `2x ACTIVE` | מבצע ה-2X פעיל — מקבלים כפול שימוש |
| `10h 50m left` | כמה זמן נשאר עד שהחלון הנוכחי נגמר |
| `9d left` | כמה ימים נשארו למבצע כולו |
| `▸` | חץ מפריד — **ירוק** כש-2X, **צהוב** ב-peak |
| `Opus 4.6` | המודל שרץ עכשיו |
| `350K/1.0M 35%` | ניצלת 350K tokens מתוך 1M (35%) |
| `$12.50` | עלות הסשן הנוכחי |
| `LOCAL` / `REMOTE` | רץ מקומית (תכלת) או על שרת (סגול) |
| `main` | branch ב-git |
| `2 unsaved` / `saved` | מצב git — קבצים שלא נשמרו, או הכל שמור (ירוק) |

### צבעי 2X

| צבע | משמעות | זמן שנשאר |
|-----|--------|-----------|
| ירוק | בנוח, יש זמן | מעל 3 שעות |
| צהוב | כדאי לתכנן | 1-3 שעות |
| אדום | אחרון! תנצל עכשיו | פחות משעה |
| אפור (PEAK) | שעות שיא — 1X | — |

### דשבורד Rate Limits (Full בלבד)

```
│ ▸ 5h ▰▰▱▱▱▱▱▱▱▱ 20% ⟳ 5:00am · weekly ▰▰▰▱▱▱▱▱▱▱ 33% ⟳ 19/3 11:00pm │
```

| חלק | משמעות |
|------|--------|
| `5h` | מכסה של 5 שעות (current window) |
| `▰▰▱▱▱▱▱▱▱▱ 20%` | ניצלת 20% מהמכסה |
| `⟳ 5:00am` | מתאפס ב-5 בבוקר |
| `weekly` | מכסה שבועית |
| `⟳ 19/3 11:00pm` | מתאפסת ב-19 במרץ ב-11 בלילה |

---

## לוח זמני המבצע

המבצע של Claude — מרץ 2026: **כפול שימוש בשעות מחוץ לשיא**.

| מתי | סטטוס | שעון ישראל |
|------|:------:|-------------|
| ימי חול מחוץ לשיא | **2X** | 00:00–14:00, 20:00–00:00 |
| ימי חול שעות שיא | 1X | 14:00–20:00 |
| סופשבוע | **2X** | שבת 9:00 → שני 9:00 |

**תאריכים: 13–27 במרץ 2026.** אפשר לשנות ב-config לקידומים עתידיים.

---

## דרישות

- Claude Code עם תמיכה ב-statusline
- **אחד מ:** Python 3 | Node.js | PowerShell 5.1+ | bash

## מנועים (זיהוי אוטומטי)

| מנוע | פלטפורמה | תלויות |
|------|----------|--------|
| **Python** | macOS, Linux, Windows | Python 3 (ללא חבילות חיצוניות) |
| **PowerShell** | Windows | PowerShell 5.1+ (מובנה) |
| **Node.js** | הכל | Node.js |
| **Pure bash** | הכל | שום דבר |

ה-wrapper מזהה אוטומטית: Python → Node.js → bash. על Windows משתמש ב-PowerShell.

## דיבאג

```bash
STATUSLINE_DEBUG=1 echo '{}' | bash ~/.claude/cc-2x-statusline/statusline.sh
```

## הסרה

```bash
bash ~/.claude/cc-2x-statusline/uninstall.sh
```

---

<div align="center">

**[Live Preview & Tier Picker](https://statusline.nvision.me)** | [MIT License](LICENSE)

</div>

---

# claude-2x-statusline (English)

### Modular statusline for Claude Code

Track the 2X promotion, monitor usage, see rate limits — all in one line.

## Install — 30 seconds

### Easiest: Just ask Claude

Paste in Claude Code:

```
Install the claude-2x-statusline plugin from github.com/Nadav-Fux/claude-2x-statusline
```

Claude will clone, install, configure everything, and ask which tier you want.

### Or: One-liner

**macOS / Linux:**
```bash
git clone https://github.com/Nadav-Fux/claude-2x-statusline.git ~/.claude/cc-2x-statusline && bash ~/.claude/cc-2x-statusline/install.sh
```

**Windows (PowerShell):**
```powershell
irm https://raw.githubusercontent.com/Nadav-Fux/claude-2x-statusline/main/install.ps1 | iex
```

## 3 Tiers

> **Recommendation:** Start with **Full** — you get everything including timeline and rate limits dashboard. You can always switch down.

| Tier | What you see | Best for |
|------|-------------|----------|
| **Minimal** | 2X + model + CTX% + 5H% + git | Clean and minimal |
| **Standard** | + detailed tokens + cost + rate limit bar | Daily use |
| **Full** ⭐ | + timeline + rate limits dashboard | **Recommended** — see everything |

## Switch Tier — Slash Commands

| Command | What it does |
|---------|-------------|
| `/statusline-minimal` | Switch to Minimal |
| `/statusline-standard` | Switch to Standard |
| `/statusline-full` | Switch to Full with dashboard |

## What Everything Means

| Part | Meaning |
|------|---------|
| `2x ACTIVE` | 2X promotion is active — doubled usage |
| `10h left` | Time until current 2X window ends |
| `9d left` | Days remaining in the promotion |
| `▸` | Arrow separator — green during 2X, yellow during peak |
| `Opus 4.6` | Active model |
| `350K/1.0M 35%` | 350K of 1M tokens used (35%) |
| `$12.50` | Current session cost |
| `LOCAL` / `REMOTE` | Running locally (cyan) or via SSH (magenta) |
| `main` | Git branch |
| `2 unsaved` / `saved` | Git status — unsaved changes, or all clean (green) |

## Promotion Schedule (Israel Time)

| When | Status | Hours |
|------|:------:|-------|
| Weekdays off-peak | **2X** | 00:00–14:00, 20:00–00:00 |
| Weekdays peak | 1X | 14:00–20:00 |
| Weekends | **2X** | Saturday 9:00 → Monday 9:00 |

**Active: March 13–27, 2026.**

## Requirements

- Claude Code with statusline support
- **One of:** Python 3 | Node.js | PowerShell 5.1+ | bash

## Uninstall

```bash
bash ~/.claude/cc-2x-statusline/uninstall.sh
```

---

<div align="center">

**[Live Preview](https://statusline.nvision.me)** | [MIT License](LICENSE)

</div>
