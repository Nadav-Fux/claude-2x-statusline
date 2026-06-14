# Development workflow

## Branch and code

1. Fork the repository and create a feature branch from `main`
2. Make changes following the [patterns and conventions](patterns-and-conventions.md)
3. Ensure three-engine parity: if you change `engines/python-engine.py`, update `engines/node-engine.js` too
4. Add or update tests for any changed logic

## Test before submitting

```bash
# Python tests (must all pass)
pip install pytest tzdata
python -m pytest tests/ -v

# Node.js runtime test
node --test tests/node-runtime.test.mjs

# Worker test
node --test worker/worker.test.mjs

# Syntax check shell scripts
bash -n install.sh
bash -n doctor/doctor.sh
bash -n statusline.sh
```

## PR process

1. Push your branch to your fork
2. Open a pull request against `main`
3. Describe what changed and why
4. Reference any related issues
5. The maintainer reviews and merges

## Version bumping

The version appears in three files that must stay in sync:

| File | Field |
|------|-------|
| `package.json` | `"version"` |
| `plugin.json` | `"version"` |
| `vscode/package.json` | `"version"` |

The schedule's `release.latest_version` in `schedule.json` should also be updated.
