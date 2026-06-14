# Shared libraries

## מטרה

ספריית `lib/` מכילה אבני בניין משותפות בין engines, narrator, installer ו-doctor. לכל ספרייה יש הטמעות מקבילות לפי הצורך.

## מצב מתגלגל

ring buffer של 60 דקות עבור קצב שריפה ומדדי מטמון. ראו [rolling metrics](../features/rolling-metrics.md) לפרטים מלאים.

| קובץ | שפה | פונקציות עיקריות |
|------|----------|---------------|
| `lib/rolling_state.py` | Python | `append_sample`, `rolling_rate`, `rolling_tokens_out`, `cache_delta` |
| `lib/rolling_state.js` | JavaScript | אותו API, הסבה ל-Node.js |

שניהם כותבים ל-`~/.claude/statusline-state.json` עם tmpfile אטומי + rename. קבועים: `MAX_AGE_SECS = 3600`, `MIN_SPAN_SECS = 180`, `MAX_PLAUSIBLE_RATE = 200.0`.

## זיהוי workflow

`lib/workflows.py` קורא מצב סשן ו-workflow של Claude Code כדי להציג פעילות subagent חיה בשורת המצב.

### רזולוציית ספריית סשן

`find_session_dir()` גוזר את ספריית הסשן של Claude Code מ-stdin של hook או ממצב הסשן. הוא מנסה:

1. `transcript_path` מ-stdin (קובץ ה-`.jsonl` הוא sibling של ספריית הסשן)
2. `session_id` + `cwd` מ-stdin (בונה `~/.claude/projects/<slug>/<sid>/`)
3. התאמת סשן לפי `cwd` ב-`~/.claude/sessions/*.json` (מעדיף מצב busy, `updatedAt` הכי טרי)

הפונקציה `project_slug()` משקפת את שמות ספריות ה-project-dir של Claude Code: כל תו שאינו אלפאנומרי הופך ל-`-`.

### זיהוי workflow חי

`detect_live_workflows()` סורק את `session_dir/subagents/workflows/wf_*/` עבור workflows בתהליך. לכל אחד, הוא סופר agents וסוכם context tokens על ידי קריאת בלוק ה-usage האחרון מכל קובץ `agent-*.jsonl`.

### אגרגציה של workflow שהושלם

`read_completed_workflows()` מאגד manifests של `session_dir/workflows/wf_*.json` עבור סך tokens, ספירת ריצות וספירת agents.

### קריאת שימוש ב-tokens

`read_agent_last_usage_tokens()` קורא את בלוק ה-`"usage"` האחרון מ-transcript מסוג JSONL. הוא קורא רק את 64KB האחרונים של הקובץ ליעילות, ומטפל בכתיבות אחרונות קטועות על ידי נפילה להתאמה הלפני-אחרונה.

## מניפולציית JSON

עוזרי merge/query חוצי-פלטפורמות המשמשים installers ו-doctor.

| קובץ | שפה | Backend |
|------|----------|---------|
| `lib/wire-json.sh` | Bash (מפנה ל-Python/Node/jq/PowerShell) | זיהוי אוטומטי |
| `lib/Wire-Json.ps1` | PowerShell | אובייקטי PS טבעיים |

`wire-json.sh` בוחר backend בשימוש הראשון:

1. Python (דרך `resolve_runtime python`)
2. Node.js (דרך `resolve_runtime node`)
3. `jq` אם זמין
4. PowerShell (`pwsh` או `powershell`)
5. `"none"` (פעולות הופכות ל-no-ops)

הוא מספק פונקציות למיזוג אובייקטי JSON, קבלת ערכים לפי נתיב, והגדרת ערכים לפי נתיב. ה-installer משתמש בו כדי לעדכן אטומית את `settings.json` עם הסטנזה של `statusLine`.

## קובצי מקור עיקריים

| קובץ | שורות | מטרה |
|------|-------|---------|
| `lib/rolling_state.py` | 157 | ring buffer ל-Python |
| `lib/rolling_state.js` | 121 | ring buffer ל-Node.js |
| `lib/workflows.py` | 193 | זיהוי סשן/workflow |
| `lib/wire-json.sh` | 365 | merge/query JSON חוצה-פלטפורמות |
| `lib/Wire-Json.ps1` | 213 | עוזרי JSON ל-PowerShell |
| `lib/resolve-runtime.sh` | 85 | resolver של runtime (ראו [runtime resolution](runtime-resolution.md)) |

## עמודים קשורים

- [Rolling metrics](../features/rolling-metrics.md) — כיצד מצב מתגלגל מזין תצוגת קצב שריפה
- [Runtime resolution](runtime-resolution.md) — כיצד wire-json בוחר את ה-backend שלו
- [Engines](engines.md) — כיצד engines צורכים את הספריות האלה
