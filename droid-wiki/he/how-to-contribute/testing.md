# בדיקות

## מסגרת בדיקות

בדיקות Python משתמשות ב-`pytest`. בדיקות Node.js משתמשות ב-runner המובנה `node --test`. אין צורך במסגרת בדיקות חיצונית עבור Node.js.

## הרצת בדיקות

```bash
# כל בדיקות Python
pip install pytest tzdata
python -m pytest tests/ -v

# בדיקת זמן ריצה של Node.js
npm run test:runtime
# או: node --test tests/node-runtime.test.mjs

# בדיקות Worker
npm run test:worker
# או: node --test worker/worker.test.mjs
```

## רשימת בדיקות

| קובץ בדיקה | תחום מיקוד | בדיקות |
|-----------|-----------|-------|
| `tests/test_peak_hours.py` | המרת אזורי זמן, DST, גלישה בין אזורי זמן | ~20 |
| `tests/test_narrator_scoring.py` | ניקוד 4 צירים, כל 15+ תבניות, dedup של חידושים | ~40 |
| `tests/test_narrator.py` | pipeline של narrator, שילוב Haiku, throttling | ~15 |
| `tests/test_narrator_memory.py` | התמדת זיכרון, רוטציית session, פינוי | ~12 |
| `tests/test_narrator_observations.py` | בניית תצפיות ממצב session | ~8 |
| `tests/test_narrator_rate_limits.py` | זיהוי סף מגבלת קצב | ~6 |
| `tests/test_rolling_state.py` | ring buffer, spike guards, חישוב קצב | ~15 |
| `tests/test_doctor.py` | בדיקות doctor | ~8 |
| `tests/test_doctor_telemetry.py` | קודים דיאגנוסטיים, שליחת טלמטריה | ~12 |
| `tests/test_install_ping.py` | payload של טלמטריית התקנה | ~10 |
| `tests/test_banners.py` | הצגת banners ותפוגה | ~10 |
| `tests/test_wire_json.py` | מיזוג/שאילתת JSON (backend של bash) | ~10 |
| `tests/test_wire_json_ps1.py` | מיזוג/שאילתת JSON (backend של PowerShell) | ~6 |
| `tests/test_workflows.py` | זיהוי ואגרגציה של workflows | ~10 |
| `tests/test_usage_credits.py` | מד קרדיט SDK | ~4 |
| `tests/test_option3_offloop.py` | התנהגות אפשרות offloop | ~8 |
| `tests/test_option6_workflow_context.py` | אפשרות הקשר workflow | ~6 |
| `tests/test_option7_auth.py` | אפשרות מצב auth | ~8 |
| `tests/node-runtime.test.mjs` | זהות מנוע Node.js | 4 |
| `tests/test_worker.py` | בדיקות endpoint של worker | ~8 |

## תבניות בדיקה

- **Fixtures** ב-`tests/fixtures/` מספקים נתוני session לדוגמה, קבצי transcript וקבצי config
- **`conftest.py`** מגדיר תשתית בדיקות כולל ספריות זמניות וקבצי state מדומים
- **דילוג** — בדיקות שדורשות bash מדלגות כש-bash אינו ב-PATH (נפוץ ב-Windows CI)
- **בדיקת contract דו-לשונית** — בדיקה מבנית אוכפת שלכל תבנית ניקוד יש גם שדה `text` וגם שדה `text_he`

## מה לבדוק בעת הוספת תכונות

- Segment חדש של statusline: הוסיפו בדיקה בקובץ הבדיקה הרלוונטי שמאמת פלט rendering
- תבנית narrator חדשה: הוסיפו בדיקות ניקוד, ודאו שבדיקת ה-contract הדו-לשונית עוברת
- לוגיקת rolling-state חדשה: הוסיפו בדיקות ב-`test_rolling_state.py`
- שינויי מנוע: ודאו שגם בדיקות Python וגם בדיקות Node.js עוברות
- שינויי endpoint של worker: הוסיפו בדיקות ב-`worker/worker.test.mjs`
