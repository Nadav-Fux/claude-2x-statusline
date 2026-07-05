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

5. For each selected provider whose detected status from step 2 is NOT `ok`,
   print the one-line auth hint (no interactive auth yet — that is Phase 2):
   - **codex** → "Run `codex login` in another terminal."
   - **antigravity** → "Run `antigravity-usage login` (or open the Antigravity app)."
   - **glm** → "Set a z.ai API key: export `ZAI_API_KEY=…` (hooks don't read your shell rc — a keychain option comes later)."
   - **copilot** → "Run `gh auth login`."
   - **droid** → "Install Factory Droid and start one session."

6. End with: "Saved. Restart Claude Code once to load the new cockpit. Re-run
   `/statusline-onboarding` anytime to add or remove a provider."
