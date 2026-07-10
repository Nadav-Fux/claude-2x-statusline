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

function installCodexRollouts(home, entries) {
  const base = path.join(home, '.codex', 'sessions', '2026', '07', '09');
  fs.mkdirSync(base, { recursive: true });
  for (const [name, fixture, mtime] of entries) {
    const dest = path.join(base, `rollout-${name}.jsonl`);
    fs.writeFileSync(dest, fs.readFileSync(path.join(fixtures, fixture), 'utf8'));
    fs.utimesSync(dest, mtime, mtime);
  }
}

function withCodexHome(entries, fn) {
  const home = fs.mkdtempSync(path.join(os.tmpdir(), 'statusline-codex-'));
  const oldHome = process.env.HOME;
  const oldUserProfile = process.env.USERPROFILE;
  try {
    process.env.HOME = home;
    process.env.USERPROFILE = home;
    installCodexRollouts(home, entries);
    return fn();
  } finally {
    if (oldHome == null) delete process.env.HOME; else process.env.HOME = oldHome;
    if (oldUserProfile == null) delete process.env.USERPROFILE; else process.env.USERPROFILE = oldUserProfile;
    fs.rmSync(home, { recursive: true, force: true });
  }
}

test('codex prefers paid plan over newer free', () => {
  // Newest rollout is a FREE account (30d 6%); an older one is the paid TEAM
  // account (5h 100%, weekly 84%). Default config must surface the paid limits.
  const now = Date.now() / 1000;
  const record = withCodexHome(
    [
      ['team', 'codex_rollout_team_snapshot.jsonl', now - 3600],
      ['free', 'codex_rollout_token_count_30d.jsonl', now - 60],
    ],
    () => providers.getCodexUsage({}),
  );

  assert.equal(record.available, true);
  assert.equal(record.plan, 'team');
  assert.equal(record.five_hour.used_pct, 100);
  assert.equal(record.five_hour.label, '5h');
  assert.equal(record.weekly.used_pct, 84);
  assert.equal(record.weekly.label, '7d');
  // stale reflects the SELECTED (team) snapshot's file age, not the newest file.
  assert.ok(record.stale_seconds >= 3600);

  // Default config does NOT surface all_plans: one Codex subscription, one row.
  assert.equal(record.all_plans, undefined);

  // The row renders a single line for the selected (team) plan.
  const row = providers.formatProviderRowParts(record, now, { labelWidth: 5 });
  assert.equal(row.subRows, undefined);
  assert.match(row.text, /team/);
  assert.match(row.text, /5h/);
  assert.match(row.text, /100%/);
  assert.match(row.text, /7d/);
  assert.match(row.text, /84%/);
});

test('codex windowed snapshot beats newer tokens-only same plan', () => {
  // A resumed/idle session can leave a team rollout with a fresher mtime whose
  // last event is tokens-only (rate_limits present but primary/secondary null).
  // The scan must upgrade that placeholder with the older WINDOWED team
  // snapshot instead of rendering a bar-less row.
  const now = Date.now() / 1000;
  const record = withCodexHome(
    [
      ['free', 'codex_rollout_token_count_30d.jsonl', now - 60],
      ['team-idle', 'codex_rollout_team_tokens_only.jsonl', now - 600],
      ['team-real', 'codex_rollout_team_snapshot.jsonl', now - 7200],
    ],
    () => providers.getCodexUsage({}),
  );

  assert.equal(record.plan, 'team');
  assert.equal(record.five_hour.used_pct, 100);
  assert.equal(record.weekly.used_pct, 84);
  // stale reflects the windowed snapshot actually selected.
  assert.ok(record.stale_seconds >= 7200);
});

test('codex plan pin selects free', () => {
  const now = Date.now() / 1000;
  const record = withCodexHome(
    [
      ['team', 'codex_rollout_team_snapshot.jsonl', now - 60],
      ['free', 'codex_rollout_token_count_30d.jsonl', now - 3600],
    ],
    () => providers.getCodexUsage({ external_providers: { codex: { plan: 'free' } } }),
  );

  assert.equal(record.plan, 'free');
  assert.equal(record.five_hour.used_pct, 6);
  assert.equal(record.five_hour.label, '30d');
  assert.equal(record.weekly, null);
  // Default config (show_all_plans unset) does NOT surface all_plans.
  assert.equal(record.all_plans, undefined);
});

