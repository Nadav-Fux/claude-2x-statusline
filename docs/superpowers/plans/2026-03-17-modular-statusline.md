# Modular Claude Code Statusline — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite claude-2x-statusline into a modular, multi-tier, cross-platform statusline with customizable segments, stdin JSON support, rate limits API, and multiple install methods.

**Architecture:** Config-driven segment system. Each segment is an independent function. User picks a tier (minimal/standard/full) or toggles individual segments. Three runtime backends: Python (bash wrapper), PowerShell, and pure-bash (Node.js fallback). Stdin JSON from Claude Code provides model, context %, cost, duration. OAuth API provides rate limits.

**Tech Stack:** Bash + Python 3 (primary), PowerShell 5.1+ (Windows), Node.js (fallback), jq (optional), curl (for OAuth API)

---

## File Structure

```
claude-2x-statusline/
├── statusline.sh           # Main entry: bash wrapper, detects runtime, reads config
├── statusline.ps1          # Windows PowerShell version
├── engines/
│   ├── python-engine.py    # Python runtime (primary, zero deps)
│   ├── node-engine.js      # Node.js fallback (if no Python)
│   └── bash-engine.sh      # Pure bash fallback (minimal features only)
├── install.sh              # Unix installer (interactive tier picker)
├── install.ps1             # Windows installer
├── uninstall.sh            # Unix uninstaller
├── config.example.json     # Example config with all segments documented
├── LICENSE
└── README.md
```

## Config File: `~/.claude/statusline-config.json`

```json
{
  "tier": "standard",
  "segments": {
    "time": true,
    "promo_2x": true,
    "model": true,
    "context": true,
    "git_branch": true,
    "git_dirty": true,
    "cost": false,
    "duration": false,
    "lines": false,
    "ts_errors": false,
    "rate_limits": false
  },
  "timezone": "auto",
  "promo_start": 20260313,
  "promo_end": 20260327,
  "separator": " │ ",
  "mode": "minimal",
  "full_mode_rate_limits": true,
  "full_mode_timeline": true
}
```

**Tiers (presets):**
- `minimal` — time + 2x promo + git (current behavior)
- `standard` — + model + context % + cost + duration
- `full` — + rate limits API + timeline bar + lines + ts_errors
- `custom` — user picks individual segments

---

### Task 1: Config System + Segment Framework (Python engine)

**Files:**
- Create: `engines/python-engine.py`
- Create: `config.example.json`
- Modify: `statusline.sh`

- [ ] **Step 1: Create config.example.json**

```json
{
  "tier": "standard",
  "segments": {
    "time": true,
    "promo_2x": true,
    "model": true,
    "context": true,
    "git_branch": true,
    "git_dirty": true,
    "git_ahead_behind": false,
    "cost": false,
    "duration": false,
    "lines": false,
    "ts_errors": false,
    "rate_limits": false
  },
  "timezone": "auto",
  "promo_start": 20260313,
  "promo_end": 20260327,
  "separator": " │ ",
  "mode": "minimal",
  "full_mode_rate_limits": true,
  "full_mode_timeline": true
}
```

- [ ] **Step 2: Create engines/python-engine.py with segment framework**

The Python engine reads stdin JSON + config file, runs enabled segments, and outputs ANSI line.

Core structure:
```python
#!/usr/bin/env python3
"""Claude Code statusline — modular Python engine."""
import sys, json, os, subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ── Config ──
DEFAULT_CONFIG = { ... }  # tier presets
TIER_PRESETS = {
    "minimal": ["time", "promo_2x", "git_branch", "git_dirty"],
    "standard": ["time", "promo_2x", "model", "context", "git_branch", "git_dirty", "cost", "duration"],
    "full": ["time", "promo_2x", "model", "context", "git_branch", "git_dirty", "git_ahead_behind", "cost", "duration", "lines", "rate_limits"],
}

def load_config():
    config_path = Path.home() / ".claude" / "statusline-config.json"
    if config_path.exists():
        with open(config_path) as f:
            return json.load(f)
    return DEFAULT_CONFIG

def get_enabled_segments(config):
    tier = config.get("tier", "standard")
    if tier == "custom":
        return [k for k, v in config.get("segments", {}).items() if v]
    return TIER_PRESETS.get(tier, TIER_PRESETS["standard"])

# ── Stdin JSON ──
def read_stdin():
    try:
        return json.loads(sys.stdin.read())
    except:
        return {}

# ── Segment functions ──
def seg_time(ctx): ...
def seg_promo_2x(ctx): ...
def seg_model(ctx): ...
def seg_context(ctx): ...
def seg_git_branch(ctx): ...
def seg_git_dirty(ctx): ...
def seg_cost(ctx): ...
def seg_duration(ctx): ...
def seg_lines(ctx): ...
def seg_rate_limits(ctx): ...

SEGMENTS = {
    "time": seg_time,
    "promo_2x": seg_promo_2x,
    "model": seg_model,
    "context": seg_context,
    "git_branch": seg_git_branch,
    "git_dirty": seg_git_dirty,
    "cost": seg_cost,
    "duration": seg_duration,
    "lines": seg_lines,
    "rate_limits": seg_rate_limits,
}

# ── Main ──
def main():
    config = load_config()
    stdin_data = read_stdin()
    mode = sys.argv[1] if len(sys.argv) > 1 else config.get("mode", "minimal")

    ctx = {"config": config, "stdin": stdin_data, "mode": mode}
    enabled = get_enabled_segments(config)

    parts = []
    for name in enabled:
        fn = SEGMENTS.get(name)
        if fn:
            result = fn(ctx)
            if result:
                parts.append(result)

    sep = config.get("separator", " │ ")
    dim_sep = f"\033[2m{sep}\033[0m"
    line1 = dim_sep.join(parts)

    print(line1, end="")

    if mode == "full":
        # timeline + rate limits on separate lines
        ...

if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Update statusline.sh as thin wrapper**

```bash
#!/usr/bin/env bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PY=$(command -v python3 2>/dev/null || command -v python 2>/dev/null)
NODE=$(command -v node 2>/dev/null)

