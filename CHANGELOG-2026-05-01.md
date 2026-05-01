# CHANGELOG — תיקונים ושיפורים 2026-05-01

## סיכום שינויים עיקריים

- שיחזור ותיקון route `/failures` ב־worker, כולל אגרגציה של כשלי install/update/doctor.
- הרחבת קבלת קוד אבחון בן 8 תווים (hex) ב־worker וב־doctor, כך ש־doctor diagnostic code תמיד מתקבל.
- תיקון `doctor.sh` לזיהוי narrator hooks ב־Windows/Git Bash: קריאת `settings.json` דרך stdin, תמיכה במבנה hooks המקונן של Claude Code, ונרמול נתיבי `/c/...` כדי למנוע false positive של "Narrator hooks not wired".
- הוספת נרמול schedule ב־engines (Python/Node): JSON לא תקין או null לא מפיל את הסטטוסליין.
- תיקון quoting של נתיבי פקודות ב־install.sh (shell_quote) — מונע תקלות בנתיבים עם רווחים.
- יישור metadata ב־README לגרסה 2.2.0 ולרישיון PolyForm Noncommercial 1.0.0.
- הוספת בדיקות רגרסיה ל־pytest (schedule shape) ועדכון worker tests.
- ניקוי קובץ probe זמני שנוצר במהלך בדיקות טרמינל.

## בדיקות ואימות

- pytest: 138 passed, 10 skipped (skips בגלל bash לא ב־PATH)
- npm run test:runtime: 4 passed
- npm run test:worker: 4 passed
- bash -n install.sh ו־doctor/doctor.sh: תקין
- VS Code Problems: אין שגיאות
- git diff --check: אין שגיאות, מלבד אזהרת line endings רגילה

## הערות

- המסמך הזה מסכם את סדרת התיקונים שבוצעה ב־2026-05-01/02, כולל follow-up ל־`doctor.sh` עבור Windows/Git Bash.
- התיעוד המפורט של תיקון ה־doctor נמצא גם תחת `docs/changelog/2026-05-02-doctor-narrator-hooks-windows.md`.
