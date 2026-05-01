# Rich doctor diagnostics — 3-tier privacy + auto-upload on failure

**Date:** 2026-04-20

---

## English

### The problem: debugging failures was a guessing game

Until now, when a user reported that their statusline was broken, the doctor could only tell us *which check IDs failed* — `settings`, `hijack`, `exec`, and so on. We couldn't see the actual error messages, the command string that failed, or the runtime environment. Every support interaction turned into a back-and-forth: "can you paste the output of doctor.sh? can you share your settings.json? what Python version are you on?"

That friction is gone.

### The solution: rich diagnostics

When any doctor check fails and the diagnostics level is `full` (the default), doctor now automatically uploads a **sanitized full report** to the maintainer's endpoint. The report includes:

- All check results with their status, titles, and detail messages
- The active runtime (Python / Node / Bash), OS, and plugin version
- A stable per-machine **diagnostic code** shown to the user

The flow:

1. User runs doctor, sees a failure, sees their diagnostic code at the bottom.
2. User sends the maintainer their code in a DM or email — one line.
3. Maintainer pulls the report by code. Immediate full context. No manual share commands, no copy-paste, no five rounds of follow-up questions.

### Sanitization — what leaves your machine

Before any data is sent, the report passes through `sanitize_report()`:

| Before | After |
|:-------|:------|
| `/home/alice/...` or `/c/Users/Alice/...` | `~/...` |
| Your actual username | `<user>` |
| Your actual hostname | `<host>` |

What is **never** in the report: conversation content, file contents, API keys, tokens, or any personal data beyond the already-opaque diagnostic code. The 30-day TTL on full reports means data is automatically deleted from the server after a month.

### Diagnostic code

The code is `sha256(hostname + ":" + username).hex()[:8]` — an 8-character hex string. It is:

- **Stable**: same value on every doctor run on this machine.
- **Anonymous**: one-way hash, cannot be reversed.
- **Shown at the end of every doctor run** (unless telemetry is off):

```
Diagnostic code: abc12345 (telemetry: full — see README to change privacy)
```

When telemetry is off:

```
Telemetry: off — no diagnostics sent.
```

### 3 privacy levels

| Level | What is sent | How to set |
|:------|:------------|:----------|
| `full` (default) | Summary ping always; full sanitized report when any check fails | No config key needed |
| `minimal` | Summary ping only (counts + failed check IDs) | `"diagnostics": "minimal"` |
| `off` | Nothing ever | `"telemetry": false` |

**Example config snippets:**

```json
// Full level — default, most helpful for debugging:
{ "tier": "full" }

// Minimal — just aggregate counts, no full report:
{ "tier": "full", "diagnostics": "minimal" }

// Off — zero network calls from doctor:
{ "tier": "full", "telemetry": false }
```

All three levels are documented in `README.md > Telemetry > Privacy levels`.

### Summary ping (unchanged, now always-on)

The existing summary ping — aggregate counts + failed check IDs, no detail strings — was previously opt-in via `--report`. It is now sent automatically at every doctor run at both `full` and `minimal` levels. The `--report` flag still exists but is a no-op (backward compatible).

### Technical notes

- The full report upload is a **background fire-and-forget** POST. Doctor does not block on the response and exits immediately after dispatching it.
- The upload chain tries `curl`, then `wget`, then a Python stdlib `urllib` fallback — the same pattern used by `install.sh` telemetry.
- The worker endpoint `/doctor/submit` responds `{"code": "abc12345"}` but doctor does not parse the response.
- Full reports are stored under a 30-day TTL. Summary pings are stored under a 90-day TTL.

---

<div dir="rtl">

## עברית

### הבעיה: דיבאגינג היה ניחוש

עד עכשיו, כשמשתמש דיווח שה-statusline שלו שבור, ה-doctor יכל להגיד לנו רק *אילו check IDs נכשלו* — `settings`, `hijack`, `exec` וכו'. לא ראינו את הודעות השגיאה האמיתיות, את הפקודה שנכשלה, או את סביבת ה-runtime. כל פנייה לתמיכה הפכה לאינסוף שאלות: "תוכל להדביק את הפלט של doctor.sh? תוכל לשתף את settings.json? איזה גרסת Python יש לך?"

