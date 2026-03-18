<div align="center">

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

## תצוגה חיה — איך זה נראה

### 2X פעיל — הרבה זמן (ירוק)
![2X Active](assets/preview-standard.svg)

### 2X פעיל — נגמר בקרוב! (אדום)
![2X Urgent](assets/preview-urgent.svg)

### שעות שיא — 1X (אפור, חצים צהובים)
![Peak](assets/preview-peak.svg)

### דשבורד מורחב (טיר Full בלבד)
![Full Dashboard](assets/preview-full.svg)

**שורה 2 — Timeline:** פס צבעוני שמראה את שעות ה-2X (ירוק) מול שעות שיא (צהוב) לאורך היום. הנקודה הלבנה = עכשיו.

**שורה 3 — Rate Limits:**
- `5h ▰▰▱▱▱▱▱▱▱▱ 20%` = כמה מהמכסה של 5 שעות ניצלת, מתאפס ב-5:00am
- `weekly ▰▰▰▱▱▱▱▱▱▱ 33%` = מכסה שבועית, מתאפסת ב-19/3 בשעה 11:00pm

---

## 3 טירים — בחר מה שמתאים לך

| טיר | מה מוצג | למי זה |
|-----|---------|--------|
| **Minimal** | 2X סטטוס + git | מי שרוצה נקי ומינימלי |
| **Standard** | + מודל + tokens + עלות | שימוש יומיומי (ברירת מחדל) |
| **Full** | + timeline + rate limits | Power users שרוצים הכל |

### Minimal
![Minimal](assets/preview-minimal.svg)

### Standard
![Standard](assets/preview-standard.svg)

### Full
![Full](assets/preview-full.svg)

---

## התקנה

### אפשרות 1: פשוט תגיד ל-Claude (הכי קל)

ב-Claude Code, כתוב בצ'אט:
```
תתקין לי את claude-2x-statusline מ-GitHub של Nadav-Fux
```
Claude ידע להתקין את הפלאגין, להגדיר את ה-statusline ולהציע לך טיר.

### אפשרות 2: פלאגין ל-Claude Code

ב-Claude Code, הקלד:
```
/plugin
```
בחר את `Nadav-Fux/claude-2x-statusline`. אחרי ההתקנה, הקלד `/statusline setup` לבחור טיר.

### אפשרות 2: npx (פקודה אחת)

```bash
npx claude-2x-statusline
```

### אפשרות 3: Git clone

**macOS / Linux:**
```bash
git clone https://github.com/Nadav-Fux/claude-2x-statusline.git ~/.claude/cc-2x-statusline \
  && bash ~/.claude/cc-2x-statusline/install.sh
```

**Windows (PowerShell):**
```powershell
irm https://raw.githubusercontent.com/Nadav-Fux/claude-2x-statusline/main/install.ps1 | iex
```

### אפשרות 4: curl (שורה אחת)

```bash
curl -fsSL https://raw.githubusercontent.com/Nadav-Fux/claude-2x-statusline/main/install.sh | bash
```

---

## שינוי טיר

אחרי התקנה כפלאגין, אפשר להחליף בכל רגע:

| פקודה | מה עושה |
|-------|---------|
| `/statusline setup` | בוחר טיר עם שאלה אינטראקטיבית |
| `/statusline minimal` | עובר ל-Minimal |
| `/statusline standard` | עובר ל-Standard |
| `/statusline full` | עובר ל-Full עם דשבורד |

או לערוך ישירות את `~/.claude/statusline-config.json`:

```json
{
  "tier": "full",
  "promo_start": 20260313,
  "promo_end": 20260327
}
```

---

## הסברים — מה כל דבר אומר

### שורה ראשית

```
 2x ACTIVE  10h 50m left 9d left ▸ Opus 4.6 ▸ 350K/1.0M 35% ▸ $12.5 ▸ main 2 unsaved
 ╰── 2X ──╯ ╰── זמן ──╯ ╰ימים╯   ╰ מודל ╯   ╰── tokens ──╯   ╰$$$╯   ╰── git ──╯
```

| חלק | משמעות |
|------|--------|
| `2x ACTIVE` | מבצע ה-2X פעיל — מקבלים כפול שימוש |
| `10h 50m left` | כמה זמן נשאר עד שהחלון הנוכחי נגמר |
| `9d left` | כמה ימים נשארו למבצע כולו |
| `▸` | חץ מפריד — **ירוק** כש-2X, **צהוב** ב-peak |
| `Opus 4.6` | המודל שרץ עכשיו |
| `350K/1.0M 35%` | ניצלת 350K tokens מתוך 1M (35%) |
| `$12.5` | עלות הסשן הנוכחי |
| `main` | branch ב-git |
| `2 unsaved` | 2 קבצים ששונו ולא נדחפו ל-GitHub |

