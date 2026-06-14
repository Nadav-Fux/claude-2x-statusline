# Tooling

## Build system

The project has no compilation step for the main plugin. Python, JavaScript, and Bash files run directly. The only build step is the VS Code extension TypeScript compilation.

### VS Code extension

```bash
cd vscode
npm install
npm run compile    # TypeScript → out/extension.js
npm run package    # Build .vsix via vsce
```

### Telemetry worker

```bash
cd worker
npm install
wrangler deploy    # Deploy to Cloudflare
```

## Linting and quality

- **Shell scripts**: Use `bash -n <file>` for syntax checking. No formal linter is configured.
- **Python**: No formal linter configured. Follow existing style (4-space indent, type hints, docstrings).
- **JavaScript/TypeScript**: TypeScript compiler (`tsc`) for the VS Code extension. No ESLint configured.
- **Markdown**: No formal linter.

## Package scripts

From `package.json`:

```json
{
  "scripts": {
    "test:runtime": "node --test tests/node-runtime.test.mjs",
    "test:worker": "node --test worker/worker.test.mjs"
  }
}
```

## CI/CD

No CI/CD pipeline is configured in the repository. Tests are run manually before releases. The telemetry worker is deployed manually via `wrangler deploy`.

## File watching (VS Code extension development)

```bash
cd vscode
npm run watch    # tsc -watch for live recompilation
```

Press F5 in VS Code to launch an Extension Development Host for testing.
