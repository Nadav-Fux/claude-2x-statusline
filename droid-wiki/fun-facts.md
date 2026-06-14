# Fun facts

## Bilingual everything

The README is written in both Hebrew and English. The Hebrew section comes first (`<div dir="rtl">`), followed by the English section. All narrator templates carry both `text` and `text_he` fields, and a structural test enforces that no new template can be added without a Hebrew translation.

## The doctor knows about 18 segments

`doctor/doctor.sh` stores detailed explanations for 18 statusline segments as entries in a bash associative array. Each entry is a multi-line string covering what the segment shows, how it is computed, what colors mean, and when it hides. This makes the doctor a self-documenting reference for every visible element of the statusline.

## Four numeric overflow bugs in one release

The April 19 bug-fix changelog describes four separate numeric overflow bugs fixed in the same batch: $1.2M/hr burn rate, $55B projected session cost, 29M% context usage, and $813/hr burn rate. All were caused by missing guards in rate calculations. The fix introduced the $200/hr sanity cap and 3-minute minimum window span that protect all rolling computations today.

## The token-optimizer incident

The doctor has a `restore-statusline` fix hint specifically because another plugin was hijacking the `statusLine` stanza in `settings.json`. The doctor detects when the statusLine command has been overwritten and can restore it. This is called out in the doctor source code comments as "the token-optimizer hijack incident."

## Cygpath is load-bearing

On Windows/Git Bash, Python cannot resolve MSYS-style paths like `/c/Users/...`. The hook scripts convert paths to native Windows form using `cygpath -w` before passing them to Python. Without this conversion, the narrator hooks silently fail on Windows.

## The longest file

`engines/python-engine.py` at 1,670 lines is the largest source file. It handles segment rendering, schedule fetching, timezone conversion, timeline drawing, rate limit bars, and metrics calculation in a single file. The Node.js port (`engines/node-engine.js`) is 915 lines, doing the same work more concisely thanks to JavaScript's more compact syntax.

## Telemetry ID generation cascade

The Bash engine tries four different methods to generate a 16-character hex telemetry ID: Python's `secrets.token_hex(8)`, `openssl rand -hex 8`, and finally `od -An -N8 -tx1 /dev/urandom`. This cascade ensures the ID can be generated even on minimal systems with unusual tool availability.
