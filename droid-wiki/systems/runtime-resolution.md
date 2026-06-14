# Runtime resolution

## Purpose

`lib/resolve-runtime.sh` finds a working Python or Node.js interpreter on any platform. It handles edge cases that break naive `command -v` lookups, particularly on Windows where Microsoft Store stubs masquerade as installed interpreters.

## Resolution order

For each requested kind (`python` or `node`), the resolver tries:

1. **PATH lookup** — `command -v python3` (or `python`, `node`), skipping any path containing `WindowsApps`
2. **Portable install locations** — Probes common directories for portable installs (only when PATH gives nothing)

### Windows Store stub rejection

On Windows, the `python3` and `python` commands in `C:\Users\...\AppData\Local\Microsoft\WindowsApps\` are not real interpreters. They are app-execution aliases that open the Microsoft Store install dialog instead of running Python. The resolver explicitly rejects any path containing `WindowsApps`:

```bash
case "$p" in
    */WindowsApps/*|*\\WindowsApps\\*) continue ;;
esac
```

### Portable install probing

When PATH lookup fails, the resolver probes these locations:

**Python:**
- `~/tools/python-*/python.exe`
- `~/tools/python/python.exe`
- `~/AppData/Local/Programs/Python/Python3*/python.exe`
- `/c/Python3*/python.exe`
- `/c/Program Files/Python3*/python.exe`

**Node.js:**
- `~/tools/node-*/node.exe`
- `~/tools/node/node.exe`
- `~/AppData/Roaming/nvm/v*/node.exe`
- `/c/Program Files/nodejs/node.exe`

## Path conversion for Windows

The resolver converts Windows-style paths (`C:\Users\...`) to MSYS-style (`/c/Users/...`) for glob matching:

```bash
case "$home_win" in
    [A-Za-z]:\\*) home_win="/${home_win:0:1}/${home_win:3}"; home_win="${home_win//\\//}" ;;
esac
```

## Consumers

| Consumer | How it uses the resolver |
|----------|-------------------------|
| `statusline.sh` | Picks Python or Node for the engine |
| `hooks/narrator-*.sh` | Picks Python or Node for the narrator |
| `install.sh` | Detects available runtime for feature gating |
| `doctor/doctor.sh` | Checks runtime availability as a diagnostic |
| `doctor/fixes.sh` | Uses runtime for config fixes |
| `lib/wire-json.sh` | Selects backend for JSON manipulation |

## Key source files

| File | Purpose |
|------|---------|
| `lib/resolve-runtime.sh` | The resolver itself (sourced, not executed) |
| `statusline.sh` | Primary consumer |
| `hooks/narrator-prompt-submit.sh` | Narrator dispatch consumer |
| `hooks/narrator-session-start.sh` | Narrator dispatch consumer |

## Related pages

- [Engines](engines.md) — How the resolver feeds engine dispatch
- [Patterns and conventions](../how-to-contribute/patterns-and-conventions.md) — Windows compatibility patterns
