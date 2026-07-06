# Contributing to claude-2x-statusline

Thanks for taking a look. This is a small, mostly-solo OSS project — keep
changes focused and prefer minimal diffs over refactors.

## Dev setup

```bash
# Python test suite
python3.12 -m venv .venv
source .venv/bin/activate
pip install pytest tzdata
python -m pytest tests/ -q

# Node runtime parity + worker tests
npm install
npm run test:runtime
npm run test:worker
```

Before opening a PR, both suites should be green (a couple of pre-existing,
known-flaky/known-failing tests are called out in `tests/README.md` — you
don't need to fix those unless your change touches them).

## The engine-parity rule

This project ships three interchangeable statusline engines
(`engines/python-engine.py`, `engines/node-engine.js`, `engines/bash-engine.sh`)
selected at runtime based on what's installed on the user's machine. They must
render equivalent output for the same input.

- **`engines/python-engine.py` is the source of truth.** New features land
  there first.
- **`engines/node-engine.js` follows.** It should mirror the Python engine's
  behavior closely enough that switching engines is invisible to the user.
  JS-side parity mirrors of shared Python modules live alongside them (e.g.
  `lib/usage_providers.js` mirrors `lib/usage_providers.py`).
- **`engines/bash-engine.sh` is a minimal last-resort fallback** (no Python,
  no Node, no `jq`). It only needs to cover the baseline segments (peak hours,
  model, git, rate limits) — it does not need feature parity with the other
  two engines.
- **The narrator (`narrator/`) is Python-only.** It requires Python 3.9+ and
  has no Node or bash equivalent; on Node-only or bash-only installs, the
  narrator hooks simply no-op until Python becomes available.

## Provider architecture (in brief)

- `lib/usage_providers.py` defines a `PROVIDERS` registry (provider name →
  display label + source type) and a `get_<name>_usage(config)` reader per
  provider, dispatched through `get_provider_usage(provider, config)`.
- Every fetched record is cached on disk at
  `~/.claude/statusline-usage-<provider>.json` (see `_cache_path`).
- **Non-blocking render contract:** the statusline's render path only reads
  caches (`read_cached_external_usage`) — it never blocks on network or a
  subprocess. Refreshing a stale cache is a detached background spawn (see
  `_spawn_provider_refresh`, used by the GLM/Copilot readers) that writes the
  cache for the *next* render; the current render returns the (possibly
  stale) cached record immediately.
- Which providers render, and in what order, is controlled by
  `providers.selected` in `~/.claude/statusline-config.json` (falling back to
  the legacy per-provider `external_providers.<name>.enabled` flags).

## Adding a new provider

1. Add an entry to `PROVIDERS` in `lib/usage_providers.py` (display name +
   source label).
2. Write `get_<name>_usage(config)`. It must never raise — catch everything
   and return `unavailable(name)` on any failure. If fetching requires
   network or a subprocess call that could block, don't call it synchronously
   on the render path: follow the cache-file + detached-refresh pattern used
   by `get_copilot_usage`/`get_glm_usage` instead of a blocking fetch.
3. Wire the new reader into `get_provider_usage()`'s dispatch and
   `collect_external_usage()`'s iteration.
4. Add tests to `tests/test_usage_providers.py` — at minimum, cover the
   "never raises, always returns a dict with `available`" invariant and any
   parsing edge cases for the provider's data source.
5. Optional JS parity: if the provider should also render from
   `engines/node-engine.js` (e.g. for the `multi-cli` tier), mirror the
   reader in `lib/usage_providers.js` and add coverage in
   `tests/usage-providers.test.mjs`. The bash engine does not need parity.
