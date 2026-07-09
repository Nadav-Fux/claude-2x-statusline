import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const providers = require(path.join(repoRoot, 'lib', 'usage_providers.js'));
const fixtures = path.join(repoRoot, 'tests', 'fixtures');

test('codex fixture maps rate limits', () => {
  const line = fs.readFileSync(path.join(fixtures, 'codex_rollout_token_count.jsonl'), 'utf8').trim();

  const record = providers.parseCodexTokenCountLine(line);

  assert.equal(record.available, true);
  assert.equal(record.five_hour.used_pct, 47);
  assert.equal(record.five_hour.resets_at, 1782536836);
  assert.equal(record.five_hour.label, '5h');
  assert.equal(record.weekly.used_pct, 10);
  assert.equal(record.weekly.resets_at, 1783029435);
  assert.equal(record.weekly.label, '7d');
  assert.equal(record.plan, 'team');
});

test('codex new-schema 30d single window', () => {
  // New Codex CLI schema: primary is a 30-day window, secondary is null, and the
  // wrapper carries limit_id/credits/individual_limit/rate_limit_reached_type.
  const line = fs.readFileSync(path.join(fixtures, 'codex_rollout_token_count_30d.jsonl'), 'utf8').trim();

  const record = providers.parseCodexTokenCountLine(line);

  assert.equal(record.available, true);
  assert.equal(record.five_hour.used_pct, 6);
  assert.equal(record.five_hour.resets_at, 1786214766);
  assert.equal(record.five_hour.label, '30d'); // 43200 minutes -> honest 30d label
  assert.equal(record.weekly, null); // secondary null -> no weekly window
  assert.equal(record.plan, 'free');

  const row = providers.formatProviderRowParts(record, 1_000, { labelWidth: 5 });
  const windowParts = row.parts.filter(part => part.kind === 'window');
  assert.equal(windowParts.length, 1);
  assert.equal(windowParts[0].label, '30d');
  assert.equal(windowParts[0].pct, 6);
  assert.match(row.text, /30d/);
  assert.doesNotMatch(row.text, /7d/);
});

test('codex window label maps minutes to honest labels', () => {
  assert.equal(providers.codexWindowLabel(300, '5h'), '5h');
  assert.equal(providers.codexWindowLabel(10080, '7d'), '7d');
  assert.equal(providers.codexWindowLabel(43200, '7d'), '30d');
  assert.equal(providers.codexWindowLabel(720, '5h'), '12h');
  assert.equal(providers.codexWindowLabel(null, '7d'), '7d');
  assert.equal(providers.codexWindowLabel('bad', '5h'), '5h');
});

test('glm fixture maps quota limits', () => {
  const data = JSON.parse(fs.readFileSync(path.join(fixtures, 'glm_quota_response.json'), 'utf8'));

  const record = providers.parseGlmQuotaResponse(data);

  assert.equal(record.available, true);
  assert.equal(record.five_hour.used_pct, 0);
  assert.ok(Math.abs(record.five_hour.resets_at - 1783532012) <= 1);
  assert.equal(record.five_hour.label, '5h');
  assert.equal(record.weekly.used_pct, 99);
  assert.ok(Math.abs(record.weekly.resets_at - 1782782126) <= 1);
  assert.equal(record.weekly.label, 'tok');
  assert.equal(record.plan, 'lite');
  assert.equal(record.display, 'compact');
  assert.deepEqual(record.metrics.map(metric => [metric.label, metric.used_pct]), [['5h', 0], ['tok', 99]]);

  const row = providers.formatProviderRowParts(record, 1_000);
  assert.equal(row.display, 'compact');
  assert.equal(row.parts.find(part => part.kind === 'metric' && part.pct === 99).label, 'tok');
  assert.match(row.text, /5h 0%/);
  assert.match(row.text, /tok 99%/);
  assert.doesNotMatch(row.text, /[\u25b0\u25b1]/);
});

