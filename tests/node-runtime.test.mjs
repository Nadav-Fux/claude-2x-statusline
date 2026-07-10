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
const ANSI_RE = /\x1b\[[0-9;]*m/g;

function stripAnsi(text) {
  return String(text || '').replace(ANSI_RE, '');
}

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

function writeCopilotUsageCache(home) {
  fs.writeFileSync(
    path.join(home, '.claude', 'statusline-usage-copilot.json'),
    JSON.stringify({
      cached_at: Date.now() / 1000,
      record: {
        provider: 'copilot',
        label: 'Copilot',
        available: true,
        display: 'bars',
        five_hour: { label: '2152 left', used_pct: 28, resets_at: 4_075_000_000 },
        plan: 'business',
        source: 'gh-billing',
        used: 848.0,
        cap: 3000,
        pool: 0,
        remaining: 2152.0,
        stale_seconds: 0,
      },
    }),
    'utf8',
  );
}

function writeAntigravityUsageCache(home) {
  // source: 'quota-summary' is required for getAntigravityUsage to return this
  // cache directly (skipping the antigravity-usage CLI subprocess entirely) —
  // see lib/usage_providers.js getAntigravityUsage step 1. Without it the
  // reader falls through to actually invoking the real `antigravity-usage`
  // binary if one happens to be installed on the host, which would make this
  // test non-hermetic.
  fs.writeFileSync(
    path.join(home, '.claude', 'statusline-usage-antigravity.json'),
    JSON.stringify({
      cached_at: Date.now() / 1000,
      record: {
        provider: 'antigravity',
        label: 'AGY',
        available: true,
        display: 'bars',
        five_hour: { label: '5h', used_pct: 10, resets_at: 4_076_000_000 },
        weekly: { label: 'wk', used_pct: 22, resets_at: 4_077_000_000 },
        plan: 'gemini',
        source: 'quota-summary',
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

const MULTI_CLI_PRESET = ['model', 'context', 'cost', 'effort', 'env', 'git_branch', 'git_dirty'];

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
  // multi-cli line 1 is now clean: model, context, cost, effort, LOCAL, git.
  for (const segment of ['gateway', 'sessions', 'jobs', 'churn', 'usage_credits', 'vim_mode', 'agent', 'workflows', 'tasks', 'banner']) {
    assert.equal(TIER_PRESETS['multi-cli'].includes(segment), false, `multi-cli must not include ${segment}`);
  }
  for (const segment of ['model', 'context', 'cost', 'effort', 'env', 'git_branch', 'git_dirty']) {
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

function writeUsageCacheWithPct(home, fhPct, sdPct) {
  fs.writeFileSync(
    path.join(home, '.claude', 'statusline-usage-cache.json'),
    JSON.stringify({
      five_hour: { utilization: fhPct, resets_at: '2099-01-01T01:00:00Z' },
      seven_day: { utilization: sdPct, resets_at: '2099-01-07T01:00:00Z' },
    }),
    'utf8',
  );
}

test('node rate-limit line applies window-aware color thresholds', () => {
  const home = makeHome();
  try {
    writeConfig(home, { tier: 'standard', schedule_url: '', schedule_cache_hours: 999 });
    writeCachedSchedule(home);
    // 48% is below BOTH the short (>=50) and long (>=45) yellow thresholds'
    // old/common ground -- pick a value that only trips the LONG threshold so
    // the two windows visibly diverge: 48 is GREEN under the short (5h) rule
    // (< 50) but YELLOW under the new long (weekly) rule (>= 45).
    writeUsageCacheWithPct(home, 48, 48);

    const result = runNodeEngine({
      home,
      input: JSON.stringify({
        model: { display_name: 'Sonnet 4.6' },
        context_window: { context_window_size: 200000, current_usage: { input_tokens: 1000 } },
        cost: { total_cost_usd: 1.23, total_duration_ms: 600000 },
        workspace: { current_dir: repoRoot },
      }),
      env: { STATUSLINE_DISABLE_TELEMETRY: '1' },
    });

    assert.equal(result.status, 0, result.stderr);
    // 5h (short window): still green at 48% -- unaffected by the new rule.
    assert.match(result.stdout, /\x1b\[32m 48%/);
    // weekly (long window): yellow at 48% -- the new, earlier threshold.
    assert.match(result.stdout, /\x1b\[33m 48%/);
    assert.doesNotMatch(result.stdout, /\x1b\[31m 48%/);
  } finally {
    fs.rmSync(home, { recursive: true, force: true });
  }
});

test('node rate-limit line reds out a long window earlier than a short one', () => {
  const home = makeHome();
  try {
    writeConfig(home, { tier: 'standard', schedule_url: '', schedule_cache_hours: 999 });
    writeCachedSchedule(home);
    // 76%: short (5h) rule keeps this YELLOW (< 80); long (weekly) rule turns
    // it RED (>= 75).
    writeUsageCacheWithPct(home, 76, 76);

    const result = runNodeEngine({
      home,
      input: JSON.stringify({
        model: { display_name: 'Sonnet 4.6' },
        context_window: { context_window_size: 200000, current_usage: { input_tokens: 1000 } },
        cost: { total_cost_usd: 1.23, total_duration_ms: 600000 },
        workspace: { current_dir: repoRoot },
      }),
      env: { STATUSLINE_DISABLE_TELEMETRY: '1' },
    });

    assert.equal(result.status, 0, result.stderr);
    assert.match(result.stdout, /\x1b\[33m 76%/); // 5h stays yellow
    assert.match(result.stdout, /\x1b\[31m 76%/); // weekly goes red
  } finally {
    fs.rmSync(home, { recursive: true, force: true });
  }
});

function writeToolUseTranscript(home, toolUseCount) {
  const transcriptPath = path.join(home, 'transcript.jsonl');
  const lines = [{ type: 'user', message: { content: 'hi' } }];
  for (let i = 0; i < toolUseCount; i++) {
    lines.push({
      type: 'assistant',
      message: { content: [{ type: 'tool_use', id: `t${i}`, name: 'Bash', input: {} }] },
    });
  }
  fs.writeFileSync(transcriptPath, lines.map(l => JSON.stringify(l)).join('\n') + '\n', 'utf8');
  return transcriptPath;
}

function cacheCurrentUsage(cacheReadPct) {
  // 10000 total cache tokens so seg_cache_hit's >=1000 floor is comfortably
  // cleared and hitPct == cacheReadPct exactly (10000 divides evenly).
  const total = 10000;
  const cacheRead = Math.round((cacheReadPct / 100) * total);
  return {
    input_tokens: 1000,
    cache_read_input_tokens: cacheRead,
    cache_creation_input_tokens: total - cacheRead,
  };
}

test('node session-quality line renders the tool-call counter from the transcript', () => {
  const home = makeHome();
  try {
    writeConfig(home, { tier: 'full', schedule_url: '', schedule_cache_hours: 999 });
    writeCachedSchedule(home);
    const transcriptPath = writeToolUseTranscript(home, 7);

    const result = runNodeEngine({
      home,
      input: JSON.stringify({
        session_id: 'sess-tool-count-7',
        transcript_path: transcriptPath,
        model: { display_name: 'Sonnet 4.6' },
        context_window: { context_window_size: 200000, current_usage: { input_tokens: 1000 } },
        cost: { total_cost_usd: 1.23, total_duration_ms: 600000 },
        workspace: { current_dir: repoRoot },
      }),
      env: { STATUSLINE_DISABLE_TELEMETRY: '1' },
    });

    assert.equal(result.status, 0, result.stderr);
    assert.match(stripAnsi(result.stdout), /⚒ 7/);
  } finally {
    fs.rmSync(home, { recursive: true, force: true });
  }
});

test('node tool-call counter renders 0 (not omitted) for a transcript with no tool_use', () => {
  const home = makeHome();
  try {
    writeConfig(home, { tier: 'full', schedule_url: '', schedule_cache_hours: 999 });
    writeCachedSchedule(home);
    const transcriptPath = writeToolUseTranscript(home, 0);

    const result = runNodeEngine({
      home,
      input: JSON.stringify({
        session_id: 'sess-tool-count-0',
        transcript_path: transcriptPath,
        model: { display_name: 'Sonnet 4.6' },
        context_window: { context_window_size: 200000, current_usage: { input_tokens: 1000 } },
        cost: { total_cost_usd: 1.23, total_duration_ms: 600000 },
        workspace: { current_dir: repoRoot },
      }),
      env: { STATUSLINE_DISABLE_TELEMETRY: '1' },
    });

    assert.equal(result.status, 0, result.stderr);
    assert.match(stripAnsi(result.stdout), /⚒ 0/);
  } finally {
    fs.rmSync(home, { recursive: true, force: true });
  }
});

test('node tool-call counter is omitted entirely when the transcript is missing', () => {
  const home = makeHome();
  try {
    writeConfig(home, { tier: 'full', schedule_url: '', schedule_cache_hours: 999 });
    writeCachedSchedule(home);

    const result = runNodeEngine({
      home,
      input: JSON.stringify({
        session_id: 'sess-tool-count-missing',
        transcript_path: path.join(home, 'does-not-exist.jsonl'),
        model: { display_name: 'Sonnet 4.6' },
        context_window: { context_window_size: 200000, current_usage: { input_tokens: 1000 } },
        cost: { total_cost_usd: 1.23, total_duration_ms: 600000 },
        workspace: { current_dir: repoRoot },
      }),
      env: { STATUSLINE_DISABLE_TELEMETRY: '1' },
    });

    assert.equal(result.status, 0, result.stderr);
    assert.doesNotMatch(stripAnsi(result.stdout), /⚒/);
  } finally {
    fs.rmSync(home, { recursive: true, force: true });
  }
});

test('node eff segment maps cache-reuse pct to dots, rounding half up', () => {
  const cases = [
    { pct: 0, dots: '○○○○○' },
    { pct: 49, dots: '●●○○○' },
    { pct: 50, dots: '●●●○○' }, // exact half rounds UP (3), not banker's-rounds-down (2)
    { pct: 100, dots: '●●●●●' },
  ];
  for (const { pct, dots } of cases) {
    const home = makeHome();
    try {
      writeConfig(home, { tier: 'full', schedule_url: '', schedule_cache_hours: 999 });
      writeCachedSchedule(home);

      const result = runNodeEngine({
        home,
        input: JSON.stringify({
          model: { display_name: 'Sonnet 4.6' },
          context_window: { context_window_size: 200000, current_usage: cacheCurrentUsage(pct) },
          cost: { total_cost_usd: 1.23, total_duration_ms: 600000 },
          workspace: { current_dir: repoRoot },
        }),
        env: { STATUSLINE_DISABLE_TELEMETRY: '1' },
      });

      assert.equal(result.status, 0, result.stderr);
      assert.match(stripAnsi(result.stdout), new RegExp(`eff ${dots}`), `pct=${pct}`);
    } finally {
      fs.rmSync(home, { recursive: true, force: true });
    }
  }
});

function writeCachedScheduleWithBanner(home) {
  const schedule = {
    v: 2,
    mode: 'normal',
    peak: { enabled: true, tz: 'UTC', days: [1, 2, 3, 4, 5], start: 5, end: 11 },
    banners: [{ text: 'PROMO ENDS SOON', expires: '2099-01-01', color: 'yellow' }],
    release: {},
    labels: { five_hour: 'Claude 5h', weekly: 'weekly' },
    features: { show_peak_segment: true, show_rate_limits: true, show_timeline: false },
  };
  fs.writeFileSync(path.join(home, '.claude', 'statusline-schedule.json'), JSON.stringify(schedule, null, 2), 'utf8');
}

test('node multi-cli tier has a clean line 1, Codex+GLM rows (no Droid) and a bottom banner', () => {
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
    writeCachedScheduleWithBanner(home);
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
    const plainLines = stripAnsi(result.stdout).split(/\r?\n/);

    // Line 1 is clean: no gateway badge, no sessions cockpit, no banner.
    const line1 = plainLines[0];
    assert.match(line1, /Sonnet 4\.6/);
    assert.doesNotMatch(line1, /via/);
    assert.doesNotMatch(line1, /sess/);
    assert.doesNotMatch(line1, /PROMO/);

    // The promo banner moves to the very last line, exactly once.
    assert.match(plainLines[plainLines.length - 1], /PROMO ENDS SOON/);
    assert.equal((result.stdout.match(/PROMO ENDS SOON/g) || []).length, 1);

    // Codex + GLM render; Droid is dropped from multi-cli.
    assert.match(result.stdout, /Codex/);
    assert.match(result.stdout, /GLM/);
    assert.doesNotMatch(result.stdout, /Droid/);

    const glmLine = plainLines.find(line => line.includes('GLM') && line.includes('tok'));
    const codexLine = plainLines.find(line => line.includes('Codex') && line.includes('7d'));
    assert.ok(glmLine, stripAnsi(result.stdout));
    assert.ok(codexLine, stripAnsi(result.stdout));
    assert.match(glmLine, /5h 3%/);
    assert.match(glmLine, /tok 9%/);
    assert.doesNotMatch(glmLine, /[\u25b0\u25b1]/);
    assert.match(codexLine, /[\u25b0\u25b1]/);
    // Reset is now an absolute end-time clock, not a duration; the weekly
    // window resets far out so it renders date + time.
    assert.match(codexLine, /\u27f3 \d+\/\d+ \d/);
  } finally {
    fs.rmSync(home, { recursive: true, force: true });
  }
});

test('node multi-cli GLM+Copilot combine into one bottom row after Codex and AGY', () => {
  const home = makeHome();
  try {
    writeConfig(home, {
      tier: 'multi-cli',
      schedule_url: '',
      schedule_cache_hours: 999,
      external_providers: {
        enabled: true,
        codex: { enabled: true },
        glm: { enabled: true, api_key: 'test-key' },
        antigravity: { enabled: true },
        copilot: { enabled: true },
        droid: { enabled: false },
      },
    });
    writeCachedSchedule(home);
    writeUsageCache(home);
    writeExternalUsageCaches(home);
    writeCopilotUsageCache(home);
    writeAntigravityUsageCache(home);

    const result = runNodeEngine({
      home,
      input: JSON.stringify({
        model: { display_name: 'Sonnet 4.6' },
        context_window: { context_window_size: 200000, current_usage: { input_tokens: 1000 } },
        cost: { total_cost_usd: 1.23, total_duration_ms: 600000 },
        workspace: { current_dir: repoRoot },
      }),
      env: { STATUSLINE_DISABLE_TELEMETRY: '1' },
    });

    assert.equal(result.status, 0, result.stderr);
    const plainLines = stripAnsi(result.stdout).split(/\r?\n/);

    const codexIdx = plainLines.findIndex(line => line.includes('Codex'));
    const agyIdx = plainLines.findIndex(line => line.includes('AGY'));
    const combinedIdx = plainLines.findIndex(line => line.includes('GLM') && line.includes('Copilot'));
    assert.ok(codexIdx >= 0 && agyIdx >= 0 && combinedIdx >= 0, stripAnsi(result.stdout));
    assert.ok(codexIdx < agyIdx && agyIdx < combinedIdx, stripAnsi(result.stdout));

    // Exactly one row carries GLM, and it's the same row that carries Copilot.
    assert.equal(plainLines.filter(line => line.includes('GLM') && line.includes('tok')).length, 1);
    assert.equal(plainLines.filter(line => line.includes('Copilot')).length, 1);

    const combinedLine = plainLines[combinedIdx];
    assert.ok(combinedLine.indexOf('GLM') < combinedLine.indexOf('Copilot'));
    assert.match(combinedLine, /5h 3%/);
    assert.match(combinedLine, /tok 9%/);
    assert.match(combinedLine, /2152 left 28%/);
    // Copilot renders COMPACT inside the combined row (no bar).
    assert.doesNotMatch(combinedLine, /[▰▱]/);
  } finally {
    fs.rmSync(home, { recursive: true, force: true });
  }
});

test('node multi-cli GLM-only renders alone compact in the bottom slot', () => {
  const home = makeHome();
  try {
    writeConfig(home, {
      tier: 'multi-cli',
      schedule_url: '',
      schedule_cache_hours: 999,
      external_providers: {
        enabled: true,
        codex: { enabled: false },
        glm: { enabled: true, api_key: 'test-key' },
        droid: { enabled: false },
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
      env: { STATUSLINE_DISABLE_TELEMETRY: '1' },
    });

    assert.equal(result.status, 0, result.stderr);
    const plainLines = stripAnsi(result.stdout).split(/\r?\n/);
    const glmLine = plainLines.find(line => line.includes('GLM') && line.includes('tok'));
    assert.ok(glmLine, stripAnsi(result.stdout));
    assert.doesNotMatch(glmLine, /Copilot/);
    assert.match(glmLine, /5h 3%/);
    assert.match(glmLine, /tok 9%/);
    assert.doesNotMatch(glmLine, /[▰▱]/);
  } finally {
    fs.rmSync(home, { recursive: true, force: true });
  }
});

test('node multi-cli Copilot-only renders alone with a bar in the bottom slot', () => {
  const home = makeHome();
  try {
    writeConfig(home, {
      tier: 'multi-cli',
      schedule_url: '',
      schedule_cache_hours: 999,
      external_providers: {
        enabled: true,
        codex: { enabled: false },
        glm: { enabled: false },
        copilot: { enabled: true },
        droid: { enabled: false },
      },
    });
    writeCachedSchedule(home);
    writeUsageCache(home);
    writeCopilotUsageCache(home);

    const result = runNodeEngine({
      home,
      input: JSON.stringify({
        model: { display_name: 'Sonnet 4.6' },
        context_window: { context_window_size: 200000, current_usage: { input_tokens: 1000 } },
        cost: { total_cost_usd: 1.23, total_duration_ms: 600000 },
        workspace: { current_dir: repoRoot },
      }),
      env: { STATUSLINE_DISABLE_TELEMETRY: '1' },
    });

    assert.equal(result.status, 0, result.stderr);
    const plainLines = stripAnsi(result.stdout).split(/\r?\n/);
    const copilotLine = plainLines.find(line => line.includes('Copilot'));
    assert.ok(copilotLine, stripAnsi(result.stdout));
    assert.doesNotMatch(copilotLine, /GLM/);
    assert.match(copilotLine, /2152 left/);
    assert.match(copilotLine, /[▰▱]/);
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