test('codex all_plans ages out stale team', () => {
  // The owner switched off team >7 days ago (stale); free is current. The stale
  // team ages out of all_plans and — no fresh paid plan left — selection falls
  // back through the unchanged rules to the newest overall (free).
  // show_all_plans is opted in so all_plans is still populated for this check.
  const now = Date.now() / 1000;
  const record = withCodexHome(
    [
      ['team', 'codex_rollout_team_snapshot.jsonl', now - 8 * 86400],
      ['free', 'codex_rollout_token_count_30d.jsonl', now - 60],
    ],
    () => providers.getCodexUsage({ external_providers: { codex: { show_all_plans: true } } }),
  );

  assert.equal(record.plan, 'free');
  assert.equal(record.five_hour.label, '30d');
  assert.deepEqual(record.all_plans.map(p => p.plan), ['free']);
});

test('codex show_all_plans opt-in renders one row per plan', () => {
  // Interleaved free+team fixtures with show_all_plans explicitly opted in: the
  // record carries both plans, and the rendered row fans out to two sub-rows
  // (team+5h, free+30d) — the opt-in multi-plan path.
  const now = Date.now() / 1000;
  const record = withCodexHome(
    [
      ['team', 'codex_rollout_team_snapshot.jsonl', now - 3600],
      ['free', 'codex_rollout_token_count_30d.jsonl', now - 60],
    ],
    () => providers.getCodexUsage({ external_providers: { codex: { show_all_plans: true } } }),
  );

  assert.deepEqual(record.all_plans.map(p => p.plan), ['team', 'free']);

  const row = providers.formatProviderRowParts(record, now, { labelWidth: 5 });
  const subTexts = row.subRows.map(sub => sub.text);
  assert.equal(subTexts.length, 2);
  assert.match(subTexts[0], /team/);
  assert.match(subTexts[0], /5h/);
  assert.match(subTexts[1], /free/);
  assert.match(subTexts[1], /30d/);
});

test('codex all_plans renders one row per plan', () => {
  // Engine-level seam: formatProviderRowParts on a record carrying all_plans of
  // 2 yields two rendered rows (subRows) — team (5h) then free (30d).
  const team = providers.parseCodexTokenCountLine(
    fs.readFileSync(path.join(fixtures, 'codex_rollout_team_snapshot.jsonl'), 'utf8').trim(),
  );
  const free = providers.parseCodexTokenCountLine(
    fs.readFileSync(path.join(fixtures, 'codex_rollout_token_count_30d.jsonl'), 'utf8').trim(),
  );
  const record = { ...team, all_plans: [team, free] };

  const row = providers.formatProviderRowParts(record, 1_000, { labelWidth: 5 });
  const texts = row.subRows.map(sub => sub.text);
  assert.equal(texts.length, 2);
  assert.match(texts[0], /team/);
  assert.match(texts[0], /5h/);
  assert.match(texts[1], /free/);
  assert.match(texts[1], /30d/);
  // Absent all_plans still renders the single record as one row (old caches).
  const single = providers.formatProviderRowParts(team, 1_000, { labelWidth: 5 });
  assert.equal(single.subRows, undefined);
  assert.match(single.text, /team/);
  assert.match(single.text, /5h/);
});

test('codex only-free selected unchanged', () => {
  const now = Date.now() / 1000;
  const record = withCodexHome(
    [['free', 'codex_rollout_token_count_30d.jsonl', now - 120]],
    () => providers.getCodexUsage({}),
  );

  assert.equal(record.plan, 'free');
  assert.equal(record.five_hour.used_pct, 6);
  assert.equal(record.five_hour.label, '30d');
  assert.equal(record.weekly, null);
});