### צבעי 2X

| צבע | משמעות | זמן שנשאר |
|-----|--------|-----------|
| ירוק | בנוח, יש זמן | מעל 3 שעות |
| צהוב | כדאי לתכנן | 1-3 שעות |
| אדום | אחרון! תנצל עכשיו | פחות משעה |
| אפור (PEAK) | שעות שיא — 1X | — |

### שורת Rate Limits (Full בלבד)

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

## מנועים (זיהוי אוטומטי)

| מנוע | פלטפורמה | תלויות |
|------|----------|--------|
| **Python** | macOS, Linux, Windows | Python 3 (ללא חבילות חיצוניות) |
| **PowerShell** | Windows | PowerShell 5.1+ (מובנה) |
| **Node.js** | הכל | Node.js |
| **Pure bash** | הכל | שום דבר |

ה-wrapper מזהה אוטומטית: Python → Node.js → bash. על Windows משתמש ב-PowerShell.

---

## דיבאג

משהו לא עובד? הפעל מצב debug:

```bash
STATUSLINE_DEBUG=1 echo '{}' | bash ~/.claude/cc-2x-statusline/statusline.sh
```

---

## הסרה

```bash
bash ~/.claude/cc-2x-statusline/uninstall.sh
```

---

<div align="center">

**[Live Preview & Tier Picker](https://statusline.nvision.me)** | [MIT License](LICENSE)

</div>

---

# claude-2x-statusline

### Modular statusline for Claude Code

Track the 2X promotion, monitor usage, see rate limits — all in one line.

## Preview

### Standard
![Standard](assets/preview-standard.svg)

### Full (with dashboard)
![Full](assets/preview-full.svg)

### During peak (1X)
![Peak](assets/preview-peak.svg)

### Almost out of time!
![Urgent](assets/preview-urgent.svg)

## Install

### Option 1: Just ask Claude (easiest)

In Claude Code, type:
```
Install the claude-2x-statusline plugin from Nadav-Fux on GitHub
```
Claude will install the plugin, configure the statusline, and offer you a tier.

### Option 2: Claude Code Plugin

```
/plugin
```
Select `Nadav-Fux/claude-2x-statusline`. Then use `/statusline setup` to pick your tier.

### Option 2: npx
```bash
npx claude-2x-statusline
```

### Option 3: Git clone

**macOS / Linux:**
```bash
git clone https://github.com/Nadav-Fux/claude-2x-statusline.git ~/.claude/cc-2x-statusline \
  && bash ~/.claude/cc-2x-statusline/install.sh
```

**Windows (PowerShell):**
```powershell
irm https://raw.githubusercontent.com/Nadav-Fux/claude-2x-statusline/main/install.ps1 | iex
```

### Option 4: curl
```bash
curl -fsSL https://raw.githubusercontent.com/Nadav-Fux/claude-2x-statusline/main/install.sh | bash
```

## Switch Tier

| Command | What |
|---------|------|
| `/statusline setup` | Interactive tier picker |
| `/statusline minimal` | Switch to minimal |
| `/statusline standard` | Switch to standard |
| `/statusline full` | Switch to full + dashboard |

Or edit `~/.claude/statusline-config.json`:
```json
{
  "tier": "full",
  "promo_start": 20260313,
  "promo_end": 20260327
}
```

## What Everything Means

| Part | Meaning |
|------|---------|
| `2x ACTIVE` | 2X promotion is active — doubled usage |
| `10h left` | Time until current 2X window ends |
| `9d left` | Days remaining in the promotion |
| `▸` | Arrow separator — green during 2X, yellow during peak |
| `Opus 4.6` | Active model |
| `350K/1.0M 35%` | 350K of 1M tokens used (35%) |
| `$12.5` | Current session cost |
| `main` | Git branch |
| `2 unsaved` | Files changed but not pushed to GitHub |

### Rate Limits (Full tier, line 3)

| Part | Meaning |
|------|---------|
| `5h` | 5-hour usage window |
| `▰▰▱▱▱▱▱▱▱▱ 20%` | 20% of limit used |
| `⟳ 5:00am` | Resets at 5:00am |
| `weekly ▰▰▰▱▱▱▱▱▱▱ 33%` | Weekly limit 33% used |
| `⟳ 19/3 11:00pm` | Resets March 19 at 11:00pm |

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
