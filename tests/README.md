# tests/

Pytest suite for `claude-2x-statusline`.

## Running

```bash
# All tests
python -m pytest tests/ -v

# Peak-hours tests only
python -m pytest tests/test_peak_hours.py -v

# Rolling-state tests only (requires Workstream B to have merged)
python -m pytest tests/test_rolling_state.py -v

# Stop on first failure
python -m pytest tests/ -x -v

# Coverage (requires pytest-cov)
python -m pytest tests/ --cov=lib --cov=engines --cov-report=term-missing -v
```

## File map

| File | What it tests |
|---|---|
| `conftest.py` | Shared fixtures: `mock_now`, `tmp_state_dir` |
| `test_peak_hours.py` | `seg_peak_hours` in `engines/python-engine.py` |
| `test_rolling_state.py` | `lib/rolling_state.py` (Workstream B) |

## Workstream dependency

`test_rolling_state.py` imports `lib.rolling_state`.  This module is delivered
by **Workstream B** and does not exist until that branch merges.  Running the
file before B merges will produce `pytest.skip` for every test rather than
failures — safe to include in CI from day one.

## Engine importability

`engines/python-engine.py` uses `if __name__ == "__main__"` to guard all
execution.  It has no top-level side-effect calls and imports cleanly via
`importlib.util.spec_from_file_location`.  `test_peak_hours.py` uses this
approach rather than `import engine` (the file name contains a hyphen).

If a future change introduces top-level side effects (e.g. `sys.stdin.read()`
at module scope), all tests in `test_peak_hours.py` will `pytest.skip` with
the message `engine import failed: <reason>`.

## What regressions these catch

### `test_peak_hours.py` (14 test cases)

| Regression | Covered by |
|---|---|
| Off-by-one on UTC→local conversion (pre-peak shows peak) | `test_pre_peak`, `test_post_peak_at_22` |
| Midnight-crossing window not recognised | `TestMidnightCrossingPeakUTCPlus3` (4 cases) |
| Saturday spillover into Sunday not detected | `test_saturday_spillover_into_sunday` |
| `mode="normal"` not suppressing the segment | `test_normal_mode_returns_empty` |
| DST spring-forward shifts local peak window incorrectly | `test_dst_spring_forward_2026` |
| DST fall-back shifts local peak window incorrectly | `test_dst_fall_back_2025` |

### `test_rolling_state.py` (7 test cases)

| Regression | Covered by |
|---|---|
| Eviction leaves stale samples > 60 min | `test_append_and_evict` |
| `rolling_rate` crashes on empty state | `test_rolling_rate_fewer_than_2_samples` |
| Rate formula wrong (unit error hrs vs mins) | `test_rolling_rate_correct_value` |
| Corrupt JSON causes uncaught exception | `test_corrupt_json_recovery` |
| Missing state file causes uncaught exception | `test_missing_file_created` |
| `cache_delta` calculation wrong | `test_cache_delta` |
| Concurrent writes corrupt the file | `test_concurrent_writes` |

## Known limitations

- **`test_concurrent_writes`** is marked `@pytest.mark.flaky` because
  `os.replace()` on Windows can raise `PermissionError` under heavy thread
  contention when antivirus software holds the file handle.  The test
  self-skips on such failures rather than failing CI.

- **DST tests** require `zoneinfo` (Python 3.9+).  On Python 3.8 they skip
  automatically with `pytest.skip("zoneinfo not available")`.

- `seg_peak_hours` stores derived values (`is_peak`, `peak_start_local`, etc.)
  back into `ctx` rather than returning them.  Tests assert on `ctx["is_peak"]`
  as the authoritative signal.  If the segment is refactored to use a different
  key, update the assertion accordingly.
