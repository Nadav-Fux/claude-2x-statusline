# Glossary

| Term | Definition |
|------|------------|
| **Tier** | Display level controlling which segments render: `minimal` (1 line), `standard` (2 lines), or `full` (4 lines) |
| **Segment** | Individual statusline element (e.g. `model`, `context`, `rate_limits`, `cost`, `burn_rate`) |
| **Mode** | Rendering mode within a tier: `minimal` or `full`. Controls whether dashboard lines (timeline, rate bars, metrics) render below line 1 |
| **Narrator** | Hook-injected insight system that surfaces plain-language advice above the prompt. Two layers: rules engine (always on) and optional Haiku LLM |
| **Rules engine** | Template-based scoring system in `narrator/scoring.py` that evaluates observations on 4 axes (urgency, novelty, actionability, uniqueness) and picks up to 2 insights |
| **Haiku layer** | Optional LLM-augmented narrative using `claude-haiku-4-5`. Fires every 5 prompts or 15 minutes when `ANTHROPIC_API_KEY` is set |
| **Schedule** | Remote JSON file (`schedule.json` on GitHub) controlling peak-hour labels, banners, release notifications, and feature flags |
| **Rolling window** | 60-minute ring buffer at `~/.claude/statusline-state.json` storing per-sample cost, token counts, and cache metrics |
| **Burn rate** | Spending velocity ($/hr) computed from the rolling window. Minimum 3-minute span, $200/hr sanity cap |
| **Cache reuse** | Percentage of input tokens served from cache. Displayed with delta and idle/active state |
| **Doctor** | Diagnostic tool (`doctor/doctor.sh`) that checks installation health, explains segments, and applies fixes |
| **Diagnostic code** | Stable per-machine hex identifier shown at every doctor run. Used for anonymous telemetry correlation |
| **Runtime resolver** | Shared logic in `lib/resolve-runtime.sh` that finds a working Python or Node interpreter, rejecting Windows Store stubs |
| **Wire-json** | Cross-platform JSON merge/query library used by installers (`lib/wire-json.sh`, `lib/Wire-Json.ps1`) |
| **Battery bar** | Visual rate-limit indicator using Unicode block characters to show utilization percentage |
| **Framed text** | Narrator output wrapped in `//// ... ////` delimiters so it is visually distinct from normal prompt context |
| **Peak hours** | Historical schedule for when Anthropic throttled 5-hour quota consumption. Removed 2026-05-06; segment retained for custom-tier users |
| **Workflow** | Claude Code subagent execution unit. The statusline reads live and completed workflow state from session directories |
