---
description: "Guide the user through the first-run onboarding flow after installing claude-2x-statusline. Use when the user asks what to do next after install, wants a quickstart, or asks for post-install help."
argument-hint: ""
allowed-tools: ["Read", "AskUserQuestion", "Bash"]
---

# Statusline Onboarding

Use this after install/update, or when the user asks what to do next.

## Goals

1. Confirm whether the statusline is already configured.
2. Show the user the shortest path to success.
3. Offer one immediate follow-up action instead of dumping every command at once.

## Steps

1. Read `~/.claude/statusline-config.json` if it exists.
2. If the config file is missing:
   - Tell the user the install is incomplete.
   - Point them to `/statusline-init`.
   - Stop.
3. If the config file exists:
   - Summarize the current tier and mode in one sentence.
   - Mention that a restart of Claude Code may be needed after a fresh install.
4. Ask the user which action they want right now:
   - Verify the install
   - Switch tier
   - Learn the segments
   - Check for updates
5. Based on the answer:
   - Verify the install: run `bash ~/.claude/cc-2x-statusline/doctor/doctor.sh` when bash is available.
   - Switch tier: point them to `/statusline-minimal`, `/statusline-standard`, or `/statusline-full`.
   - Learn the segments: point them to `/explain`, `/explain peak_hours`, `/explain rate_limits`.
   - Check for updates: point them to `/statusline-update`.