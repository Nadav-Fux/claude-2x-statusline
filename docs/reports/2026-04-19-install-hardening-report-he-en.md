# claude-2x-statusline Installation Hardening Report

Date: 2026-04-19
Repository: claude-2x-statusline
Original plan reference: `C:\Users\Nadav\.claude\plans\harmonic-stargazing-harbor.md`

---

## עברית

### תקציר מנהלים

המטרה המקורית הייתה לאחד את מסלול ההתקנה, לשפר את מסלול העדכון, להבטיח שהמערכת תעבוד גם למשתמש חדש וגם למשתמש קיים, גם על Windows וגם על macOS/Linux, וגם במצבים שבהם אין Python זמין. בפועל, העבודה לא הסתכמה ב"לממש תוכנית" אלא דרשה שורה ארוכה של תיקונים ברמת ה-runtime, PowerShell 5.1, wiring של JSON, Doctor, telemetry, packaging, וזרימת post-install אמינה.

בסיום העבודה, המוצר נמצא במצב יציב משמעותית מהמצב ההתחלתי:

- `install.sh` ו-`install.ps1` מספקים התקנה מלאה הרבה יותר, כולל doctor, telemetry, update path, commands, hooks, schedule ו-editor extension.
- משתמשים ותיקים מקבלים מסלול עדכון ברור ומבוסס `update.sh` / `update.ps1` ולא נדרשים לנחש שצריך `git pull` והרצה מחודשת ידנית.
- wiring של `settings.json` ו-`statusline-config.json` כבר לא תלוי ב-Python בלבד, אלא משתמש בשכבת JSON משותפת שנבנתה במיוחד עבור bash ו-PowerShell.
- כשלי התקנה/עדכון נאספים בצורה מסודרת ב-worker, כולל `fail_index` ו-`/failures` לדיווח מרוכז למתחזק.
- שתי הנקודות האחרונות שנשארו פתוחות הושלמו: בדיקות אוטומטיות ל-`/failures`, וכן stale-version surfacing + post-install onboarding flow.

### שתי הנקודות האחרונות שהושלמו בסוף

#### 1. בדיקות אוטומטיות ל-`/failures`

נוספו בדיקות worker אמיתיות ולא רק תיעוד או בדיקות ידניות:

- `worker/worker.test.mjs`
- `worker/package.json`
- script חדש ב-`package.json`: `npm run test:worker`

מה הבדיקות מכסות:

- גישה פתוחה ל-`/failures` כאשר `_auth_token` לא מוגדר
- חסימת גישה עם `401` כאשר מוגדר token והבקשה לא מאומתת
- aggregation אמיתי של `install_result`, `update`, ו-`doctor`
- rollup של `fail_index` לאורך מספר ימים
- ספירה לפי מערכת הפעלה (`by_os`)
- נרמול `failed_ids` גם ממחרוזת וגם ממערך, כולל dedupe

למה זה חשוב:

עד עכשיו המסלול הזה היה קיים לוגית אבל לא היה נעול על ידי בדיקות. המשמעות הייתה שכל שינוי קטן ב-worker היה עלול לשבור את reporting של כשלי התקנה בלי שהיינו יודעים. מעכשיו, יש כיסוי אוטומטי למסלול החדש המרכזי הזה.

#### 2. stale-version surfacing + post-install onboarding flow

הושלמה הזרימה שחסרה למשתמש אחרי התקנה מוצלחת:

##### stale-version surfacing

נוספו metadata של release בתוך `schedule.json`, וה-engine-ים מציגים badge כאשר הגרסה המקומית ישנה:

- `schedule.json` כולל עכשיו `release.latest_version`, `release.minimum_version`, `release.command`
- `engines/python-engine.py`
- `engines/node-engine.js`
- `engines/bash-engine.sh`
- `statusline.ps1`

בנוסף:

- `install.sh` מעתיק עכשיו גם `package.json` לתיקיית ההתקנה כדי שלמנועים תהיה גישה לגרסה המקומית

