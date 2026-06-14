# Testing

## Test framework

Python tests use `pytest`. Node.js tests use the built-in `node --test` runner. No external test framework is needed for Node.js.

## Running tests

```bash
# All Python tests
pip install pytest tzdata
python -m pytest tests/ -v

# Node.js runtime test
npm run test:runtime
# or: node --test tests/node-runtime.test.mjs

# Worker tests
npm run test:worker
# or: node --test worker/worker.test.mjs
```

## Test inventory

| Test file | Focus area | Tests |
|-----------|-----------|-------|
| `tests/test_peak_hours.py` | Timezone conversion, DST, cross-timezone spillover | ~20 |
| `tests/test_narrator_scoring.py` | 4-axis scoring, all 15+ templates, novelty dedup | ~40 |
| `tests/test_narrator.py` | Narrator pipeline, Haiku integration, throttling | ~15 |
| `tests/test_narrator_memory.py` | Memory persistence, session rotation, eviction | ~12 |
| `tests/test_narrator_observations.py` | Observation building from session state | ~8 |
| `tests/test_narrator_rate_limits.py` | Rate limit threshold detection | ~6 |
| `tests/test_rolling_state.py` | Ring buffer, spike guards, rate calculation | ~15 |
| `tests/test_doctor.py` | Doctor checks | ~8 |
| `tests/test_doctor_telemetry.py` | Diagnostic codes, telemetry submission | ~12 |
| `tests/test_install_ping.py` | Install telemetry payload | ~10 |
| `tests/test_banners.py` | Banner display and expiration | ~10 |
| `tests/test_wire_json.py` | JSON merge/query (bash backend) | ~10 |
| `tests/test_wire_json_ps1.py` | JSON merge/query (PowerShell backend) | ~6 |
| `tests/test_workflows.py` | Workflow detection and aggregation | ~10 |
| `tests/test_usage_credits.py` | SDK credit meter | ~4 |
| `tests/test_option3_offloop.py` | Offloop option behavior | ~8 |
| `tests/test_option6_workflow_context.py` | Workflow context option | ~6 |
| `tests/test_option7_auth.py` | Auth mode option | ~8 |
| `tests/node-runtime.test.mjs` | Node.js engine parity | 4 |
| `tests/test_worker.py` | Worker endpoint tests | ~8 |

## Test patterns

- **Fixtures** in `tests/fixtures/` provide sample session data, transcript files, and config files
- **`conftest.py`** sets up test infrastructure including temporary directories and mock state files
- **Skipping** — Tests that require bash skip when bash is not in PATH (common on Windows CI)
- **Bilingual contract test** — A structural test enforces that every scoring template has both `text` and `text_he` fields

## What to test when adding features

- New statusline segment: add a test in the relevant test file verifying rendering output
- New narrator template: add scoring tests, ensure bilingual contract test passes
- New rolling-state logic: add tests in `test_rolling_state.py`
- Engine changes: verify both Python and Node.js tests pass
- Worker endpoint changes: add tests in `worker/worker.test.mjs`
