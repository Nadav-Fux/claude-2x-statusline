#!/usr/bin/env bash
# claude-2x-statusline — modular statusline for Claude Code
# Auto-detects runtime: Python → Node.js → pure bash
# https://github.com/Nadav-Fux/claude-2x-statusline

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY=$(command -v python3 2>/dev/null || command -v python 2>/dev/null)
NODE=$(command -v node 2>/dev/null)

if [ -n "$PY" ]; then
    exec "$PY" "$SCRIPT_DIR/engines/python-engine.py" "$@"
elif [ -n "$NODE" ]; then
    exec "$NODE" "$SCRIPT_DIR/engines/node-engine.js" "$@"
else
    exec bash "$SCRIPT_DIR/engines/bash-engine.sh" "$@"
fi