התוצאה:

- משתמש ותיק שנשאר מאחור כבר לא צריך לגלות במקרה שיש פער גרסאות
- ההתראה מגיעה ישירות לשורת הסטטוס עצמה, כלומר למשטח הכי גלוי במוצר

##### post-install onboarding flow

נוספה נקודת כניסה ברורה למשתמשים אחרי install/update:

- command חדש: `commands/statusline-onboarding.md`
- skill חדש: `skills/onboarding/SKILL.md`
- הודעת הסיום של `install.sh` ו-`install.ps1` מפנה כעת ל-`/statusline-onboarding`

למה זה עדיף:

- אין תלות ב-auto-run לא מתועד של plugin skill
- יש מסלול מפורש, discoverable, ואפשר להסביר אותו גם ב-docs וגם מתוך ה-installer
- משתמש חדש לא נשאר עם שורת "Restart Claude Code" בלבד, אלא מקבל next step ברור

### מה בוצע בפועל לאורך כל העבודה

להלן התמונה המלאה של מה שבוצע ברמת המוצר:

#### שכבת התקנה ועדכון

- `install.sh` נכתב מחדש למסלול מלא יותר:
  - `--tier`, `--update`, `--quiet`
  - זיהוי same-dir / in-place install
  - טעינת config קיים בעת update
  - doctor בסוף ההתקנה
  - telemetry נפרד ל-`install` ול-`install_result`
  - הפצת files, commands, skills, hooks, narrator
  - packaging יציב יותר ל-extension באמצעות binary מקומי של `vsce`

- `install.ps1` שוכתב מ-stub למסלול Windows אמיתי:
  - clone / refresh / zip bootstrap
  - בחירת tier
  - runtime detection ל-Git Bash / Python / Node
  - wiring של `statusLine`
  - wiring של narrator hooks כאשר Git Bash זמין
  - diagnostics בסוף
  - telemetry ל-install/update
  - fallback ברור כאשר narrator לא זמין

- נוספו updaters:
  - `update.sh`
  - `update.ps1`

#### שכבת JSON / settings wiring

- נוספה שכבת helper משותפת:
  - `lib/wire-json.sh`
  - `lib/Wire-Json.ps1`

השכבה הזו מאפשרת merge/query ל-JSON גם כאשר אין Python, תוך שמירה על Windows PowerShell 5.1 ותאימות רחבה יותר.

#### telemetry / diagnostics

- `worker/worker.js` הורחב לקבלת `install_result`, `update`, ו-`doctor`
- נוסף endpoint של `GET /failures`
- נוסף `fail_index` יומי ו-aggregation לפי OS
- `doctor/doctor.sh` הורחב כדי לזהות narrator hooks בצורה אמינה יותר על Windows

#### UX / discoverability

- `commands/statusline-init.md`
- `commands/statusline-update.md`
- `commands/statusline-onboarding.md`
- `skills/onboarding/SKILL.md`
- עדכוני README ו-`tests/README.md`

#### runtime/version visibility

- stale version notice ברמת ה-engine
- release metadata ב-`schedule.json`
- `package.json` מועתק למסלול ההתקנה הידני

### כל הכשלים והבעיות שנתקלתי בהם, ומה נעשה כדי לפתור אותם

זו הרשימה המרוכזת של הבעיות המהותיות שנחשפו במהלך העבודה, לא רק בסוף:

#### 1. `install.sh` לא היה מתאים למסלולי update ו-migration

הבעיה:

- הסקריפט היה אינטראקטיבי מדי
- לא שמר flow מסודר ל-existing installs
- לא היה ברור למשתמש איך לעדכן

מה נעשה:

- נוספו `--tier`, `--update`, `--quiet`
- נוספה לוגיקה של טעינת config קיים
- נוספו `update.sh` ו-`update.ps1`

#### 2. wiring של JSON היה תלוי ב-Python

הבעיה:

- משתמשים בלי Python היו מקבלים התקנה חלקית או שקטה מדי
- `settings.json` ו-hooks לא תמיד עודכנו

מה נעשה:

- נבנתה שכבת JSON נפרדת ל-bash ול-PowerShell
- נוספה התאמה ל-PowerShell 5.1 ולא רק ל-PowerShell 7

#### 3. `install.ps1` היה stub ולא מתקין אמיתי

הבעיה:

- לא היה parity מול `install.sh`
- לא הותקנו hooks, skills, doctor, config, slash commands, update flow

מה נעשה:

- שכתוב כמעט מלא של `install.ps1`

#### 4. בעיות PowerShell 5.1

הבעיה:

- חלק מהנחות היסוד המודרניות לא עבדו ב-5.1
- `ConvertFrom-Json -AsHashtable` לא זמין
- handling של stderr / BOM / path quoting היה רגיש

מה נעשה:

- helper מותאם ל-5.1
- כתיבה ב-UTF-8 ללא BOM
- המרות path מסודרות ל-Git Bash
- טיפול שמרני יותר ב-stderr וב-error behavior

#### 5. narrator hook detection נתן false negatives

הבעיה:

- doctor לא תמיד זיהה hook תקין על Windows כי הייצוג ב-`settings.json` השתנה בין מחרוזות, dict-ים ו-wrapped commands

מה נעשה:

- `doctor/doctor.sh` הורחב לזהות full path, basename, dict/list/string, ו-command wrapping

#### 6. packaging של extension ב-Windows היה שביר

הבעיה:

- המסלול שהתבסס על `npx` היה לא יציב תחת PowerShell
- לעיתים התקבל כשל מדומה גם כאשר package נבנה בפועל

מה נעשה:

- מעבר ל-`node_modules/.bin/vsce` / `vsce.cmd` מקומי
- מחיקה של VSIX ישן לפני build
- בדיקה מפורשת שהקובץ באמת נוצר
- PowerShell הותאם כדי לא לפרש stderr אינפורמטיבי כ-exception

#### 7. PowerShell יצר artifact לא רצוי ב-working tree

הבעיה:

- `Microsoft/Windows/PowerShell/ModuleAnalysisCache` הופיע ב-git status

מה נעשה:

- artifact נוקה ידנית ולא נשאר כחלק מהדיפ הסופי

#### 8. הטרמינל חזר ל-`>>` continuation prompt

הבעיה:

- לקראת סוף העבודה shell אחד היה במצב continuation, מה שהפך חלק מהריצות לפחות אמינות

מה נעשה:

- הרצות האימות הקריטיות בוצעו במסלול מבודד יותר
- worker tests הורצו ב-terminal session נפרד
- pytest הורץ דרך execution environment ישיר

#### 9. `pytest` נכשל בתחילה בגלל `tzdata` חסר

הבעיה:

- בדיקות DST ב-Windows נכשלו, אבל זו לא הייתה regression מהקוד החדש אלא חוסר תלות בסביבת העבודה

מה נעשה:

- הותקן `tzdata` לסביבת ה-venv
- לאחר מכן `pytest` עבר בהצלחה

### השוואה לתוכנית המקורית

### מה היה חזק בתוכנית המקורית

התוכנית המקורית הייתה חזקה מאוד בשלב האבחון. היא זיהתה נכון את רוב הבעיות המבניות:

- אין מסלול update ברור למשתמשים ותיקים
- Windows PowerShell נשאר מאחור
- plugin-only install לא מספיק ל-`statusLine`
- יש צורך ב-doctor + telemetry structured בסוף install/update
- נדרשת שכבת JSON portable

כלומר, ברמת ה"מה שבור ולמה" התוכנית הייתה טובה מאוד.

### מה היה בעייתי או מסוכן בתוכנית המקורית

עם זאת, היו בתוכנית כמה נקודות שהיו צריכות תיקון או התאמה לפני מימוש:

