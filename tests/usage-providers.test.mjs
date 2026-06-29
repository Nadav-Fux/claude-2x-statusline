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

  const row = providers.formatProviderRowParts(record, 1_000);
  assert.equal(row.parts.find(part => part.kind === 'window' && part.pct === 99).label, 'tok');
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
