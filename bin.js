#!/usr/bin/env node
// npx wrapper — spawns install.sh on macOS/Linux
const { execFileSync } = require('child_process');
const path = require('path');

const installScript = path.join(__dirname, 'install.sh');

if (process.platform === 'win32') {
  console.log('Windows detected. Run this in PowerShell instead:');
  console.log('  irm https://raw.githubusercontent.com/Nadav-Fux/claude-2x-statusline/main/install.ps1 | iex');
  process.exit(0);
}

try {
  execFileSync('bash', [installScript], { stdio: 'inherit' });
} catch (e) {
  process.exit(e.status || 1);
}
