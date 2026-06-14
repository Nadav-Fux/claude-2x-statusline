# פריסה

## התקנת הפלאגין

הפלאגין מופץ על ידי שיבוט ה-repository והרצת ה-installer. אין שלב build. ראו [תחילת העבודה](overview/getting-started.md) להוראות התקנה.

ה-installer מטפל ב:

1. העתקת קבצים ל-`~/.claude/cc-2x-statusline/`
2. כתיבת `~/.claude/statusline-config.json`
3. חיבור סטנזת `statusLine` ב-`~/.claude/settings.json`
4. רישום hooks של ה-narrator ב-`settings.json`
5. שליפת ה-schedule ההתחלתי
6. התקנת תוסף VS Code (אם זוהה עורך נתמך)
7. שליחת פינג טלמטריית התקנה

## עדכונים

עדכונים נמשכים באמצעות `git pull` בתיקיית ההתקנה. הפקודה `/statusline-update` או הסקריפט `update.sh` מאוטמטים זאת. השדה `release.latest_version` ב-schedule המרוחק מניע הודעות עדכון המוצגות בשורת הסטטוס.

עדכוני schedule בלבד (שעות שיא, באנרים, feature flags) מתבצעים אוטומטית כל 3 שעות ללא כל עדכון קוד. ראו [שעות שיא ו-schedule](features/peak-hours-schedule.md).

## פריסת worker הטלמטריה

ה-Cloudflare Worker נפרס בנפרד:

```bash
cd worker
wrangler deploy
wrangler kv key put --binding=TELEMETRY _auth_token "secret"
```

ראו [worker הטלמטריה](apps/telemetry-worker.md) לפרטים.

## אריזת תוסף VS Code

```bash
cd vscode
npm run package    # מייצר claude-statusline-0.2.0.vsix
```

הקובץ `.vsix` יכול להיות מותקן באמצעות `code --install-extension claude-statusline-0.2.0.vsix` או להתפרסם ב-VS Code Marketplace.

## הסרת התקנה

יש להריץ את `~/.claude/cc-2x-statusline/uninstall.sh` כדי להסיר את כל העקבות. ראו [צינור ה-installer](systems/installer.md) למידע על מה שעובר ניקוי.

## הערות ספציפיות לפלטפורמה

| פלטפורמה | Installer | הערות |
|----------|-----------|-------|
| macOS | `install.sh` | Python מ-Homebrew או מהמערכת |
| Linux | `install.sh` | Python ממנהל החבילות של ההפצה |
| Windows | `install.ps1` | דוחה stubs של Store, מזהה התקנות ניידות |