החיכוך הזה נגמר.

### הפתרון: diagnostics עשיר

כשבדיקה כלשהי נכשלת ורמת ה-diagnostics היא `full` (ברירת המחדל), ה-doctor מעלה עכשיו אוטומטית **דוח מלא מסונטז** ל-endpoint של המתחזק. הדוח כולל:

- כל תוצאות הבדיקות עם הסטטוס, הכותרות, והודעות הפירוט שלהן
- ה-runtime הפעיל (Python / Node / Bash), מערכת ההפעלה, וגרסת התוסף
- **קוד אבחון** יציב ואנונימי שמוצג למשתמש

הזרימה:

1. משתמש מריץ doctor, רואה כישלון, רואה את קוד האבחון שלו בתחתית.
2. משתמש שולח למתחזק את הקוד ב-DM או במייל — שורה אחת.
3. המתחזק מושך את הדוח לפי הקוד. הקשר מלא מיד. ללא פקודות שיתוף ידניות, ללא copy-paste, ללא חמש סבבי שאלות נוספות.

### סניטיזציה — מה יוצא מהמכשיר שלך

לפני שליחת כל מידע, הדוח עובר דרך `sanitize_report()`:

| לפני | אחרי |
|:-----|:-----|
| `/home/alice/...` או `/c/Users/Alice/...` | `~/...` |
| שם המשתמש האמיתי שלך | `<user>` |
| ה-hostname האמיתי שלך | `<host>` |

מה **לעולם לא** נמצא בדוח: תוכן שיחות, תוכן קבצים, מפתחות API, טוקנים, או כל מידע אישי מעבר לקוד האבחון האטום ממילא. TTL של 30 יום על דוחות מלאים אומר שהנתונים נמחקים אוטומטית מהשרת אחרי חודש.

### קוד אבחון

הקוד הוא `sha256(hostname + ":" + username).hex()[:8]` — מחרוזת hex בת 8 תווים. הוא:

- **יציב**: אותו ערך בכל הרצת doctor במכשיר הזה.
- **אנונימי**: hash חד-כיווני, לא ניתן לפיענוח.
- **מוצג בסוף כל הרצת doctor** (אלא אם telemetry כבוי):

```
Diagnostic code: abc12345 (telemetry: full — see README to change privacy)
```

כשה-telemetry כבוי:

```
Telemetry: off — no diagnostics sent.
```

### 3 רמות פרטיות

| רמה | מה נשלח | איך להגדיר |
|:----|:--------|:----------|
| `full` (ברירת מחדל) | סיכום תמיד; דוח מלא מסונטז כשבדיקה נכשלת | אין צורך במפתח config |
| `minimal` | סיכום בלבד (ספירות + check IDs שנכשלו) | `"diagnostics": "minimal"` |
| `off` | כלום לעולם | `"telemetry": false` |

**דוגמאות config:**

```json
// רמה מלאה — ברירת מחדל, הכי שימושית לדיבאגינג:
{ "tier": "full" }

// מינימלי — רק ספירות מצטברות, ללא דוח מלא:
{ "tier": "full", "diagnostics": "minimal" }

// כבוי — אפס קריאות רשת מ-doctor:
{ "tier": "full", "telemetry": false }
```

### הערות טכניות

- העלאת הדוח המלא היא **background fire-and-forget POST**. ה-doctor לא מחכה לתשובה ויוצא מיד אחרי שליחת הבקשה.
- שרשרת ההעלאה מנסה `curl`, אחר כך `wget`, אחר כך fallback של Python stdlib `urllib` — אותו תבנית שמשמש את telemetry של `install.sh`.
- ה-TTL על דוחות מלאים הוא 30 יום. ה-TTL על summary pings הוא 90 יום.
- הדגל `--report` עדיין קיים אבל הפך ל-no-op (תאימות לאחור). ה-telemetry נשלח עכשיו אוטומטית לפי רמת ה-config.

</div>
