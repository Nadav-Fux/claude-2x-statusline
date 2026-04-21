import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const nodeEnginePath = path.join(repoRoot, 'engines', 'node-engine.js');
const narratorHookPath = path.join(repoRoot, 'hooks', 'narrator-session-start.sh');
const narratorCliPath = path.join(repoRoot, 'narrator', 'cli.js');

function makeHome() {
  const home = fs.mkdtempSync(path.join(os.tmpdir(), 'statusline-node-'));
  fs.mkdirSync(path.join(home, '.claude'), { recursive: true });
  return home;
}

function writeCachedSchedule(home) {
  const schedule = {
    v: 2,
    mode: 'normal',
    peak: {
      enabled: true,
      tz: 'America/Los_Angeles',
      days: [1, 2, 3, 4, 5],
      start: 5,
      end: 11,
      label_peak: 'Peak',
      label_offpeak: 'Off-Peak',
    },
    banner: { text: '', expires: '', color: 'yellow' },
    release: {},
    features: { show_peak_segment: true, show_rate_limits: false, show_timeline: false },
  };
  fs.writeFileSync(
    path.join(home, '.claude', 'statusline-schedule.json'),
    JSON.stringify(schedule, null, 2),
    'utf8',
  );
}

function runNodeEngine({ input, home, env = {} }) {
  return spawnSync(process.execPath, [nodeEnginePath], {
    cwd: repoRoot,
    input,
    encoding: 'utf8',
    env: {
      ...process.env,
      HOME: home,
      USERPROFILE: home,
      ...env,
    },
  });
}

function findGitBash() {
  const candidates = [
    'C:/Program Files/Git/bin/bash.exe',
    'C:/Program Files/Git/usr/bin/bash.exe',
    'C:/Program Files (x86)/Git/bin/bash.exe',
    'C:/Program Files (x86)/Git/usr/bin/bash.exe',
  ];
  return candidates.find(candidate => fs.existsSync(candidate)) || null;
}

function resolveGitRoot(bashPath) {
  let root = path.dirname(bashPath);
  if (path.basename(root).toLowerCase() === 'bin') {
    root = path.dirname(root);
  }
  if (path.basename(root).toLowerCase() === 'usr') {
    root = path.dirname(root);
  }
  return root;
}

test('node engine renders vim and agent/worktree segments in standard preset', () => {
  const home = makeHome();

  try {
    writeCachedSchedule(home);

    const input = JSON.stringify({
      model: { display_name: 'Sonnet 4.6' },
      context_window: {
        context_window_size: 1_000_000,
        current_usage: {
          input_tokens: 400_000,
          output_tokens: 10_000,
          cache_creation_input_tokens: 0,
          cache_read_input_tokens: 0,
        },
      },
      cost: { total_cost_usd: 1.23, total_duration_ms: 600_000 },
      vim: { mode: 'normal' },
      agent: { name: 'Explore' },
      worktree: { name: 'wt-demo' },
      workspace: { current_dir: repoRoot },
      version: '2.2.0',
    });

    const result = runNodeEngine({ input, home });

    assert.equal(result.status, 0, result.stderr);
    assert.match(result.stdout, /NORMAL/);
    assert.match(result.stdout, /Explore/);
    assert.match(result.stdout, /wt:wt-demo/);
  } finally {
    fs.rmSync(home, { recursive: true, force: true });
  }
});

test('node engine skips heartbeat when STATUSLINE_DISABLE_TELEMETRY is set', () => {
  const home = makeHome();

  try {
    writeCachedSchedule(home);

    const result = runNodeEngine({
      input: JSON.stringify({ workspace: { current_dir: repoRoot } }),
      home,
      env: { STATUSLINE_DISABLE_TELEMETRY: '1' },
    });

    assert.equal(result.status, 0, result.stderr);
    assert.equal(fs.existsSync(path.join(home, '.claude', '.statusline-heartbeat')), false);
    assert.equal(fs.existsSync(path.join(home, '.claude', '.statusline-telemetry-id')), false);
  } finally {
    fs.rmSync(home, { recursive: true, force: true });
  }
});

test('node narrator output is framed as statusline text', () => {
  const home = makeHome();

  try {
    const result = spawnSync(process.execPath, [narratorCliPath, 'session_start'], {
      cwd: repoRoot,
      encoding: 'utf8',
      env: {
        ...process.env,
        HOME: home,
        USERPROFILE: home,
        LANG: 'en_US.UTF-8',
        STATUSLINE_NARRATOR_ENABLED: '1',
        STATUSLINE_NARRATOR_HAIKU: '0',
      },
    });

    assert.equal(result.status, 0, result.stderr);
    assert.match(result.stdout, /^\/\/\/\/ Statusline note \/\/\/\//);
    const bodyLines = result.stdout.trim().split(/\r?\n/).slice(1);
    assert.ok(bodyLines.length >= 1, result.stdout);
    assert.ok(bodyLines.every(line => line.startsWith('//// -> ') && line.endsWith(' ////')), result.stdout);
  } finally {
    fs.rmSync(home, { recursive: true, force: true });
  }
});

test('windows narrator hook falls back to Node when Python is unavailable', { skip: process.platform !== 'win32' }, t => {
  const bashPath = findGitBash();
  if (!bashPath) {
    t.skip('Git Bash not installed');
    return;
  }

  const home = makeHome();

  try {
    const gitRoot = resolveGitRoot(bashPath);
    const envPath = [
      path.join(gitRoot, 'usr', 'bin'),
      path.join(gitRoot, 'bin'),
      path.dirname(process.execPath),
    ].join(path.delimiter);

    const result = spawnSync(bashPath, [narratorHookPath], {
      cwd: repoRoot,
      encoding: 'utf8',
      env: {
        ...process.env,
        HOME: home,
        USERPROFILE: home,
        PATH: envPath,
        STATUSLINE_NARRATOR_ENABLED: '0',
      },
    });

    assert.equal(result.status, 0, result.stderr || result.stdout);
    assert.equal(result.stderr, '');
  } finally {
    fs.rmSync(home, { recursive: true, force: true });
  }
});