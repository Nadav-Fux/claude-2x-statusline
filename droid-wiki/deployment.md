# Deployment

## Plugin installation

The plugin is deployed by cloning the repository and running the installer. There is no build step. See [getting started](../overview/getting-started.md) for installation instructions.

The installer handles:

1. Copying files to `~/.claude/cc-2x-statusline/`
2. Writing `~/.claude/statusline-config.json`
3. Wiring `statusLine` stanza in `~/.claude/settings.json`
4. Registering narrator hooks in `settings.json`
5. Fetching the initial schedule
6. Installing the VS Code extension (if a supported editor is detected)
7. Sending the install telemetry ping

## Updates

Updates are pulled via `git pull` in the install directory. The `/statusline-update` command or `update.sh` script automates this. The remote schedule's `release.latest_version` drives update notifications shown in the statusline.

Schedule-only updates (peak hours, banners, feature flags) happen automatically every 3 hours without any code update. See [peak hours and schedule](../features/peak-hours-schedule.md).

## Telemetry worker deployment

The Cloudflare Worker is deployed separately:

```bash
cd worker
wrangler deploy
wrangler kv key put --binding=TELEMETRY _auth_token "secret"
```

See [telemetry worker](../apps/telemetry-worker.md) for details.

## VS Code extension packaging

```bash
cd vscode
npm run package    # Produces claude-statusline-0.2.0.vsix
```

The `.vsix` can be installed via `code --install-extension claude-statusline-0.2.0.vsix` or published to the VS Code Marketplace.

## Uninstallation

Run `~/.claude/cc-2x-statusline/uninstall.sh` to remove all traces. See [installer pipeline](../systems/installer.md) for what gets cleaned up.

## Platform-specific notes

| Platform | Installer | Notes |
|----------|-----------|-------|
| macOS | `install.sh` | Python from Homebrew or system |
| Linux | `install.sh` | Python from distro package manager |
| Windows | `install.ps1` | Rejects Store stubs, probes portable installs |
