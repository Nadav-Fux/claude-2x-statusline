# תצוגה מקדימה חיה

## מטרה

Web app חד-עמודי בכתובת [statusline.nvision.me](https://statusline.nvision.me) שמאפשר למשתמשים לראות תצוגה מקדימה של שלושת tiers של ה-statusline ולבחור איזה מהם הם רוצים לפני ההתקנה.

## יישום

`public/index.html` הוא קובץ HTML עצמאי (21KB) עם CSS ו-JavaScript מוטמעים. הוא מציג:

- תצוגות מקדימות חזותיות של tiers minimal, standard ו-full באמצעות אותם נכסי SVG מ-`assets/`
- טבלת השוואת tiers
- הוראות התקנה מ-copy-paste עבור ה-tier הנבחר
- קישורים ל-repository ב-GitHub

לדף אין תלות ב-backend. הוא מוגש כקובץ static.

## קבצי קוד מפתח

| קובץ | מטרה |
|------|---------|
| `public/index.html` | דף תצוגה מקדימה חיה ובורר tier |
| `assets/tier-minimal.svg` | תמונת תצוגה מקדימה של tier minimal |
| `assets/tier-standard.svg` | תמונת תצוגה מקדימה של tier standard |
| `assets/tier-full.svg` | תמונת תצוגה מקדימה של tier full |
