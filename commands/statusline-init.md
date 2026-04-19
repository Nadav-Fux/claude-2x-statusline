---
description: "Initialize the full claude-2x-statusline install from the plugin/runtime files"
allowed-tools: ["Bash"]
argument-hint: "[minimal|standard|full]"
---

Complete a full claude-2x-statusline install for the user.

## Steps

1. Detect whether the user is on Windows PowerShell or a bash-like shell.
2. If bash-like, run `bash ~/.claude/cc-2x-statusline/install.sh --tier ${ARGUMENTS:-full}`.
3. If Windows PowerShell only, run `powershell -NoProfile -ExecutionPolicy Bypass -File "$env:USERPROFILE\.claude\cc-2x-statusline\install.ps1" -Tier ${ARGUMENTS:-full}`.
4. Show the installer output.
5. Tell the user to restart Claude Code.