if [ -n "$PY" ]; then
    exec "$PY" "$SCRIPT_DIR/engines/python-engine.py" "$@"
elif [ -n "$NODE" ]; then
    exec "$NODE" "$SCRIPT_DIR/engines/node-engine.js" "$@"
else
    exec bash "$SCRIPT_DIR/engines/bash-engine.sh" "$@"
fi
```

- [ ] **Step 4: Test with `echo '{}' | bash statusline.sh`**

Expected: shows time + 2x status + git (minimal tier default)

- [ ] **Step 5: Commit**

```bash
git add engines/python-engine.py config.example.json statusline.sh
git commit -m "feat: modular segment framework with config + tiers"
```

---

### Task 2: All Segments (Python)

**Files:**
- Modify: `engines/python-engine.py`

- [ ] **Step 1: Implement seg_time**
Israel time with auto DST (existing logic).

- [ ] **Step 2: Implement seg_promo_2x**
2x promotion status with color-coded countdown (existing logic).

- [ ] **Step 3: Implement seg_model**
Read `stdin["model"]["display_name"]`, display as `Opus 4.6`.

- [ ] **Step 4: Implement seg_context**
Read `stdin["context_window"]`, calculate percentage, color-code green/yellow/red.

- [ ] **Step 5: Implement seg_git_branch + seg_git_dirty + seg_git_ahead_behind**
Existing git logic + ahead/behind from `git rev-list --count`.

- [ ] **Step 6: Implement seg_cost**
Read `stdin["cost"]["total_cost_usd"]`, display as `$0.42`.

- [ ] **Step 7: Implement seg_duration**
Read `stdin["cost"]["total_duration_ms"]`, format as `23m` or `1h15m`.

- [ ] **Step 8: Implement seg_lines**
Read `stdin["cost"]["total_lines_added/removed"]`, display as `+45 -12`.

- [ ] **Step 9: Implement seg_ts_errors**
Read cached file `/tmp/tsc-errors-{hash}.txt` (same as AsafSaar), display count.

- [ ] **Step 10: Test each segment**

```bash
echo '{"model":{"display_name":"Opus 4.6"},"context_window":{"context_window_size":200000,"current_usage":{"input_tokens":80000,"cache_creation_input_tokens":0,"cache_read_input_tokens":0}},"cost":{"total_cost_usd":0.42,"total_duration_ms":1380000,"total_lines_added":45,"total_lines_removed":12}}' | bash statusline.sh
```

Expected: `20:30 │ ⚡ 2x 5h left │ Opus 4.6 │ 40% │ main +3 │ $0.420 │ 23m │ +45 -12`

- [ ] **Step 11: Commit**

```bash
git commit -am "feat: all segments (model, context, cost, duration, lines, ts_errors)"
```

---

### Task 3: Rate Limits + Full Mode (Python)

**Files:**
- Modify: `engines/python-engine.py`

- [ ] **Step 1: Implement OAuth token reader**
Read from: `$CLAUDE_CODE_OAUTH_TOKEN` env → `~/.claude/.credentials.json` → macOS keychain.

- [ ] **Step 2: Implement rate limits fetcher with 60s cache**
Fetch `https://api.anthropic.com/api/oauth/usage`, cache to `/tmp/claude/statusline-usage-cache.json`.

- [ ] **Step 3: Implement seg_rate_limits**
Parse `five_hour.utilization` and `seven_day.utilization`, build `●●●●○○○○○○ 42%` bars.

- [ ] **Step 4: Implement `--full` mode timeline**
48-char bar with `━` colored green (2x) / yellow (1x), `●` for current position.

- [ ] **Step 5: Implement full mode output**
Line 1: minimal segments. Line 2: blank. Line 3: timeline. Line 4: rate limits.

- [ ] **Step 6: Test full mode**

```bash
echo '{"model":{"display_name":"Opus 4.6"}}' | bash statusline.sh --full
```

- [ ] **Step 7: Commit**