test('healCodexRecord zeroes an elapsed window', () => {
  // Direct unit test of the healing helper: an elapsed five_hour window (its
  // resets_at is in the past) is provably reset — no newer rollout for this
  // plan exists, so recorded usage since the reset is zero. The still-future
  // weekly window is untouched.
  const now = 1_000_000;
  const record = {
    provider: 'codex',
    available: true,
    five_hour: { used_pct: 100, resets_at: now - 100, label: '5h' },
    weekly: { used_pct: 84, resets_at: now + 500_000, label: '7d' },
    plan: 'team',
  };

  const healed = providers.healCodexRecord(record, now);

  assert.deepEqual(healed.five_hour, { used_pct: 0, resets_at: null, label: '5h' });
  assert.deepEqual(healed.weekly, { used_pct: 84, resets_at: now + 500_000, label: '7d' });
  // The helper does not mutate its input.
  assert.equal(record.five_hour.used_pct, 100);
});

test('codex getCodexUsage heals an elapsed five_hour window', () => {
  // End-to-end (fresh build, no cache yet): the team snapshot's 5h window
  // reset long ago (resets_at 1700000000). Absent any newer team rollout,
  // getCodexUsage must render 0% instead of the frozen 100% snapshot.
  const now = Date.now() / 1000;
  const record = withCodexHome(
    [['team', 'codex_rollout_team_elapsed.jsonl', now - 60]],
    () => providers.getCodexUsage({}),
  );

  assert.equal(record.plan, 'team');
  assert.deepEqual(record.five_hour, { used_pct: 0, resets_at: null, label: '5h' });
  assert.equal(record.weekly.used_pct, 84);
  assert.equal(record.weekly.resets_at, 4102444800);
  assert.equal(record.weekly.label, '7d');
});

test('codex getCodexUsage heals a cache hit', () => {
  // A cache written while the window still looked hot (or written by an older
  // binary, pre-healing) must still render healed when read back within TTL:
  // the elapsed-window proof depends on wall-clock time at READ time, not at
  // write time.
  const home = fs.mkdtempSync(path.join(os.tmpdir(), 'statusline-codex-cache-'));
  const oldHome = process.env.HOME;
  const oldUserProfile = process.env.USERPROFILE;
  try {
    process.env.HOME = home;
    process.env.USERPROFILE = home;
    const cacheDir = path.join(home, '.claude');
    fs.mkdirSync(cacheDir, { recursive: true });
    fs.writeFileSync(
      path.join(cacheDir, 'statusline-usage-codex.json'),
      JSON.stringify({
        cached_at: Date.now() / 1000,
        record: {
          provider: 'codex',
          label: 'Codex',
          available: true,
          five_hour: { used_pct: 100, resets_at: 1700000000, label: '5h' },
          weekly: { used_pct: 84, resets_at: 4102444800, label: '7d' },
          plan: 'team',
          tokens: null,
          stale_seconds: 0,
        },
      }),
    );

    const record = providers.getCodexUsage({});

    assert.deepEqual(record.five_hour, { used_pct: 0, resets_at: null, label: '5h' });
    assert.equal(record.weekly.used_pct, 84);
    assert.equal(record.weekly.resets_at, 4102444800);
  } finally {
    if (oldHome == null) delete process.env.HOME; else process.env.HOME = oldHome;
    if (oldUserProfile == null) delete process.env.USERPROFILE; else process.env.USERPROFILE = oldUserProfile;
    fs.rmSync(home, { recursive: true, force: true });
  }
});