| נקודה בתוכנית                                      | למה זה היה בעייתי                               | מה יושם בפועל                                               |
| -------------------------------------------------- | ----------------------------------------------- | ----------------------------------------------------------- |
| הבטחה מרומזת ל-JSON merge בטוח גם בלי parser אמיתי | מסוכן על קבצי JSON קיימים                       | נבנתה שכבת parser-backed helpers, עם fallbacks ברורים       |
| הישענות על `ConvertFrom-Json -AsHashtable`         | לא עובד ב-PowerShell 5.1                        | נבנה merge רקורסיבי ידני ב-`Wire-Json.ps1`                  |
| רעיון של auto-run ל-post-install skill             | אין guarantee שה-plugin יריץ skill כזה אוטומטית | נבחר flow מפורש: `/statusline-onboarding` + installer hints |
| stale-version hint דרך wrapper/helper חיצוני       | פחות ישיר ופחות runtime-agnostic                | ההתראה הוכנסה לתוך ה-engine banner path                     |
| תכנון שלא שיקלל כשלי packaging של `npx`            | ב-Windows זה היה source of flakiness            | הוחלף ל-local `vsce` binary                                 |
| הסתמכות חלקית על doctor event shape                | ערבוב אחריות בין installer ל-doctor             | installer שולח payloadים נפרדים ומפורשים                    |

### מה נעשה אחרת בפועל ולמה זה עדיף

#### 1. onboarding מפורש במקום auto-run לא אמין

בתוכנית היה כיוון ל-skill post-install אוטומטי. בפועל בחרתי ב:

- `commands/statusline-onboarding.md`
- `skills/onboarding/SKILL.md`
- הפניה ברורה מתוך שני ה-installers

למה זה עדיף:

- deterministic
- discoverable
- לא תלוי בהתנהגות plugin לא מתועדת
- קל יותר לבדוק ולתעד

#### 2. stale-version notice בתוך ה-engine, לא רק helper חיצוני

בתוכנית הופיע רעיון של helper/cached behind-check. בפועל ההתראה שולבה במסלול ה-render עצמו דרך `schedule.json` + `package.json`.

למה זה עדיף:

- אין fetch נוסף בתוך ה-render path
- אין תלות ב-git בלבד
- זה עובד גם ב-install non-git
- ההתראה מופיעה במקום שהמשתמש באמת רואה

#### 3. local `vsce` במקום `npx`

הנקודה הזו לא הייתה מפורטת מספיק בתוכנית כי הבעיה התגלתה תוך כדי מימוש.

למה זה עדיף:

- deterministic יותר
- לא תלוי ב-package resolution של `npx`
- יציב יותר ב-PowerShell

#### 4. סגירה מלאה של `worker` עם בדיקות

התוכנית דיברה על worker extensions, אבל לא כיסתה עד הסוף את שלב הבדיקות למסלול החדש. בפועל הוספתי בדיקות אוטומטיות מלאות ל-`/failures`.

למה זה עדיף:

- פחות regression risk
- מאפשר שינוי עתידי ב-worker בלי לשבור telemetry בשקט

### מה נעשה בסוף ממש, ברמת הסגירה האחרונה

ברמת ה"finish line" של המשימה, השלמתי את הסגירה הבאה:

1. הוספתי worker tests אמיתיים ל-`/failures`.
2. הוספתי stale-version badges לכל מנועי ה-runtime הרלוונטיים.
3. הוספתי onboarding flow מפורש אחרי install/update.
4. עדכנתי את ה-docs כך שהפיצ'רים החדשים יהיו discoverable.
5. הרצתי validation בפועל עד למצב ירוק.

### ולידציה סופית שבוצעה

בוצעו אימותים ממשיים, לא רק קריאה סטטית של הקוד:

- `npm run test:worker`
  - 3 tests passed

- `python -m pytest tests -v`
  - 106 passed
  - 1 skipped
  - warning אחד על `pytest.mark.flaky`

- `get_errors`
  - לא נמצאו שגיאות בקבצים המרכזיים ששונו

