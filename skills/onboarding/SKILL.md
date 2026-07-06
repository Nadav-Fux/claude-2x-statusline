---
description: "Guide the user to choose which AI-CLI providers appear in the statusline cockpit (Claude + Codex/Antigravity/Copilot/GLM/Droid). Use after install/update, or when the user wants to add, remove, or re-check a provider."
argument-hint: ""
allowed-tools: ["Read", "AskUserQuestion", "Bash"]
---

# Statusline Onboarding — Provider Selection

Pick WHICH providers show in the statusline. `claude` is always implicit (the
Claude rate-limit line); external providers are everything else. Additive and
re-runnable — the single command to add / remove / re-check a provider.

## Grouping

- **Primary trio (מומלץ / recommended):** Claude · Codex · Antigravity.
- **Extras:** Copilot · GLM · Droid.

Present the trio first, then the extras. Never offer to remove Claude.

## Steps

1. Read `~/.claude/statusline-config.json`. If missing → tell the user the
   install is incomplete, point to `/statusline-init`, stop.
2. Determine the current selection to pre-check: `providers.selected` (minus
   `claude`) if present, else the enabled providers under `external_providers`.
3. Detect existing auth (read-only, cache-preferring, never prompts):
   ```bash
   python3 -c "import sys, os, json; sys.path.insert(0, os.path.expanduser('~/.claude/cc-2x-statusline/lib')); from onboarding import detect_all_auth; p=os.path.expanduser('~/.claude/statusline-config.json'); cfg=json.load(open(p)) if os.path.exists(p) else {}; print(json.dumps(detect_all_auth(cfg)))"
   ```
   Statuses: `ok` (detected) · `missing` (needs auth) · `unknown` (probe errored).
4. `AskUserQuestion` multi-select — trio first (label them "מומלץ"), extras after.
5. Apply atomically (build `['claude', <chosen in shown order>...]`):
   ```bash
   python3 -c "import sys, os; sys.path.insert(0, os.path.expanduser('~/.claude/cc-2x-statusline/lib')); from onboarding import apply_selection; apply_selection(os.path.expanduser('~/.claude/statusline-config.json'), ['claude','codex','antigravity'])"
   ```
   `apply_selection` writes `providers.selected`, mirrors it into
   `external_providers.<p>.enabled` (so the Node/Bash engines keep working with
   no code change), and auto-sets `tier` (`multi-cli` for 2+ providers).

6. **Auth stage (Phase 2).** For each selected provider, confirm it actually
   authenticates with a bounded probe (`validate_provider` → `ok`/`unauth`/
   `missing`/`unknown`). Only card the providers that are NOT `ok`:
   ```bash
   python3 -c "import sys, os, json; sys.path.insert(0, os.path.expanduser('~/.claude/cc-2x-statusline/lib')); from onboarding import validate_provider; p=os.path.expanduser('~/.claude/statusline-config.json'); cfg=json.load(open(p)) if os.path.exists(p) else {}; print(validate_provider('codex', cfg))"
   ```
   For each non-`ok` provider, drive the matching card (Hebrew-first, English
   terms) with `AskUserQuestion`, then re-run `validate_provider` to confirm:

   - **codex** — *Codex CLI · דרוש login*: "הריצו `codex login` בטרמינל אחר, ואז המשיכו."
   - **antigravity** — *Antigravity · דרוש login*: "הריצו `antigravity-usage login` (או פתחו את אפליקציית Antigravity / ה-IDE), ואז המשיכו."
   - **glm** — *z.ai key*: בקשו מהמשתמש את מפתח ה-z.ai (get it at https://z.ai). **אל תדפיסו את המפתח.** העבירו אותו דרך משתנה סביבה (לא בתוך ה-`-c`) והריצו:
     ```bash
     ZAI_KEY='PASTE_THE_KEY' python3 -c "import sys, os; sys.path.insert(0, os.path.expanduser('~/.claude/cc-2x-statusline/lib')); from onboarding import store_glm_key; err=store_glm_key(os.path.expanduser('~/.claude/statusline-config.json'), os.environ.get('ZAI_KEY','')); print(err or 'OK — key validated, saved to the OS keychain, plaintext removed from config')"
     ```
     `store_glm_key` validates the key first; on failure it prints an error and
     stores **nothing** (retry or skip). On success the key lives only in the
     keychain/secret store — never in the config file or chat.
   - **copilot** — *GitHub Copilot*: "הריצו `gh auth login`, ואז בחרו מצב: `individual` לרוב המשתמשים, או `org` לבריכת ארגון." במצב `individual` לא צריך לשמור token או cap; במצב `org` בקשו org slug ו-cap חודשי חיובי, ושמרו אותם ב-`external_providers.copilot.org` וב-`external_providers.copilot.cap` יחד עם `mode: "org"` (אפשר גם `pool` להצגה). אם `validate_provider('copilot', cfg)` מחזיר `missing`, חסר `gh` או שחסרים `org`/`cap` למצב org.
   - **droid** — *Factory Droid*: "התקינו/הפעילו את Factory Droid והתחילו session אחד, ואז המשיכו."

   A provider that stays non-`ok` after its card is fine — the selection is kept
   and the statusline shows a dim `no data — /statusline-onboarding` row until it
   authenticates. Never abort the wizard on one failed provider.

7. Close with: "נשמר. הפעילו מחדש את Claude Code כדי לטעון את ה-cockpit. הריצו
   `/statusline-onboarding` שוב מתי שתרצו כדי להוסיף / להסיר / לחבר מחדש provider."
