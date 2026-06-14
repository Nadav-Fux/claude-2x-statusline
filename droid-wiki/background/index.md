# Background

Design decisions and historical context that explain why the code is structured the way it is.

## Why three engines?

The plugin targets developers who may have any combination of Python, Node.js, or only Bash available. Python gives the fullest feature set (narrator with Haiku support). Node.js provides full statusline parity for JavaScript developers who may not have Python installed. Bash is the universal fallback that renders a minimal but functional statusline.

Maintaining three engines is a conscious tradeoff: more maintenance burden, but zero friction for users regardless of their runtime environment.

## Why a remote schedule?

Anthropic has changed their rate-limiting and peak-hour policies multiple times. Hardcoding peak hours in the plugin would require users to update every time the policy changes. By hosting `schedule.json` on GitHub, the maintainer can update one file and every running statusline picks up the change within 3 hours.

This design also enables promotional banners and feature flags to be pushed without code changes.

## Why framed narrator output?

The narrator wraps its output in `//// -> text ////` delimiters. This serves two purposes:

1. Visual distinction from normal prompt context, so the user knows this is an injected insight, not their own text
2. Parsing stability for Claude Code's prompt processing

## Why 4-axis scoring?

The narrator's scoring system uses four axes (urgency, novelty, actionability, uniqueness) rather than a simple priority queue. This prevents the same insight from repeating (novelty), ensures actionable advice ranks higher than pure information (actionability), and avoids restating facts the user already sees in the statusline (uniqueness).

## Why rolling windows instead of session averages?

Session averages are misleading during bursty sessions. If a user spends $5 in the first 10 minutes then goes idle, the lifetime average stays at $30/hr even hours later. A 10-minute rolling window captures the current spending velocity, which is what the user actually needs to know.

The spike guards ($200/hr cap, 3-minute minimum) were added after four separate numeric overflow bugs produced absurd values in early testing.

## Why atomic file writes?

The statusline runs frequently (every prompt). If the process is interrupted mid-write to `statusline-state.json` or `narrator-memory.json`, a corrupt file would persist and break subsequent runs. The tmpfile + rename pattern ensures the file is either fully written or unchanged.

## Why reject WindowsApps stubs?

On Windows, the `python3` command in `WindowsApps/` is not Python. It is a Microsoft Store alias that opens an install dialog. If the resolver accepted this path, the statusline would silently fail on every Windows machine that has not explicitly installed Python. Rejecting these stubs and probing portable install locations ensures the statusline works on fresh Windows setups.
