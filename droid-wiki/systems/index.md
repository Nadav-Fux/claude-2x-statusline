# Systems

Internal building blocks that power the statusline and narrator. These are architectural components that do not map to a single user-visible feature.

- [Engines](engines.md) — Three parallel rendering implementations (Python, Node.js, Bash)
- [Runtime resolution](runtime-resolution.md) — Interpreter detection with Windows compatibility
- [Shared libraries](shared-libraries.md) — Rolling state, workflow detection, JSON manipulation
- [Hooks and commands](hooks-and-commands.md) — Claude Code hook integration and slash commands
- [Installer pipeline](installer.md) — Cross-platform setup, update, and uninstall