test('compact provider row parts render metrics without bars while bars records keep bars', () => {
  const compact = providers.formatProviderRowParts({
    provider: 'glm',
    label: 'GLM',
    available: true,
    display: 'compact',
    metrics: [
      { label: '5h', used_pct: 0, resets_at: 1_000 + 39 * 60 },
      { label: 'tok', used_pct: 8, resets_at: 1_000 + 90 * 60 },
    ],
    five_hour: { used_pct: 0, resets_at: 1_000 + 39 * 60, label: '5h' },
    weekly: { used_pct: 8, resets_at: 1_000 + 90 * 60, label: 'tok' },
    plan: 'lite',
    tokens: null,
    stale_seconds: 0,
  }, 1_000);

  assert.match(compact.text, /GLM lite  5h 0% \u00b7 tok 8% \u27f3 39m/);
  assert.doesNotMatch(compact.text, /[\u25b0\u25b1]/);

  const bars = providers.formatProviderRowParts({
    provider: 'codex',
    label: 'Codex',
    available: true,
    display: 'bars',
    five_hour: { used_pct: 60, resets_at: null, label: '5h' },
    weekly: null,
    plan: null,
    tokens: null,
    stale_seconds: 0,
  }, 1_000);

  assert.match(bars.text, /[\u25b0\u25b1]/);
});

test('provider row parts include reset countdown and stale marker', () => {
  const row = providers.formatProviderRowParts({
    provider: 'codex',
    label: 'Codex',
    available: true,
    five_hour: { used_pct: 60, resets_at: 1_000 + 133 * 60 },
    weekly: null,
    plan: 'team',
    tokens: null,
    stale_seconds: 1_200,
  }, 1_000, { labelWidth: 7 });

  assert.equal(row.parts[0].label, 'Codex  ');
  assert.equal(row.parts[1].resetText, '\u27f3 2h 13m');
  assert.equal(row.staleText, ' \u00b7stale');
});

test('provider row parts prefer per-window labels', () => {
  const row = providers.formatProviderRowParts({
    provider: 'antigravity',
    label: 'Antigravity',
    available: true,
    five_hour: { used_pct: 40, resets_at: null, label: '5h' },
    weekly: { used_pct: 12, resets_at: null, label: 'wk' },
    plan: null,
    tokens: null,
    stale_seconds: 0,
  }, 1_000);

  assert.equal(row.parts[1].label, '5h');
  assert.equal(row.parts[2].label, 'wk');
});

test('antigravity parser maps sprint and weekly windows', () => {
  const record = providers.parseAntigravityItemTable([
    {
      key: 'antigravity.usage',
      value: '{"sprint":{"usedPercent":40,"resetsAt":1790000000},"weekly":{"usedPercent":12}}',
    },
  ]);

  assert.equal(record.available, true);
  assert.equal(record.five_hour.used_pct, 40);
  assert.equal(record.five_hour.resets_at, 1790000000);
  assert.equal(record.five_hour.label, '5h');
  assert.equal(record.weekly.used_pct, 12);
  assert.equal(record.weekly.resets_at, null);
  assert.equal(record.weekly.label, 'wk');
});

test('antigravity model parser maps model-group metrics', () => {
  const metrics = providers.parseAntigravityModels({
    models: {
      'gemini-3-flash': { usedPercent: 23 },
      'gemini-3-pro-low': { usedPercent: 67 },
      'claude-opus': { usedPercent: 41 },
    },
  });

  assert.deepEqual(metrics.map(metric => [metric.label, metric.used_pct]), [['Flash', 23], ['Pro', 67], ['Opus', 41]]);
  assert.equal(providers.parseAntigravityModels({ hello: 'world' }), null);

  const record = providers.parseAntigravityItemTable([
    {
      key: 'antigravity.models',
      value: JSON.stringify({
        models: {
          'gemini-3-flash': { usedPercent: 23 },
          'gemini-3-pro-low': { usedPercent: 67 },
          'claude-opus': { usedPercent: 41 },
        },
      }),
    },
  ]);
  assert.equal(record.available, true);
  assert.equal(record.label, 'AGY');
  assert.equal(record.display, 'compact');
  assert.deepEqual(record.metrics.map(metric => [metric.label, metric.used_pct]), [['Flash', 23], ['Pro', 67], ['Opus', 41]]);
});