```bash
git commit -am "feat: rate limits API + --full dashboard mode"
```

---

### Task 4: PowerShell Version (Windows)

**Files:**
- Rewrite: `statusline.ps1`

- [ ] **Step 1: Rewrite statusline.ps1 with same segment framework**
Read config from `~\.claude\statusline-config.json`, read stdin JSON with `ConvertFrom-Json`, implement all segments. No jq/curl needed — PowerShell has `Invoke-WebRequest` and `ConvertFrom-Json` built-in.

- [ ] **Step 2: Implement rate limits in PowerShell**
Read OAuth token from `~\.claude\.credentials.json`, fetch API with `Invoke-WebRequest`, cache to `$env:TEMP\claude\statusline-usage-cache.json`.

- [ ] **Step 3: Test on Windows**

```powershell
'{"model":{"display_name":"Opus 4.6"}}' | powershell -File statusline.ps1
'{}' | powershell -File statusline.ps1 --full
```

- [ ] **Step 4: Commit**

```bash
git commit -am "feat: PowerShell version with full feature parity"
```

---

### Task 5: Node.js Fallback Engine

**Files:**
- Create: `engines/node-engine.js`

- [ ] **Step 1: Implement node-engine.js**
Same segment framework as Python, but in Node.js. For users who have Node but not Python. Covers: time, promo, model, context, git, cost, duration. No rate limits (would need `https` module — keep simple).

- [ ] **Step 2: Test**

```bash
echo '{}' | node engines/node-engine.js
```

- [ ] **Step 3: Commit**

```bash
git commit -am "feat: Node.js fallback engine"
```

---

### Task 6: Pure Bash Fallback Engine

**Files:**
- Create: `engines/bash-engine.sh`

- [ ] **Step 1: Implement bash-engine.sh**
Minimal features in pure bash (no Python, no Node, no jq): time + 2x promo + git. This is the last resort for systems with nothing installed.

- [ ] **Step 2: Test**

```bash
echo '{}' | bash engines/bash-engine.sh
```

- [ ] **Step 3: Commit**

```bash
git commit -am "feat: pure bash fallback engine"
```

---

### Task 7: Interactive Installer

**Files:**
- Rewrite: `install.sh`
- Modify: `install.ps1`

- [ ] **Step 1: Rewrite install.sh with tier picker**

```
╭─────────────────────────────────────────╮
│  claude-2x-statusline installer         │
│                                         │
│  Choose your tier:                      │
│                                         │
│  1) Minimal  — time + 2x + git         │
│  2) Standard — + model + context + cost │
│  3) Full     — + rate limits + timeline │
│  4) Custom   — pick individual segments │
│                                         │
│  Install method:                        │
│  a) Auto (detect best runtime)          │
│  b) Python (recommended)               │
│  c) Node.js                            │
│  d) Pure bash (minimal only)           │
│                                         │
╰─────────────────────────────────────────╯
```

Saves config to `~/.claude/statusline-config.json`, copies files, updates settings.json.

- [ ] **Step 2: Support both git clone and curl one-liner**

```bash
# Git clone:
git clone ... && bash install.sh

# One-liner (downloads + installs):
curl -fsSL https://raw.githubusercontent.com/.../install.sh | bash
```

The installer detects if it's running from a cloned repo or standalone.

- [ ] **Step 3: Update install.ps1 with same tier picker**

- [ ] **Step 4: Add npx support via package.json**

```json
{
  "name": "claude-2x-statusline",
  "version": "2.0.0",
  "bin": { "claude-2x-statusline": "install.sh" }
}
```

- [ ] **Step 5: Test all install methods**

```bash
bash install.sh              # interactive
bash install.sh --tier standard --runtime python  # non-interactive
curl -fsSL ... | bash        # one-liner
npx claude-2x-statusline     # npx
```

- [ ] **Step 6: Commit**

```bash
git commit -am "feat: interactive installer with tier picker + npx support"
```

---

### Task 8: README + Documentation

**Files:**
- Rewrite: `README.md`

- [ ] **Step 1: Rewrite README with all features**

Show previews for each tier, install methods, customization, comparison with competitors.

- [ ] **Step 2: Commit + push**

```bash
git commit -am "docs: complete README rewrite"
git push origin main
```

---

## Output Preview by Tier

**Minimal:**
```
20:30  ⚡ 2x ACTIVE  5h 37m left  | main +3
```

**Standard:**
```
Opus 4.6 │ 40% │ ⚡ 2x ~ 1x 15:00 (5h37m) │ main +3 │ $0.42 │ 23m
```

**Full:**
```
Opus 4.6 │ 40% │ ⚡ 2x ~ 1x 15:00 (5h37m) │ main +3 │ $0.42 │ 23m │ +45 -12

today  ━━━━━━━━━━━━━━●━━━━━━━━━━━━━  ━ 2x  ━ 1x 15:00-21:00  ● now
current ●●●●○○○○○○ 42% ⟳ 10:00pm │ weekly ●●●○○○○○○○ 31% ❄ ⟳ mar 20
```
