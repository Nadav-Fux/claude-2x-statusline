# כלים

## מערכת build

לפרויקט אין שלב קומפילציה עבור ה-plugin הראשי. קבצי Python, JavaScript ו-Bash רצים ישירות. שלב ה-build היחיד הוא קומפילציית TypeScript של הרחבת VS Code.

### הרחבת VS Code

```bash
cd vscode
npm install
npm run compile    # TypeScript → out/extension.js
npm run package    # build של .vsix באמצעות vsce
```

### Telemetry worker

```bash
cd worker
npm install
wrangler deploy    # פריסה ל-Cloudflare
```

## Linting ואיכות

- **סקריפטי Shell**: השתמשו ב-`bash -n <file>` לבדיקת תחביר. אין linter רשמי מוגדר.
- **Python**: אין linter רשמי מוגדר. עקבו אחר הסגנון הקיים (הזחה של 4 רווחים, type hints, docstrings).
- **JavaScript/TypeScript**: מהדר TypeScript (`tsc`) להרחבת VS Code. אין ESLint מוגדר.
- **Markdown**: אין linter רשמי.

## סקריפטי package

מ-`package.json`:

```json
{
  "scripts": {
    "test:runtime": "node --test tests/node-runtime.test.mjs",
    "test:worker": "node --test worker/worker.test.mjs"
  }
}
```

## CI/CD

אין pipeline של CI/CD מוגדר ב-repository. בדיקות מורצות ידנית לפני releases. ה-telemetry worker מתפרס ידנית באמצעות `wrangler deploy`.

## מעקב אחר קבצים (פיתוח הרחבת VS Code)

```bash
cd vscode
npm run watch    # tsc -watch לקומפילציה מחדש חיה
```

לחצו F5 ב-VS Code כדי להפעיל Extension Development Host לבדיקות.
