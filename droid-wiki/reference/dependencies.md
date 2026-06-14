# Dependencies

## Runtime dependencies

### Python engine

| Dependency | Required | Purpose |
|------------|----------|---------|
| Python 3.6+ | Yes (3.9+ for narrator) | Runtime |
| `tzdata` | Recommended | Timezone data on systems without system tz database |

### Node.js engine

| Dependency | Required | Purpose |
|------------|----------|---------|
| Node.js LTS | Yes | Runtime |

No npm dependencies for the engine itself.

### Bash engine

No external dependencies beyond Bash 4+.

### Narrator Haiku layer (optional)

| Dependency | Required | Purpose |
|------------|----------|---------|
| `anthropic` Python package | Only for Haiku | Anthropic SDK for claude-haiku-4-5 calls |
| `ANTHROPIC_API_KEY` env var | Only for Haiku | API authentication |

## Development dependencies

### Testing

| Dependency | Purpose |
|------------|---------|
| `pytest` | Python test runner |
| `tzdata` | Timezone data for peak-hour tests |

### VS Code extension

| Dependency | Purpose |
|------------|---------|
| `typescript` | TypeScript compiler |
| `@types/vscode` | VS Code API types |
| `@types/node` | Node.js types |
| `@vscode/vsce` | Extension packaging tool |

### Telemetry worker

| Dependency | Purpose |
|------------|---------|
| `wrangler` | Cloudflare Workers CLI |

## External services

| Service | Purpose | Required |
|---------|---------|----------|
| GitHub (raw content) | Schedule hosting | Yes (for remote schedule) |
| Cloudflare Workers | Telemetry endpoint | No (telemetry is opt-out) |
| Anthropic API | Haiku narrator + rate limits | No (optional features) |

## Dependency counts

| Category | Count |
|----------|-------|
| Python runtime deps | 0 (stdlib only) |
| Python optional deps | 1 (`anthropic`, `tzdata`) |
| npm deps (root) | 0 |
| npm devDeps (vscode) | 4 |
| npm deps (worker) | 0 |
