#!/usr/bin/env bash
# Narrator: emits a plain-language session intro that Claude surfaces above the prompt.
# Never fails the session — all errors silent.
set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
NARR_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# On Windows / Git Bash, Python can't resolve /c/Users/... style paths.
# Convert to native form via cygpath when available.
if command -v cygpath >/dev/null 2>&1; then
    NARR_ROOT=$(cygpath -w "$NARR_ROOT")
fi

# Use the shared resolver that rejects Windows App-Store stubs and finds
# portable installs.
RESOLVER="$NARR_ROOT/lib/resolve-runtime.sh"
if [ -f "$RESOLVER" ]; then
    # shellcheck disable=SC1090
    . "$RESOLVER"
    PY=$(resolve_runtime python 2>/dev/null || true)
else
    PY=$(command -v python3 2>/dev/null || command -v python 2>/dev/null || true)
    case "$PY" in */WindowsApps/*|*\\WindowsApps\\*) PY="" ;; esac
fi

[ -z "$PY" ] && exit 0

exec "$PY" -c "
import sys, io
# Force UTF-8 stdout so the ⟨narrator⟩ directive + cost symbols don't blow up
# under Windows cp1252.
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, r'$NARR_ROOT')
try:
    from narrator.engine import run
    text = run('session_start')
    if text:
        sys.stdout.write(text)
        sys.stdout.write('\n')
except Exception:
    pass
"
