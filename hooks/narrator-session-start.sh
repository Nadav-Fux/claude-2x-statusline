#!/usr/bin/env bash
# Narrator: emits a plain-language session intro that Claude surfaces above the prompt.
# Never fails the session — all errors silent.
set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
NARR_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
NARR_ROOT_NATIVE="$NARR_ROOT"

# On Windows / Git Bash, Python can't resolve /c/Users/... style paths.
# Convert to native form via cygpath when available.
if command -v cygpath >/dev/null 2>&1; then
    NARR_ROOT_NATIVE=$(cygpath -w "$NARR_ROOT")
fi

# Use the shared resolver that rejects Windows App-Store stubs and finds
# portable installs.
RESOLVER="$NARR_ROOT/lib/resolve-runtime.sh"
if [ -f "$RESOLVER" ]; then
    # shellcheck disable=SC1090
    . "$RESOLVER"
    PY=$(resolve_runtime python 2>/dev/null || true)
    NODE=$(resolve_runtime node 2>/dev/null || true)
else
    PY=$(command -v python3 2>/dev/null || command -v python 2>/dev/null || true)
    NODE=$(command -v node 2>/dev/null || true)
    case "$PY" in */WindowsApps/*|*\\WindowsApps\\*) PY="" ;; esac
fi

# Try Python narrator first (full feature parity + Haiku support)
if [ -n "$PY" ]; then
    STATUSLINE_NARR_ROOT="$NARR_ROOT_NATIVE" exec "$PY" -c "
import os, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
narr_root = os.environ.get('STATUSLINE_NARR_ROOT', '')
if narr_root:
    sys.path.insert(0, narr_root)
try:
    from narrator.engine import run
    text = run('session_start')
    if text:
        sys.stdout.write(text)
        sys.stdout.write('\n')
except Exception:
    pass
"
fi

# Fallback: Node.js narrator (full rules engine + optional Haiku)
# Uses narrator/cli.js wrapper to avoid path-escaping issues with node -e on Windows.
if [ -n "$NODE" ]; then
    exec "$NODE" "$NARR_ROOT/narrator/cli.js" session_start
fi

exit 0