- במהלך האימות הותקן `tzdata` ל-venv כדי להשלים את בדיקות ה-DST על Windows

### מצב סופי

המצב הסופי טוב מהתוכנית המקורית בשני מובנים:

1. לא רק שהיעדים העיקריים יושמו, אלא גם נפתרו בעיות מימוש אמיתיות שהתוכנית לא יכלה לחזות מראש, בעיקר סביב PowerShell, packaging, BOM, path conversion ו-tooling behavior.
2. שתי הנקודות האחרונות שהיו חסרות באמת נסגרו בצורה מוצרית: יש כעת גם בדיקות ל-worker וגם מסלול אמיתי למשתמש אחרי install, כולל discoverability של update.

המסקנה שלי היא שהתוצאה הסופית עדיפה על התוכנית המקורית לא מפני שהתוכנית הייתה חלשה, אלא מפני שהיא הייתה נקודת פתיחה טובה שנדרשה לעבור hardening מול המציאות של Windows, PowerShell 5.1, Git Bash, ו-user flows אמיתיים.

---

## English

### Executive summary

The original goal was to unify installation, harden updates, support both new and existing users, work on Windows and macOS/Linux, and keep the product usable even when Python is unavailable. In practice, this required much more than simply “executing the plan”: it required runtime hardening, PowerShell 5.1 compatibility work, JSON wiring changes, doctor/reporting fixes, telemetry extensions, packaging stabilization, and a deterministic post-install path.

By the end of the work, the repository is in a materially better state:

- `install.sh` and `install.ps1` now provide a much fuller install/update flow.
- existing users have a real upgrade path through `update.sh` / `update.ps1`
- JSON wiring no longer assumes Python-only environments
- install/update failures are aggregated in the telemetry worker and exposed through `/failures`
- the two remaining unfinished items were completed: automated tests for `/failures`, and stale-version surfacing plus a post-install onboarding flow

### The two remaining items completed at the end

#### 1. Automated tests for `/failures`

Real worker tests were added, not just documentation or manual validation:

- `worker/worker.test.mjs`
- `worker/package.json`
- new `package.json` script: `npm run test:worker`

What these tests cover:

- open access to `/failures` when `_auth_token` is not configured
- `401` behavior when auth is required and the request is not authorized
- aggregation across `install_result`, `update`, and `doctor`
- multi-day `fail_index` rollups
- per-OS aggregation in `by_os`
- normalization and deduplication of `failed_ids` from both strings and arrays

Why this matters:

Before this, the feature existed logically but was not locked down by tests. A small worker refactor could have broken install-failure reporting silently. That risk is now much lower.

#### 2. Stale-version surfacing and post-install onboarding flow

The missing user-facing completion path after a successful install was added.

##### Stale-version surfacing

Release metadata was added to `schedule.json`, and the runtime engines now show a badge when the local install is behind:

- `schedule.json` now includes `release.latest_version`, `release.minimum_version`, and `release.command`
- badge support was added to:
  - `engines/python-engine.py`
  - `engines/node-engine.js`
  - `engines/bash-engine.sh`
  - `statusline.ps1`
- `install.sh` now copies `package.json` into the installed directory so engines can read the local version

Result:

- older installs can now discover drift directly from the statusline
- the update prompt appears in the most visible surface of the product

##### Post-install onboarding flow

A clear next-step path was added for users immediately after install/update:

- new command: `commands/statusline-onboarding.md`
- new skill: `skills/onboarding/SKILL.md`
- both installers now point users to `/statusline-onboarding`

Why this is better:

- it does not rely on undocumented plugin auto-run behavior
- it is explicit and discoverable
- it gives new users a deterministic “what do I do now?” path instead of only saying “restart Claude Code”

### What was implemented overall

#### Installation and update layer

- `install.sh` was rewritten/hardened with:
  - `--tier`, `--update`, `--quiet`
  - same-dir / in-place detection
  - reuse of existing config during update
  - mandatory doctor run at the end
  - separate `install` and `install_result` telemetry
  - packaging stabilization for the editor extension using local `vsce`

