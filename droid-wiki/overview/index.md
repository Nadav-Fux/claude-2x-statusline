# claude-2x-statusline

A modular statusline plugin for Claude Code that renders a live terminal dashboard showing model info, context usage, rate limits, session cost, burn rate, cache efficiency, and git status. It also includes a narrator hook system that injects plain-language context-management advice above the user's prompt.

## What it does

At a glance, the statusline shows everything a Claude Code user needs to manage their session: which model is active, how much context window remains, whether rate limits are approaching, how much the session has cost, how fast tokens are burning, and whether the cache is being used efficiently.

The killer feature is remote policy updates. A `schedule.json` file hosted on GitHub controls peak-hour labels, promotional banners, and release notifications. When the maintainer updates that file, every running statusline picks up the change within 3 hours without requiring a `git pull` or reinstall.

The narrator is a second layer that sits above the prompt. It reads the same metrics the statusline displays and produces a short plain-language insight, like "Burning $18/hr, your 5-hour budget ends in ~40 min, consider Sonnet for simple steps." A rules engine handles the common cases in under 50ms. An optional Haiku LLM layer adds richer narrative when an Anthropic API key is available.

## Who uses it

Developers using Claude Code in the terminal who want visibility into session economics and rate limits. The plugin works on macOS, Linux, and Windows, with a companion VS Code extension for Cursor, Windsurf, and Antigravity users.

## Quick links

- [Architecture](architecture.md) and [getting started](getting-started.md)
- [Statusline tiers](../features/statusline-tiers.md) and [rolling metrics](../features/rolling-metrics.md)
- [Narrator system](../features/narrator.md) and [doctor diagnostics](../features/doctor.md)
- [Engine architecture](../systems/engines.md) and [runtime resolution](../systems/runtime-resolution.md)
- [Telemetry worker](../apps/telemetry-worker.md) and [VS Code extension](../apps/vscode-extension.md)
- [Configuration reference](../reference/configuration.md) and [schedule format](../reference/schedule-format.md)