test('antigravity parser returns unavailable for junk rows', () => {
  const record = providers.parseAntigravityItemTable([
    { key: 'antigravity.usage', value: 'not json' },
    { key: 'other', value: '{"hello":"world"}' },
  ]);

  assert.equal(record.provider, 'antigravity');
  assert.equal(record.available, false);
});

test('provider row parts omit past reset countdown', () => {
  const row = providers.formatProviderRowParts({
    provider: 'glm',
    label: 'GLM',
    available: true,
    five_hour: { used_pct: 0, resets_at: 999 },
    weekly: null,
    plan: 'lite',
    tokens: null,
    stale_seconds: 0,
  }, 1_000);

  assert.equal(row.parts[1].resetText, '');
  assert.equal(row.staleText, '');
});

test('antigravity dual model rows render two compact rows without bars', () => {
  const record = {
    provider: 'antigravity',
    label: 'AGY',
    available: true,
    display: 'compact',
    metrics_5h: [
      { label: 'Opus', used_pct: 12, resets_at: 4_071_000_000 },
      { label: 'Pro', used_pct: 45, resets_at: 4_071_000_000 },
      { label: 'Flash', used_pct: 7, resets_at: 4_071_000_000 },
    ],
    metrics_weekly: [
      { label: 'Opus', used_pct: 30, resets_at: 4_072_000_000 },
      { label: 'Pro', used_pct: 60, resets_at: 4_072_000_000 },
      { label: 'Flash', used_pct: 22, resets_at: 4_072_000_000 },
    ],
    stale_seconds: 0,
  };

  // Fixed clock formatter so the two-row layout is deterministic across hosts.
  const formatClock = (epoch, style) => (style === 'time' ? '12:00pm' : '4/7 5:00am');

  const row = providers.formatProviderRowParts(record, 1_000, { formatClock });

  assert.ok(row);
  assert.equal(row.display, 'agy_dual');
  assert.equal(row.subRows.length, 2);

  const [fiveHour, weekly] = row.text.split('\n');
  assert.ok(fiveHour.startsWith('AGY 5h'));
  assert.match(fiveHour, /Opus 12%/);
  assert.match(fiveHour, /Pro 45%/);
  assert.match(fiveHour, /Flash 7%/);
  assert.match(fiveHour, /⟳ 12:00pm/);

  assert.ok(weekly.startsWith('AGY 7d'));
  assert.match(weekly, /Opus 30%/);
  assert.match(weekly, /Pro 60%/);
  assert.match(weekly, /Flash 22%/);
  assert.match(weekly, /⟳ 4\/7 5:00am/);

  assert.doesNotMatch(row.text, /[▰▱]/);
});

test('providers gracefully return unavailable without home data', async () => {
  const home = fs.mkdtempSync(path.join(os.tmpdir(), 'statusline-providers-'));
  const oldHome = process.env.HOME;
  const oldUserProfile = process.env.USERPROFILE;
  const oldZai = process.env.ZAI_API_KEY;
  const oldZhipu = process.env.ZHIPU_API_KEY;
  try {
    process.env.HOME = home;
    process.env.USERPROFILE = home;
    delete process.env.ZAI_API_KEY;
    delete process.env.ZHIPU_API_KEY;

    for (const name of ['codex', 'glm', 'droid', 'antigravity']) {
      const record = await providers.getProviderUsage(name, {});
      assert.equal(record.provider, name);
      assert.equal(record.available, false);
    }
  } finally {
    if (oldHome == null) delete process.env.HOME; else process.env.HOME = oldHome;
    if (oldUserProfile == null) delete process.env.USERPROFILE; else process.env.USERPROFILE = oldUserProfile;
    if (oldZai == null) delete process.env.ZAI_API_KEY; else process.env.ZAI_API_KEY = oldZai;
    if (oldZhipu == null) delete process.env.ZHIPU_API_KEY; else process.env.ZHIPU_API_KEY = oldZhipu;
    fs.rmSync(home, { recursive: true, force: true });
  }
});