- `install.ps1` was rewritten from a stub into a real Windows installer:
  - clone / refresh / zip bootstrap
  - tier selection
  - runtime detection for Git Bash / Python / Node
  - `statusLine` wiring
  - narrator hook wiring when Git Bash is available
  - diagnostics and telemetry at the end

- new updaters were added:
  - `update.sh`
  - `update.ps1`

#### JSON/settings wiring layer

- shared JSON helper layer added:
  - `lib/wire-json.sh`
  - `lib/Wire-Json.ps1`

This removed the Python-only assumption from settings/config mutation and kept Windows PowerShell 5.1 support intact.

#### Telemetry and diagnostics

- `worker/worker.js` was extended for `install_result`, `update`, and `doctor`
- `GET /failures` was added
- daily `fail_index` rollups and per-OS aggregation were added
- `doctor/doctor.sh` was hardened to detect narrator hooks reliably on Windows

#### UX and discoverability

- `commands/statusline-init.md`
- `commands/statusline-update.md`
- `commands/statusline-onboarding.md`
- `skills/onboarding/SKILL.md`
- README and `tests/README.md` updates

#### Runtime/version visibility

- stale-version notice integrated into the engine banner path
- release metadata added to `schedule.json`
- `package.json` copied into manual install targets

### Failures and issues encountered, and how they were resolved

These are the important implementation issues encountered during the work, not just the final-day items.

#### 1. `install.sh` was not suitable for update/migration flows

Problem:

- too interactive
- weak handling of existing installs
- no obvious upgrade path

Fix:

- added `--tier`, `--update`, `--quiet`
- added config reuse logic
- added `update.sh` / `update.ps1`

#### 2. JSON wiring depended on Python

Problem:

- users without Python could get a partial or degraded install
- `settings.json` and hooks were not guaranteed to be wired

Fix:

- added shared JSON helper layer for bash and PowerShell
- explicitly supported PowerShell 5.1 instead of assuming newer features

#### 3. `install.ps1` was only a v1 stub

Problem:

- no real parity with `install.sh`
- missing hooks, config, doctor, slash commands, telemetry, update flow

Fix:

- near-complete rewrite of `install.ps1`

#### 4. PowerShell 5.1 constraints

Problem:

- several modern assumptions did not hold in 5.1
- `ConvertFrom-Json -AsHashtable` is unavailable
- BOM/stderr/path quoting behavior was fragile

Fix:

- built a dedicated 5.1-safe JSON helper
- forced UTF-8 without BOM
- fixed Bash/Windows path conversion
- used more conservative error handling

#### 5. Narrator hook detection produced false negatives

Problem:

- doctor did not always recognize valid hook configurations on Windows because settings could store commands in different shapes

Fix:

- `doctor/doctor.sh` now checks full paths, basenames, string/dict/list forms, and wrapped command strings

#### 6. VS Code extension packaging on Windows was unstable

Problem:

- the `npx` packaging path was flaky under PowerShell
- in some cases it reported failure even when output existed

Fix:

- switched to local `vsce` binaries from `node_modules`
- removed stale VSIX before packaging
- checked explicitly that the new VSIX file exists
- prevented informational stderr output from becoming false exceptions

#### 7. PowerShell generated a worktree artifact

Problem:

- `Microsoft/Windows/PowerShell/ModuleAnalysisCache` appeared in the git status

Fix:

- cleaned it from the working tree so it does not remain in the final diff

#### 8. PowerShell terminal continuation prompt (`>>`)

Problem:

- one terminal returned to a continuation state late in the session, making some commands unreliable

Fix:

- used more isolated validation paths
- ran worker tests in a separate terminal session
- ran pytest through the configured Python execution environment

#### 9. `pytest` initially failed because `tzdata` was missing

Problem:

- DST tests failed on Windows, not because of a regression, but because the environment lacked `tzdata`

Fix:

