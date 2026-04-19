# Windows-specific hardening — WindowsApps stubs, cygpath, UTF-8

**Date:** 2026-04-19

---

## English

### The WindowsApps stub problem

Microsoft Store ships "app-execution aliases" — stub binaries placed in:

```
C:\Users\<user>\AppData\Local\Microsoft\WindowsApps\python.exe
C:\Users\<user>\AppData\Local\Microsoft\WindowsApps\node.exe
```

These stubs appear on `PATH` before any real installation. When called, they open a Store install prompt and exit — they don't run Python or Node. Any script that does `which python` or `python --version` on a machine without Python installed will silently get the stub path back, then fail confusingly when trying to use it.

#### The fix in `lib/resolve-runtime.sh`

The shared runtime resolver now explicitly rejects any path matching `*/WindowsApps/*`:

```bash
resolve_python() {
  for candidate in $(which -a python python3 python3.11 python3.12 python3.13 2>/dev/null); do
    # Reject Microsoft Store stubs
    case "$candidate" in
      */WindowsApps/*) continue ;;
    esac
    # Verify it actually runs
    if "$candidate" -c "import sys; print(sys.version)" &>/dev/null; then
      echo "$candidate"
      return 0
    fi
  done
  return 1
}
```

The same filter applies to Node resolution.

### Portable install probing

When the WindowsApps stub is rejected and no system Python is found, the resolver probes a set of known portable install locations in order:

```bash
PORTABLE_PYTHON_PATHS=(
  "$HOME/tools/python-*/python.exe"
  "$HOME/tools/python*/python.exe"
  "$LOCALAPPDATA/Programs/Python/Python3*/python.exe"
  "$LOCALAPPDATA/Programs/Python/Python31*/python.exe"
  "C:/Python3*/python.exe"
  "C:/Python*/python.exe"
)
```

The first path that exists, is not in `WindowsApps`, and successfully runs `python -c "print(1)"` is used. This handles the common Windows setup where Python is installed via a portable zip rather than the Microsoft Store or the official installer MSI.

### Path conversion: Git Bash `→` native Windows

Git Bash (the shell used in most Claude Code Windows setups) uses POSIX-style paths internally:

```
/c/Users/nadav/tools/python-3.13.3/python.exe
```

Python on Windows does not understand these paths. Module resolution fails with `ModuleNotFoundError` or simply silently imports the wrong file.

All hook scripts now convert paths via `cygpath -w` before passing them to Python:

```bash
PYTHON_NATIVE=$(cygpath -w "$PYTHON_PATH")
STATE_FILE_NATIVE=$(cygpath -w "$STATE_FILE")

"$PYTHON_NATIVE" "$SCRIPT_NATIVE" --state "$STATE_FILE_NATIVE"
```

`cygpath -w` converts `/c/Users/nadav/...` → `C:\Users\nadav\...`. The result is passed as the invocation path, so Python receives native Windows paths throughout.

### UTF-8 stdout forcing

Windows uses **cp1252** (Windows-1252) as the default code page in many terminal configurations. The statusline uses several non-ASCII characters:

- `⟨ narrator ⟩` — the narrator hook directive delimiters
- `·` — the separator between narrator insights (U+00B7)
- `↑` — the cache delta arrow (U+2191)
- `──` — the horizontal rule in the full-tier display (U+2500)

Under cp1252, any of these cause a `UnicodeEncodeError` and the engine crashes, producing a blank statusline.

All Python hooks now force UTF-8 output via two mechanisms:

```bash
# In the hook wrapper shell script:
export PYTHONIOENCODING=utf-8
```

```python
# In the Python engine itself (top of file):
import sys
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
```

The shell export handles the case where the Python script is invoked as a subprocess. The in-script reconfiguration handles the case where Python is invoked directly.

### Embeddable Python (`python313._pth`)

Some Windows users install Python via the embeddable distribution (a zip file, common in portable setups). The embeddable Python has a `python313._pth` file that **hard-codes `sys.path`** and ignores `PYTHONPATH` entirely.

If a statusline dependency (e.g., `json5`, `tomli`) is installed via pip into a non-standard location, it won't be found.

**How to fix it**: open `python313._pth` (in the Python install directory) and add the site-packages path:

```
# python313._pth (embeddable Python)
python313.zip
.

# Uncomment to enable site packages:
# import site

# Add this line manually for portable pip installs:
../lib/site-packages
```

Or uncomment `import site` if you want pip's default site-packages location to be respected. The statusline install script detects embeddable Python and adds this automatically when it finds `python313._pth` in the install directory.

### Windows-specific config flag

If you're on Windows and the automatic detection isn't working, you can force native-path mode:

```json
// ~/.claude/statusline-config.json
{
  "windows_native_paths": true
}
```

This forces `cygpath -w` conversion on all paths, even if `cygpath` reports that conversion is not needed (i.e., you're already using native paths).

### Summary of Windows changes

| Issue                           | Location                    | Fix                                          |
|---------------------------------|-----------------------------|----------------------------------------------|
| WindowsApps stubs on PATH       | `lib/resolve-runtime.sh`    | Reject `*/WindowsApps/*` paths               |
| Portable Python not found       | `lib/resolve-runtime.sh`    | Probe `~/tools/`, `AppData/Programs/Python`  |
| Git Bash paths break Python     | All hook scripts            | `cygpath -w` conversion before invocation    |
| cp1252 crashes on non-ASCII     | Python engines + hook scripts | `PYTHONIOENCODING=utf-8` + `reconfigure()`  |
| Embeddable Python missing deps  | `install.sh` + docs         | Patch `python313._pth` automatically         |

---

<div dir="rtl">

## עברית

### Windows — ה-stubs של Microsoft Store

Windows שם על ה-PATH קבצי `python.exe` ו-`node.exe` שהם stub בלבד — הם פותחים דיאלוג התקנה מה-Store ומסתיימים. כל script שמריץ `which python` מקבל חזרה את ה-stub הזה ואז נכשל בצורה לא ברורה.

**התיקון**: `lib/resolve-runtime.sh` דוחה בצורה מפורשת כל path שמכיל `*/WindowsApps/*`.

### גילוי portable installs

אחרי שה-stub נדחה, ה-resolver בודק מיקומים ידועים של Python פורטבילי: `~/tools/python-*/python.exe`, `AppData/Local/Programs/Python/Python3*/python.exe`, ועוד. מתאים לסטאפ עם Python מ-zip ולא מה-Store או ה-MSI.

### המרת paths של Git Bash

Git Bash משתמש ב-paths כמו `/c/Users/nadav/...`. Python ב-Windows לא מבין את זה. כל ה-hooks מעבירים עכשיו paths דרך `cygpath -w` לפני הקריאה ל-Python, מה שממיר ל-`C:\Users\nadav\...`.

### UTF-8 ב-stdout

Windows משתמש ב-cp1252 כ-default. התווים שלנו — `⟨`, `·`, `↑`, `──` — גורמים ל-`UnicodeEncodeError` ומקרסים את ה-engine.

שני מנגנוני הגנה: `export PYTHONIOENCODING=utf-8` ב-shell, ו-`sys.stdout.reconfigure(encoding='utf-8')` בתוך ה-Python עצמו.

### Python embeddable

ה-embeddable Python יש לו `python313._pth` שנועל את `sys.path` — `PYTHONPATH` מתעלם לחלוטין. ה-install script מזהה את זה ומתקן את ה-`_pth` אוטומטית.

</div>
