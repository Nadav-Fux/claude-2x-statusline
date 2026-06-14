# How to contribute

This is a solo-maintained project. Contributions are welcome via pull requests on GitHub.

## Working in this codebase

- Read [patterns and conventions](patterns-and-conventions.md) before making changes. The "never crash the caller" principle and three-engine parity requirements are the most important conventions.
- Read [development workflow](development-workflow.md) for the branch, code, test, PR cycle.
- See [testing](testing.md) for how to run the 138 Python tests and 8 Node.js tests.
- See [debugging](debugging.md) for common issues and troubleshooting steps.
- See [tooling](tooling.md) for build system and linting.

## Key constraints

1. **Three-engine parity** — Any statusline feature must work in both Python and Node.js engines. The Bash engine is intentionally minimal.
2. **Bilingual templates** — New narrator scoring templates need both `text` and `text_he` fields. A structural test enforces this.
3. **Windows compatibility** — Test changes against the Windows path handling in `lib/resolve-runtime.sh`. Reject WindowsApps stubs.
4. **Silent failure** — Engines and hooks must never crash. Wrap all logic in error handling that degrades gracefully.
5. **Atomic writes** — State files must be written atomically (tmpfile + rename).
