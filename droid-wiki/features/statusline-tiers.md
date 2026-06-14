# Statusline tiers

## Purpose

The statusline renders in one of three tiers, each showing progressively more information. The tier system lets users balance information density against terminal space.

## Tier presets

Each tier maps to a list of segments rendered on line 1. The segment lists are defined identically in both `engines/python-engine.py` and `engines/node-engine.js`:

| Tier | Lines | Segments on line 1 | Extra lines |
|------|-------|---------------------|-------------|
| `minimal` | 1 | model, context, git_branch, git_dirty, rate_limits, env | none |
| `standard` | 1-2 | model, context, vim_mode, agent, workflows, git_branch, git_dirty, cost, effort, env | rate limit bars |
| `full` | 4 | Same as standard + usage_credits | timeline, rate limit bars, burn/cache metrics |

The `full` tier triggers three additional rendering passes in the main loop:
- **Line 2**: Visual schedule timeline (`build_timeline`)
- **Line 3**: Rate limit bars (`build_rate_limits_line`)
- **Line 4**: Burn rate, context depletion, cache metrics (`build_metrics_line`)

Lines 2-4 are guarded by feature flags from the remote schedule (`features.show_timeline`, `features.show_rate_limits`).

## Segment catalog

The engines support these segments:

| Segment | Description | Tiers |
|---------|-------------|-------|
| `model` | Current model name with effort indicator | all |
| `context` | Context window usage percentage with color coding | all |
| `git_branch` | Current git branch name | all |
| `git_dirty` | Dirty/clean indicator (asterisk or checkmark) | all |
| `rate_limits` | 5-hour and weekly rate limit utilization | all |
| `env` | Environment indicator (auth mode, API vs OAuth) | all |
| `vim_mode` | Vim mode indicator if active | standard, full |
| `agent` | Active agent/tool indicator | standard, full |
| `workflows` | Live subagent workflow count and token usage | standard, full |
| `cost` | Session cumulative cost in USD | standard, full |
| `usage_credits` | SDK credit meter | full |
| `effort` | Thinking effort level (HI/MED/LO) | standard, full |

## Mode vs tier

The `mode` field in `~/.claude/statusline-config.json` controls whether dashboard lines render:

- `mode: "minimal"` — Only line 1 renders, even in full tier
- `mode: "full"` — All lines render for the chosen tier

This lets users use the full segment set on line 1 without the dashboard lines below.

## Switching tiers

Three slash commands switch tiers instantly:

- `/statusline-minimal` — writes `"tier": "minimal", "mode": "minimal"`
- `/statusline-standard` — writes `"tier": "standard", "mode": "minimal"`
- `/statusline-full` — writes `"tier": "full", "mode": "full"`

Each command reads `~/.claude/statusline-config.json`, updates the tier and mode fields, and writes it back.

## ANSI rendering

Segments use a shared color palette (see [patterns and conventions](../how-to-contribute/patterns-and-conventions.md)). Rate limit bars use Unicode block characters (`▰▱`) for visual battery indicators. The timeline uses `━` and `●` characters for a horizontal schedule view.

## Key source files

| File | Purpose |
|------|---------|
| `engines/python-engine.py` | Segment definitions, rendering loop, tier presets |
| `engines/node-engine.js` | Node.js parity implementation |
| `engines/bash-engine.sh` | Minimal Bash fallback (4 segments only) |
| `config.example.json` | Example configuration with all segment toggles |
| `skills/full/SKILL.md` | Claude Code skill for switching to full tier |
| `skills/standard/SKILL.md` | Claude Code skill for switching to standard tier |
| `skills/minimal/SKILL.md` | Claude Code skill for switching to minimal tier |
