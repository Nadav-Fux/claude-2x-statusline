# Hooks and commands

## Purpose

Claude Code integration layer. Hooks connect the narrator to Claude Code's session lifecycle. Slash commands let users control the statusline from within Claude Code. Skills provide guided setup flows.

## Hooks

Two hook scripts fire on Claude Code lifecycle events, registered via `hooks/hooks.json`:

```json
{
  "hooks": {
    "SessionStart": [{
      "hooks": [{
        "type": "command",
        "command": "bash \"${CLAUDE_PLUGIN_ROOT}/hooks/narrator-session-start.sh\""
      }]
    }],
    "UserPromptSubmit": [{
      "hooks": [{
        "type": "command",
        "command": "bash \"${CLAUDE_PLUGIN_ROOT}/hooks/narrator-prompt-submit.sh\""
      }]
    }]
  }
}
```

### Hook dispatch

Both hook scripts follow the same pattern:

1. Source `lib/resolve-runtime.sh` to find Python or Node
2. Try Python narrator first (`narrator/engine.py` via `python -c`)
3. On Python failure, fall back to Node.js narrator (`narrator/cli.js`)
4. Always exit 0 (never block the session)

The hooks use `cygpath -w` on Windows/Git Bash to convert MSYS paths to native form, since Python cannot resolve `/c/Users/...` style paths.

### What hooks emit

The narrator outputs framed text (`//// -> insight text ////`) to stdout. Claude Code surfaces this above the user's next prompt. If the narrator returns nothing (throttled, disabled, no data), the hook exits silently.

## Slash commands

Eleven command definitions live in `commands/`:

| Command | File | Purpose |
|---------|------|---------|
| `/statusline-init` | `statusline-init.md` | Full install from plugin runtime files |
| `/statusline-minimal` | `statusline-minimal.md` | Switch to minimal tier |
| `/statusline-standard` | `statusline-standard.md` | Switch to standard tier |
| `/statusline-full` | `statusline-full.md` | Switch to full tier |
| `/statusline-tier` | `statusline-tier.md` | Interactive tier picker |
| `/statusline-doctor` | `statusline-doctor.md` | Run diagnostics |
| `/statusline-update` | `statusline-update.md` | Check for and apply updates |
| `/statusline-onboarding` | `statusline-onboarding.md` | Post-install guided walkthrough |
| `/explain` | `explain.md` | Explain statusline segments |
| `/narrate` | `narrate.md` | Manual narrator trigger |
| `/narrator-lang` | `narrator-lang.md` | Switch narrator language |

Commands are markdown files with YAML frontmatter defining the description, allowed tools, and argument hints. Claude Code reads these and executes the embedded steps.

## Skills

Five skills live in `skills/`:

| Skill | Purpose |
|-------|---------|
| `skills/setup/SKILL.md` | Guided initial setup with tier picker |
| `skills/onboarding/SKILL.md` | Post-install first-run walkthrough |
| `skills/full/SKILL.md` | Switch to full tier |
| `skills/standard/SKILL.md` | Switch to standard tier |
| `skills/minimal/SKILL.md` | Switch to minimal tier |

Skills are similar to commands but can be triggered by natural language. They are registered in `plugin.json` via `"skills": "./skills/"`.

## Plugin manifest

`plugin.json` registers the plugin with Claude Code:

```json
{
  "name": "claude-2x-statusline",
  "version": "2.2.0",
  "commands": "./commands/",
  "skills": "./skills/",
  "hooks": "./hooks/"
}
```

When installed via Claude Code's plugin system, commands, skills, and hooks are auto-discovered from these directories.

## Key source files

| File | Purpose |
|------|---------|
| `hooks/hooks.json` | Claude Code hook registration |
| `hooks/narrator-prompt-submit.sh` | UserPromptSubmit hook |
| `hooks/narrator-session-start.sh` | SessionStart hook |
| `commands/*.md` | 11 slash command definitions |
| `skills/*/SKILL.md` | 5 skill definitions |
| `plugin.json` | Plugin manifest |

## Related pages

- [Narrator](../features/narrator.md) — What the hooks trigger
- [Doctor diagnostics](../features/doctor.md) — The `/statusline-doctor` command
- [Installer pipeline](installer.md) — How hooks get wired into `settings.json`
