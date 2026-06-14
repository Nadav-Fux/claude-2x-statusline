# Debugging

## Statusline not appearing

1. Run `/statusline-doctor` to check installation health
2. Check `~/.claude/settings.json` has a `statusLine` stanza pointing to `cc-2x-statusline/statusline.sh`
3. Verify the runtime is available: `python3 --version` or `node --version`
4. On Windows, verify the interpreter is not a WindowsApps stub

## Statusline showing wrong data

1. Set `STATUSLINE_DEBUG=1` to enable debug output on stderr in the Python engine
2. Check `~/.claude/statusline-state.json` for corrupt rolling state (delete to reset)
3. Check `~/.claude/statusline-schedule.json` for stale schedule (delete to force refresh)
4. Verify the schedule URL in `~/.claude/statusline-config.json` is reachable

## Narrator not firing

1. Check `STATUSLINE_NARRATOR_ENABLED` is not set to `0`
2. Verify hooks are wired in `~/.claude/settings.json` (run `/statusline-doctor`)
3. For Haiku layer: verify `ANTHROPIC_API_KEY` is set and the `anthropic` package is installed
4. Check throttle: the narrator waits at least 5 minutes between prompt_submit emits
5. On Windows: verify `cygpath` is available for path conversion

## Debug mode

```bash
# Python engine debug output
STATUSLINE_DEBUG=1 python3 engines/python-engine.py < /dev/null

# Test statusline rendering directly
echo '{"model":"opus","context_window":{"pct":45}}' | python3 engines/python-engine.py

# Test narrator directly
python3 -c "from narrator.engine import run; print(run('prompt_submit'))"

# Test Node.js narrator
node narrator/cli.js prompt_submit
```

## Common errors

| Error | Cause | Fix |
|-------|-------|-----|
| Statusline empty | Engine crashed silently | Check `STATUSLINE_DEBUG=1` output |
| `$800/hr burn rate` | Missing spike guard | Should not occur after v2.1; verify rolling_state constants |
| Peak hours wrong time | Timezone conversion bug | Check schedule `tz` field and local timezone |
| Narrator hooks not wired | Install incomplete | Run `/statusline-doctor --fix` |
| JSON parse error in config | Corrupt config file | Delete `~/.claude/statusline-config.json` and reconfigure |
| Windows path errors | MSYS vs native path mismatch | Ensure `cygpath` is available in Git Bash |

## Doctor as a debugging tool

The doctor is the first-line debugging tool. It checks:

- Runtime availability
- Settings.json wiring
- Config file validity
- Dry-run statusline execution (captures exit code, output lines, timing)
- Hook registration

Run `bash doctor/doctor.sh --json` for machine-readable output that can be piped to other tools.
