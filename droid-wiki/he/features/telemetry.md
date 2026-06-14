# טלמטריה

## מטרה

מעקב שימוש אנונימי שאומר למתחזק כמה אנשים משתמשים בפלאגין, אילו מנועים ורמות פופולריים, והאם התקנות או עדכונים נכשלים. כל הנתונים מחוטאים בצד הלקוח לפני השידור, והמערכת שקופה לחלוטין עם נקודת קצה סטטיסטיקה ציבורית.

## מה נשלח

| אירוע | מתי | TTL |
|-------|------|-----|
| `install` | פעם אחת לכל מכונה (התקנה ראשונה או הרצה ראשונה) | קבוע |
| `heartbeat` | פעם ביום | 90 יום |
| `doctor` | בכל הרצת דוקטור (אם טלמטריה מופעלת) | 90 יום |
| `doctor/submit` | כשבדיקה נכשלת והפרטיות `full` | 30 יום |

## Payload

ה-payload הבסיסי של ping:

```json
{
  "id": "a1b2c3d4e5f6a7b8",
  "v": "2.2.0",
  "engine": "python",
  "tier": "full",
  "os": "linux",
  "event": "install"
}
```

ה-`id` הוא מחרוזת hex בת 16 תווים המיוצרת פעם אחת לכל מכונה באמצעות `secrets.token_hex(8)`. הוא מאוחסן ב-`~/.claude/.statusline-telemetry-id`. לא נשלחים נתוני שיחות, תוכן קבצים, מפתחות API, או זהות אמיתית.

עבור אירועי `doctor/submit` עם פרטיות `full`, דוח דיאגנוסטי מחוטא נכלל. החיטוי מחליף:

- נתיבי ספריית home ב-`~/`
- שמות משתמש ב-`<user>`
- hostnames ב-`<host>`

## רמות פרטיות

מוגדרות ב-`~/.claude/statusline-config.json`:

| רמה | קונפיג | מה נשלח |
|-------|--------|-------------|
| Full (ברירת מחדל) | `{ "tier": "full" }` | סיכום + דוח מחוטא בעת כשל |
| Minimal | `{ "diagnostics": "minimal" }` | סיכום בלבד |
| Off | `{ "telemetry": false }` | כלום, לעולם לא |

משתנה הסביבה `STATUSLINE_DISABLE_TELEMETRY=1` גם מנטרל את כל הטלמטריה, כולל דוחות דוקטור.

## נקודת קצה

כל ה-pings הולכים ל-`https://statusline-telemetry.nadavf.workers.dev/ping`. ה-Cloudflare Worker מאחסן נתונים ב-KV עם פקיעת TTL אוטומטית. ראו [worker טלמטריה](../apps/telemetry-worker.md) למימוש בצד השרת.

## שקיפות

סטטיסטיקות חיות זמינות לצפייה ציבורית ב-`https://statusline-telemetry.nadavf.workers.dev/stats`. נקודת קצה זו מציגה ספירות מצטברות (התקנות, DAU, פילוח engine/tier/OS) ללא נתוני מכונה בודדים.

## יצירת מזהה טלמטריה

מפל יצירת המזהה ב-`engines/bash-engine.sh` מנסה את המקורות הבאים לפי סדר:

1. `python3 -c "import secrets; print(secrets.token_hex(8))"`
2. `python -c "import secrets; print(secrets.token_hex(8))"`
3. `openssl rand -hex 8`
4. `od -An -N8 -tx1 /dev/urandom`

המזהה מאומת כמחרוזת hex בת 16 תווים, נכתב ל-`~/.claude/.statusline-telemetry-id` עם מצב 600, ובשימוש חוזר בהרצות הבאות.

## קובצי מקור מרכזיים

| קובץ | מטרה |
|------|---------|
| `engines/bash-engine.sh` | יצירת מזהה טלמטריה ו-ping של heartbeat |
| `engines/python-engine.py` | Ping טלמטריה במנוע Python |
| `engines/node-engine.js` | Ping טלמטריה במנוע Node.js |
| `doctor/doctor.sh` | שליחת טלמטריה של דוקטור |
| `install.sh` | Ping של אירוע התקנה |
| `worker/worker.js` | Cloudflare Worker שמקבל pings |
| `tests/test_install_ping.py` | בדיקות ping התקנה |
| `tests/test_doctor_telemetry.py` | בדיקות טלמטריה של דוקטור |

## עמודים קשורים

- [דיאגנוסטיקת דוקטור](doctor.md) — מה מפעיל טלמטריה של דוקטור
- [Worker טלמטריה](../apps/telemetry-worker.md) — מימוש נקודת קצה בצד השרת
- [אבטחה](../security.md) — חיטוי נתונים ומודל פרטיות
