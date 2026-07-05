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
6. For each selected provider whose detected status is not `ok`, print the auth
   hint (no interactive auth in this phase):
   - **codex** → `codex login`
   - **antigravity** → `antigravity-usage login` (or open the Antigravity app)
   - **glm** → set `ZAI_API_KEY` (hooks don't source your shell rc; a keychain flow comes later)
   - **copilot** → `gh auth login`
   - **droid** → install Factory Droid and start one session
7. Close with: "Saved. Restart Claude Code once to load the new cockpit."
