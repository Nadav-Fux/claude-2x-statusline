# תהליך פיתוח

## Branch וקוד

1. בצעו fork ל-repository וצרו feature branch מ-`main`
2. בצעו שינויים בהתאם ל[תבניות ומוסכמות](patterns-and-conventions.md)
3. ודאו זהות בין שלושה מנועים: אם שיניתם את `engines/python-engine.py`, עדכנו גם את `engines/node-engine.js`
4. הוסיפו או עדכנו בדיקות לכל לוגיקה ששונתה

## בדיקה לפני הגשה

```bash
# בדיקות Python (חייבות לעבור כולן)
pip install pytest tzdata
python -m pytest tests/ -v

# בדיקת זמן ריצה של Node.js
node --test tests/node-runtime.test.mjs

# בדיקת Worker
node --test worker/worker.test.mjs

# בדיקת תחביר של סקריפטי shell
bash -n install.sh
bash -n doctor/doctor.sh
bash -n statusline.sh
```

## תהליך PR

1. Push את ה-branch שלכם ל-fork
2. פתחו pull request מול `main`
3. תארו מה השתנה ולמה
4. הפנו ל-issues קשורים
5. המתחזק סוקר וממזג

## ניהול גרסאות

הגרסה מופיעה בשלושה קבצים שחייבים להישאר מסונכרנים:

| קובץ | שדה |
|------|-------|
| `package.json` | `"version"` |
| `plugin.json` | `"version"` |
| `vscode/package.json` | `"version"` |

יש לעדכן גם את `release.latest_version` ב-`schedule.json` של schedule.