- installed `tzdata` into the repo virtual environment
- reran the full suite successfully

### Comparison to the original plan

### What the original plan got right

The original plan was strong at the diagnosis layer. It correctly identified the main structural problems:

- no visible update path for existing users
- Windows PowerShell lagging behind
- plugin-only install not being enough to wire `statusLine`
- need for structured doctor + telemetry at the end of install/update
- need for a portable JSON wiring layer

In other words: the plan was good at identifying what was broken and why.

### What was risky or problematic in the original plan

There were still several places where the plan needed refinement before safe implementation:

| Plan item                                               | Why it was risky                      | What was implemented instead                        |
| ------------------------------------------------------- | ------------------------------------- | --------------------------------------------------- |
| implied safe JSON merge without a real parser           | unsafe for existing JSON files        | parser-backed helper layer with explicit fallbacks  |
| `ConvertFrom-Json -AsHashtable` style thinking          | not valid in PowerShell 5.1           | custom recursive merge in `Wire-Json.ps1`           |
| automatic post-install skill invocation                 | no guaranteed plugin auto-run path    | explicit `/statusline-onboarding` + installer hints |
| stale-version helper outside the engine path            | less direct and less runtime-agnostic | integrated badge inside engine banner rendering     |
| no anticipation of `npx`/PowerShell packaging flakiness | became a real Windows blocker         | switched to local `vsce` binaries                   |
| partial coupling between doctor and installer reporting | blurred responsibility                | installer sends its own explicit telemetry payloads |

### What was done differently in the final implementation, and why it is better

#### 1. Explicit onboarding instead of unreliable auto-run

The plan suggested an automatic post-install skill direction. The final implementation shipped:

- `commands/statusline-onboarding.md`
- `skills/onboarding/SKILL.md`
- explicit installer messaging

Why this is better:

- deterministic
- discoverable
- testable
- not dependent on undocumented plugin behavior

#### 2. Engine-level stale-version notice instead of only an external helper

The plan discussed a stale-version helper / cached behind check. The final implementation placed the notice directly in the runtime banner path using `schedule.json` release metadata and local `package.json` version detection.

Why this is better:

- no extra live fetch in the render path
- not git-only
- works for non-git installs too
- visible exactly where the user looks

#### 3. Local `vsce` instead of `npx`

This was discovered during implementation rather than fully anticipated in the plan.

Why this is better:

- more deterministic
- avoids package-resolution ambiguity
- more stable under PowerShell automation

#### 4. Worker extensions plus tests, not only worker extensions

The plan described the telemetry worker evolution, but did not fully close the loop on automated coverage for the new `/failures` flow.

Why this is better:

- lower regression risk
- future worker changes are safer

### What was completed at the very end

At the finish line, the following final closures were made:

1. Real worker tests were added for `/failures`.
2. Stale-version badges were added across the relevant runtime engines.
3. A deterministic onboarding flow was added after install/update.
4. Documentation was updated so the new paths are discoverable.
5. Validation was rerun until it was clean.

### Final validation performed

Real validation was executed, not just static reading:

- `npm run test:worker`
  - 3 tests passed

- `python -m pytest tests -v`
  - 106 passed
  - 1 skipped
  - 1 warning for `pytest.mark.flaky`

- `get_errors`
  - no editor/language-service errors on the core changed files

- `tzdata` was installed into the repo virtual environment to complete Windows DST test coverage

### Final state

The final state is better than the original plan in two important ways:

1. The plan’s main goals were implemented, but the implementation also solved real-world problems the plan could not fully anticipate ahead of time, especially around PowerShell, packaging, BOM handling, path conversion, and terminal/tooling behavior.
2. The two remaining unfinished product items were closed in a real, user-facing way: the worker reporting path now has automated coverage, and users now have both update visibility and a post-install next-step flow.

My conclusion is that the final implementation is better than the original plan not because the plan was weak, but because it was a strong starting point that still needed hardening against the reality of Windows, PowerShell 5.1, Git Bash, and actual user flows.
