import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const nodeEnginePath = path.join(repoRoot, 'engines', 'node-engine.js');
const narratorHookPath = path.join(repoRoot, 'hooks', 'narrator-session-start.sh');
const narratorCliPath = path.join(repoRoot, 'narrator', 'cli.js');
const { parseGitShortstat, TIER_PRESETS } = require(nodeEnginePath);

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

function writeConfig(home, config) {
  fs.writeFileSync(
    path.join(home, '.claude', 'statusline-config.json'),
    JSON.stringify(config, null, 2),
    'utf8',
  );
}

function writeUsageCache(home) {
  fs.writeFileSync(
    path.join(home, '.claude', 'statusline-usage-cache.json'),
    JSON.stringify({
      five_hour: { utilization: 42, resets_at: '2099-01-01T01:00:00Z' },
      seven_day: { utilization: 24, resets_at: '2099-01-07T01:00:00Z' },
    }),
    'utf8',
  );
}

function writeExternalUsageCaches(home) {
  const claudeDir = path.join(home, '.claude');
  fs.writeFileSync(
    path.join(claudeDir, 'statusline-usage-codex.json'),
    JSON.stringify({
      cached_at: Date.now() / 1000,
      record: {
        provider: 'codex',
        label: 'Codex',
        available: true,
        five_hour: { used_pct: 12, resets_at: 4_071_000_000, label: '5h' },
        weekly: { used_pct: 34, resets_at: 4_072_000_000, label: '7d' },
        plan: 'team',
        tokens: null,
        stale_seconds: 0,
      },
    }),
    'utf8',
  );
  fs.writeFileSync(
    path.join(claudeDir, 'statusline-usage-glm.json'),
    JSON.stringify({
      cached_at: Date.now() / 1000,
      response: {
        data: {
          level: 'lite',
          limits: [
            { type: 'TIME_LIMIT', percentage: 3, nextResetTime: 4_071_000_000_000 },
            { type: 'TOKENS_LIMIT', percentage: 9, nextResetTime: 4_072_000_000_000 },
          ],
        },
      },
    }),
    'utf8',
  );
  fs.writeFileSync(
    path.join(claudeDir, 'statusline-usage-droid.json'),
    JSON.stringify({
      cached_at: Date.now() / 1000,
      record: {
        provider: 'droid',
        label: 'Droid',
        available: true,
        five_hour: null,
        weekly: null,
        plan: null,
        tokens: { total: 12345 },
        stale_seconds: 0,
      },
    }),
    'utf8',
  );
}