test('codex getCodexUsage prefers a fresh live app-server cache over rollouts', () => {
  // The Node twin is cache-read-only: it must render the live snapshot the
  // Python refresher wrote (source: 'app-server'), preferring it over a frozen
  // rollout on disk, and never spawn app-server itself.
  const home = fs.mkdtempSync(path.join(os.tmpdir(), 'statusline-codex-live-'));
  const oldHome = process.env.HOME;
  const oldUserProfile = process.env.USERPROFILE;
  try {
    process.env.HOME = home;
    process.env.USERPROFILE = home;
    const now = Math.floor(Date.now() / 1000);

    // A frozen rollout that would read 100% used ...
    const sessions = path.join(home, '.codex', 'sessions', '2026', '07', '09');
    fs.mkdirSync(sessions, { recursive: true });
    const rollout = path.join(sessions, 'rollout-team.jsonl');
    fs.copyFileSync(path.join(repoRoot, 'tests', 'fixtures', 'codex_rollout_team_snapshot.jsonl'), rollout);

    // ... but a fresh live app-server snapshot says 10% / 2%.
    const cacheDir = path.join(home, '.claude');
    fs.mkdirSync(cacheDir, { recursive: true });
    fs.writeFileSync(
      path.join(cacheDir, 'statusline-usage-codex.json'),
      JSON.stringify({
        cached_at: Date.now() / 1000,
        record: {
          provider: 'codex',
          label: 'Codex',
          available: true,
          five_hour: { used_pct: 10, resets_at: now + 3600, label: '5h' },
          weekly: { used_pct: 2, resets_at: now + 7 * 86400, label: '7d' },
          plan: 'team',
          source: 'app-server',
          stale_seconds: 0,
        },
      }),
    );

    const record = providers.getCodexUsage({});

    assert.equal(record.source, 'app-server');
    assert.equal(record.five_hour.used_pct, 10);
    assert.equal(record.weekly.used_pct, 2);
    assert.equal(record.plan, 'team');
  } finally {
    if (oldHome == null) delete process.env.HOME; else process.env.HOME = oldHome;
    if (oldUserProfile == null) delete process.env.USERPROFILE; else process.env.USERPROFILE = oldUserProfile;
    fs.rmSync(home, { recursive: true, force: true });
  }
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

test('antigravity CLI snapshot groups current lineup into two pools', () => {
  // Real `antigravity-usage quota --json` shape: 8 models across the current
  // Gemini/Claude/GPT-OSS lineup. Antigravity's real quota structure is TWO
  // pools ("Gemini Models" and "Claude and GPT models") that each share ONE
  // 5-hour + weekly limit — Opus/Sonnet/GPT are NOT independent pools. Within
  // a pool, used_pct is the MAX (most-constrained) member, and resets_at picks
  // the earliest resetTime among members tied on that max.
  const snapshot = JSON.parse(fs.readFileSync(path.join(fixtures, 'antigravity_quota_response.json'), 'utf8'));

  const metrics = providers.mapAntigravitySnapshot(snapshot);

  assert.deepEqual(metrics.map(metric => [metric.label, metric.used_pct]), [
    ['Gemini', 60],
    ['Claude+GPT', 90],
  ]);
  // Gemini's max (60%) is tied between "Flash (High)" and "Pro (High)"; the
  // earlier of their two resetTimes wins ("Pro (High)" resets at noon UTC).
  // Claude+GPT's max (90%) is "Claude Opus 4.6 (Thinking)" alone, no tie.
  assert.deepEqual(metrics.map(metric => metric.resets_at), [1783598400, 1783627200]);

  const record = { ...providers.unavailable('antigravity'), available: true, label: 'AGY', display: 'compact', metrics };
  const row = providers.formatProviderRowParts(record, 1_000);
  for (const [label, pct] of [['Gemini', 60], ['Claude+GPT', 90]]) {
    assert.ok(row.text.includes(`${label} ${pct}%`), `expected "${label} ${pct}%" in ${row.text}`);
  }
});

test('antigravity CLI snapshot skips autocomplete-only models', () => {
  const snapshot = {
    models: [
      { label: 'Gemini 3.5 Flash (Autocomplete)', modelId: 'gemini-ac', remainingPercentage: 0.1, isAutocompleteOnly: true },
      { label: 'Gemini 3.5 Flash (Low)', modelId: 'gemini-flash-low', remainingPercentage: 0.7 },
    ],
  };

  const metrics = providers.mapAntigravitySnapshot(snapshot);

  assert.deepEqual(metrics.map(metric => [metric.label, metric.used_pct]), [['Gemini', 30]]);
});

test('antigravity CLI snapshot old lineup lands in gemini pool', () => {
  // Backward compatibility: if the CLI ever reverts to the old bare Flash/Pro
  // labels (no "Gemini" prefix), the flash/pro keyword match must still route
  // them into the Gemini pool instead of a spurious own pool.
  const snapshot = {
    models: [
      { label: 'Flash', modelId: 'flash', remainingPercentage: 0.8 },
      { label: 'Pro', modelId: 'pro', remainingPercentage: 0.6 },
    ],
  };

  const metrics = providers.mapAntigravitySnapshot(snapshot);

  assert.deepEqual(metrics.map(metric => [metric.label, metric.used_pct]), [['Gemini', 40]]);
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
