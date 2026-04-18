#!/usr/bin/env bash
# claude-2x-statusline — shared runtime resolver.
#
# Finds a working Python or Node interpreter, with special handling for
# Windows: rejects Microsoft Store app-execution aliases (WindowsApps\*.exe
# stubs that exit with an install nag instead of running) and searches a
# handful of common portable install locations so the full dashboard renders
# on fresh Windows setups without manual PATH wrangling.
#
# Source (do not execute). Callers:
#   . "$(dirname "$0")/lib/resolve-runtime.sh"
#   PY=$(resolve_runtime python)
#   NODE=$(resolve_runtime node)

resolve_runtime() {
    local kind="$1"

    local candidates=()
    case "$kind" in
        python) candidates=(python3 python) ;;
        node)   candidates=(node) ;;
        *)      return 1 ;;
    esac

    # 1) Anything already on PATH — as long as it's not a WindowsApps stub.
    for c in "${candidates[@]}"; do
        local p
        p=$(command -v "$c" 2>/dev/null) || continue
        [ -z "$p" ] && continue
        case "$p" in
            */WindowsApps/*|*\\WindowsApps\\*) continue ;;
        esac
        echo "$p"
        return 0
    done

    # 2) Common portable / user-local locations. Only probed when PATH gave
    # nothing — keeps Linux/macOS fast paths untouched.
    local home_win="${USERPROFILE:-$HOME}"
    case "$home_win" in
        [A-Za-z]:\\*) home_win="/${home_win:0:1}/${home_win:3}"; home_win="${home_win//\\//}" ;;
    esac

    local extra=()
    case "$kind" in
        python)
            while IFS= read -r p; do extra+=("$p"); done < <(
                ls -1 "$home_win"/tools/python-*/python.exe 2>/dev/null
                ls -1 "$home_win"/tools/python/python.exe 2>/dev/null
                ls -1 "$home_win"/AppData/Local/Programs/Python/Python3*/python.exe 2>/dev/null
                ls -1 /c/Python3*/python.exe 2>/dev/null
                ls -1 /c/Program\ Files/Python3*/python.exe 2>/dev/null
            )
            ;;
        node)
            while IFS= read -r p; do extra+=("$p"); done < <(
                ls -1 "$home_win"/tools/node-*/node.exe 2>/dev/null
                ls -1 "$home_win"/tools/node/node.exe 2>/dev/null
                ls -1 "$home_win"/AppData/Roaming/nvm/v*/node.exe 2>/dev/null
                ls -1 /c/Program\ Files/nodejs/node.exe 2>/dev/null
            )
            ;;
    esac

    for p in "${extra[@]}"; do
        [ -x "$p" ] || [ -f "$p" ] || continue
        case "$p" in */WindowsApps/*|*\\WindowsApps\\*) continue ;; esac
        echo "$p"
        return 0
    done

    return 1
}