function runNodeEngine({ input, home, env = {}, args = [] }) {
  return spawnSync(process.execPath, [nodeEnginePath, ...args], {
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

const REGULAR_TIER_PRESETS = {
  minimal: ['model', 'context', 'workflows', 'tasks', 'git_branch', 'git_dirty', 'rate_limits', 'effort', 'env'],
  standard: ['model', 'context', 'vim_mode', 'agent', 'workflows', 'tasks', 'git_branch', 'git_dirty', 'cost', 'effort', 'env'],
  full: ['model', 'context', 'vim_mode', 'agent', 'workflows', 'tasks', 'git_branch', 'git_dirty', 'cost', 'usage_credits', 'effort', 'env'],
};

const MULTI_CLI_PRESET = ['model', 'gateway', 'context', 'vim_mode', 'agent', 'sessions', 'jobs', 'workflows', 'tasks', 'git_branch', 'git_dirty', 'cost', 'usage_credits', 'churn', 'effort', 'env'];

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

test('node tier presets keep regular tiers clean and add multi-cli cockpit', () => {
  assert.deepEqual(TIER_PRESETS.minimal, REGULAR_TIER_PRESETS.minimal);
  assert.deepEqual(TIER_PRESETS.standard, REGULAR_TIER_PRESETS.standard);
  assert.deepEqual(TIER_PRESETS.full, REGULAR_TIER_PRESETS.full);
  assert.deepEqual(TIER_PRESETS['multi-cli'], MULTI_CLI_PRESET);

  for (const tier of ['minimal', 'standard', 'full']) {
    for (const segment of ['gateway', 'sessions', 'jobs', 'churn']) {
      assert.equal(TIER_PRESETS[tier].includes(segment), false, `${tier} must not include ${segment}`);
    }
  }
  for (const segment of ['gateway', 'sessions', 'jobs', 'churn', 'usage_credits']) {
    assert.equal(TIER_PRESETS['multi-cli'].includes(segment), true, `multi-cli must include ${segment}`);
  }
});

test('node full tier ignores foreign gateway and keeps Claude rate-limit bars', () => {
  const home = makeHome();
  try {
    writeConfig(home, { tier: 'full', schedule_url: '', schedule_cache_hours: 999 });
    writeCachedSchedule(home);
    writeUsageCache(home);

    const result = runNodeEngine({
      home,
      input: JSON.stringify({
        model: { display_name: 'Sonnet 4.6' },
        context_window: { context_window_size: 200000, current_usage: { input_tokens: 1000 } },
        cost: { total_cost_usd: 1.23, total_duration_ms: 600000 },
        workspace: { current_dir: repoRoot },
      }),
      env: {
        ANTHROPIC_BASE_URL: 'https://api.z.ai/api/anthropic',
        STATUSLINE_DISABLE_TELEMETRY: '1',
      },
    });

    assert.equal(result.status, 0, result.stderr);
    assert.doesNotMatch(result.stdout, /via z\.ai/);
    assert.doesNotMatch(result.stdout, /rate limits n\/a on gateway/);
    assert.match(result.stdout, /weekly/);
    assert.match(result.stdout, /\$1\.23/);
  } finally {
    fs.rmSync(home, { recursive: true, force: true });
  }
});

test('node multi-cli tier shows gateway badge and forced external usage rows', () => {
  const home = makeHome();
  try {
    writeConfig(home, {
      tier: 'multi-cli',
      schedule_url: '',
      schedule_cache_hours: 999,
      external_providers: {
        enabled: false,
        glm: { api_key: 'test-key' },
      },
    });
    writeCachedSchedule(home);
    writeUsageCache(home);
    writeExternalUsageCaches(home);

    const result = runNodeEngine({
      home,
      input: JSON.stringify({
        model: { display_name: 'Sonnet 4.6' },
        context_window: { context_window_size: 200000, current_usage: { input_tokens: 1000 } },
        cost: { total_cost_usd: 1.23, total_duration_ms: 600000 },
        workspace: { current_dir: repoRoot },
      }),
      env: {
        ANTHROPIC_BASE_URL: 'https://api.z.ai/api/anthropic',
        STATUSLINE_DISABLE_TELEMETRY: '1',
      },
    });

    assert.equal(result.status, 0, result.stderr);
    assert.match(result.stdout, /via z\.ai \(GLM\)/);
    assert.match(result.stdout, /Codex/);
    assert.match(result.stdout, /GLM/);
    assert.match(result.stdout, /Droid/);
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

test('parseGitShortstat parses empty and partial shortstat output', () => {
  assert.deepEqual(parseGitShortstat(''), { insertions: 0, deletions: 0, files: 0 });
  assert.deepEqual(
    parseGitShortstat(' 7 files changed, 420 insertions(+), 110 deletions(-)'),
    { insertions: 420, deletions: 110, files: 7 },
  );
  assert.deepEqual(
    parseGitShortstat(' 1 file changed, 3 insertions(+)'),
    { insertions: 3, deletions: 0, files: 1 },
  );
  assert.deepEqual(
    parseGitShortstat(' 2 files changed, 9 deletions(-)'),
    { insertions: 0, deletions: 9, files: 2 },
  );
});

test('node narrator output is framed as statusline text', () => {
  const home = makeHome();

  try {
    fs.writeFileSync(
      path.join(home, '.claude', 'statusline-usage-cache.json'),
      JSON.stringify({ five_hour: { utilization: 85 }, seven_day: { utilization: 10 } }),
    );
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
