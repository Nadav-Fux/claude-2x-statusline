#!/usr/bin/env node
// npx wrapper — spawns the platform-appropriate installer
const { execFileSync } = require('child_process');
const path = require('path');

const installScript = path.join(__dirname, 'install.sh');
const installScriptPs1 = path.join(__dirname, 'install.ps1');

if (process.platform === 'win32') {
  const shells = ['pwsh', 'powershell'];
  const shell = shells.find((candidate) => {
    try {
      execFileSync(candidate, ['-Version'], { stdio: 'ignore' });
      return true;
    } catch {
      return false;
    }
  });

  if (!shell) {
    console.error('PowerShell not found. Install PowerShell 5.1+ or run install.ps1 manually.');
    process.exit(1);
  }

  try {
    execFileSync(shell, ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', installScriptPs1], {
      stdio: 'inherit',
    });
    process.exit(0);
  } catch (error) {
    process.exit(error.status || 1);
  }
}

try {
  execFileSync('bash', [installScript], { stdio: 'inherit' });
} catch (error) {
  process.exit(error.status || 1);
}
