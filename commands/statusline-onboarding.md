---
description: "Choose which AI-CLI providers appear in your statusline (Claude, Codex, Antigravity, + Copilot/GLM/Droid)"
argument-hint: ""
allowed-tools: ["Read", "AskUserQuestion", "Bash"]
---

# Statusline Onboarding — Provider Selection

Let the user pick WHICH providers show in the statusline cockpit. `claude` is
always implicit (the Claude rate-limit line). This flow is additive and
re-runnable: run it any time to add or remove a provider.

## Steps

1. Read `~/.claude/statusline-config.json`.
   - If it is missing, tell the user the install is incomplete and point them to
     `/statusline-init`, then stop.
   - Note the current selection: `providers.selected` if present, otherwise the
     enabled providers under `external_providers` (that is what will be
     pre-selected).

2. Detect existing auth (read-only, no prompts) so you can flag what still needs
   setup. Run:
   ```bash
   python3 -c "import sys, os, json; sys.path.insert(0, os.path.expanduser('~/.claude/cc-2x-statusline/lib')); from onboarding import detect_all_auth; p=os.path.expanduser('~/.claude/statusline-config.json'); cfg=json.load(open(p)) if os.path.exists(p) else {}; print(json.dumps(detect_all_auth(cfg)))"
   ```

3. Ask the user with a multi-select `AskUserQuestion`. List the **primary trio
   first**, then the extras:
   - **Codex** (OpenAI) — trio · מומלץ
   - **Antigravity** (Google) — trio · מומלץ
   - **Copilot** (GitHub) — extra
   - **GLM** (z.ai) — extra
   - **Droid** (Factory) — extra
   (Claude is always on; do not offer to remove it.)

4. Apply the selection atomically. Build the final list as `["claude", <chosen>...]`
   in the order shown, then run (substitute the real list):
   ```bash
   python3 -c "import sys, os; sys.path.insert(0, os.path.expanduser('~/.claude/cc-2x-statusline/lib')); from onboarding import apply_selection; apply_selection(os.path.expanduser('~/.claude/statusline-config.json'), ['claude','codex','antigravity'])"
   ```
   This writes `providers.selected`, mirrors it into `external_providers`, and
   auto-sets the tier (`multi-cli` for 2+ providers).

5. **Auth stage.** For each selected provider run a bounded auth probe and card
   only the ones that are NOT `ok` (statuses: `ok`/`unauth`/`missing`/`unknown`):
   ```bash
   python3 -c "import sys, os, json; sys.path.insert(0, os.path.expanduser('~/.claude/cc-2x-statusline/lib')); from onboarding import validate_provider; p=os.path.expanduser('~/.claude/statusline-config.json'); cfg=json.load(open(p)) if os.path.exists(p) else {}; print(validate_provider('codex', cfg))"
   ```
   Drive each card with `AskUserQuestion` (Hebrew-first labels, English terms),
   then re-run `validate_provider` to confirm:
   - **codex** — "הריצו `codex login` בטרמינל אחר, ואז המשיכו." (statusline reads Codex's own session files — no key to paste.)
   - **antigravity** — "הריצו `antigravity-usage login` (או פתחו את אפליקציית Antigravity / ה-IDE), ואז המשיכו."
   - **glm** — ask for the z.ai key (https://z.ai). **Never print the key.** Pass
     it through an env var (not inside the `-c`) so it stays out of the python
     argv, then call `store_glm_key`:
     ```bash
     ZAI_KEY='PASTE_THE_KEY' python3 -c "import sys, os; sys.path.insert(0, os.path.expanduser('~/.claude/cc-2x-statusline/lib')); from onboarding import store_glm_key; err=store_glm_key(os.path.expanduser('~/.claude/statusline-config.json'), os.environ.get('ZAI_KEY','')); print(err or 'OK — key validated, saved to the OS keychain, plaintext removed from config')"
     ```
     It validates the key first; on failure it stores **nothing** and prints an
     error (offer retry / skip). On success the key lives only in the keychain /
     secret store, never in the config or chat.
   - **copilot** — "הריצו `gh auth login`." For an org pool, also set `COPILOT_ORG` (or `external_providers.copilot.org`) to the org slug.
   - **droid** — "התקינו/הפעילו את Factory Droid והתחילו session אחד, ואז המשיכו."

   Never abort the wizard on one failing provider — keep the selection. A
   selected provider that stays non-`ok` renders a dim
   `no data — /statusline-onboarding` row until it authenticates.

6. End with: "Saved. Restart Claude Code once to load the new cockpit. Re-run
   `/statusline-onboarding` anytime to add, remove, or re-auth a provider."
