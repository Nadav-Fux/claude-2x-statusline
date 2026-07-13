/**
 * narrator-node.test.mjs — Unit tests for narrator/narrator-node.js pure functions.
 *
 * Mirrors tests/test_narrator_scoring.py (Python parity suite).
 * Covers: C1 ctx_pct formula, L4 milestone template_key ints, H3 const→let
 * regression, novelty window, pick ordering/limits.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import fs from 'node:fs';
import os from 'node:os';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const narratorPath = path.join(repoRoot, 'narrator', 'narrator-node.js');
const narratorCliPath = path.join(repoRoot, 'narrator', 'cli.js');

// ── Import the pure functions exported from narrator-node.js ─────────────────
const { buildObservation, buildInsights, pick, nextMilestone, novelty, computeTrendFields, parseResetAt } =
  await import(narratorPath);

import { createRequire } from 'node:module';
const rs = createRequire(import.meta.url)(path.join(repoRoot, 'lib', 'rolling_state.js'));

// ── Helpers ──────────────────────────────────────────────────────────────────

function emptyMem() {
  return {
    current: {
      session_id: 'test-sess',
      started_at: 0,
      last_emit_at: 0,
      last_haiku_at: 0,
      rolling_observations: [],
      delivered_narratives: [],
      cost_milestones_hit: [],
      prompt_count: 0,
    },
    prior_sessions: [],
  };
}

/**
 * Build a minimal observation object, all-zeros by default.
 * Pass any overrides as a plain object.
 */
function makeObs(overrides = {}) {
  return Object.assign(
    {
      cost_usd: 0,
      burn_10m: null,
      burn_session: null,
      ctx_pct: 0,
      ctx_mins_left: null,
      cache_pct: 0,
      cache_delta_5m: null,
      is_peak: false,
      session_duration_min: 0,
      prompt_count: 0,
      rate_limit_5h_pct: 0,
      rate_limit_7d_pct: 0,
      rate_limit_5h_resets_at: null,
      rate_limit_7d_resets_at: null,
      rate_limit_7d_hours_left: null,
      cost_delta_5m: 0,
      cost_delta_20m: 0,
      ctx_delta_5m: 0,
      total_input_tokens: 0,
      total_output_tokens: 0,
      cache_read_tokens: 0,
      cache_creation_tokens: 0,
      ctx_window_size: 200000,
      cost_milestones_hit: [],
      subagent_tokens_live: 0,
      subagent_runs_session: 0,
      active_workflow_agents: 0,
    },
    overrides,
  );
}

// ── C1: ctx_pct formula ───────────────────────────────────────────────────────
// ctx_pct must be computed as:
//   (input_tokens + cache_creation_tokens + cache_read_tokens) / ctx_window * 100
// Output tokens MUST NOT be included.

test('C1: ctx_pct formula excludes output_tokens — subprocess integration', () => {
  /**
   * Drive via subprocess to exercise the real buildObservation() stdin path.
   *
   * input=100k, output=50k, cache_read=0, cache_creation=0, ctx_window=200k,
   * session_duration_min=70 (4200000ms).
   *
   * Correct formula: (100000 + 0 + 0) / 200000 * 100 = 50% → ctx_pct=50
   *   → ctx_high_long_session (fires when ctx>70 && session>60) does NOT fire.
   *
   * Wrong formula (if output were included):
   *   (100000 + 50000) / 200000 * 100 = 75% → ctx_high_long_session WOULD fire.
   */
  const home = fs.mkdtempSync(path.join(os.tmpdir(), 'c1-ctx-'));
  fs.mkdirSync(path.join(home, '.claude'), { recursive: true });

  try {
    const stdinData = JSON.stringify({
      cost: { total_cost_usd: 0.5, total_duration_ms: 4200000 }, // 70 min
      context_window: {
        context_window_size: 200000,
        current_usage: {
          input_tokens: 100000,
          output_tokens: 50000,
          cache_creation_input_tokens: 0,
          cache_read_input_tokens: 0,
        },
      },
    });

    const result = spawnSync(process.execPath, [narratorCliPath, 'session_start'], {
      input: stdinData,
      encoding: 'utf8',
      cwd: repoRoot,
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
    // ctx_high_long_session text contains "noise accumulating"
    assert.ok(
      !result.stdout.includes('noise accumulating'),
      `ctx_pct must be ~50% (output excluded), not 75% (output included). ` +
        `Got: ${result.stdout.trim()}`,
    );
  } finally {
    fs.rmSync(home, { recursive: true, force: true });
  }
});

// ── L4: nextMilestone returns int, template_key uses int ─────────────────────

test('L4: nextMilestone(0) → null', () => {
  assert.equal(nextMilestone(0), null);
});

test('L4: nextMilestone(4.99) → null (below $5)', () => {
  assert.equal(nextMilestone(4.99), null);
});

test('L4: nextMilestone(5) → 5 (exact boundary)', () => {
  assert.equal(nextMilestone(5), 5);
});

test('L4: nextMilestone(6) → 5 (between milestones)', () => {
  assert.equal(nextMilestone(6), 5);
});

test('L4: nextMilestone(10.5) → 10', () => {
  assert.equal(nextMilestone(10.5), 10);
});

test('L4: nextMilestone(100) → 100', () => {
  assert.equal(nextMilestone(100), 100);
});

test('L4: nextMilestone(150) → 100 (no milestone above $100)', () => {
  assert.equal(nextMilestone(150), 100);
});

test('L4: milestone template_key is milestone_5, not milestone_5.0', () => {
  /**
   * The milestone key must be `milestone_5` (integer suffix), not `milestone_5.0`
   * (float suffix). Python uses f"milestone_{milestone:.0f}" which rounds.
   * Node uses template literal with an integer constant from COST_MILESTONES.
   */
  const mem = emptyMem();
  const obs = makeObs({ cost_usd: 6.0, cost_milestones_hit: [], session_duration_min: 30 });
  const insights = buildInsights(obs, mem);
  const ms = insights.filter(i => i.template_key && i.template_key.startsWith('milestone_'));
  assert.ok(ms.length >= 1, 'Expected at least one milestone insight');
  assert.equal(ms[0].template_key, 'milestone_5', `Expected 'milestone_5', got '${ms[0].template_key}'`);
});

test('L4: milestone template_key is milestone_10, not milestone_10.0', () => {
  const mem = emptyMem();
  const obs = makeObs({ cost_usd: 11.0, cost_milestones_hit: [5], session_duration_min: 60 });
  const insights = buildInsights(obs, mem);
  const ms = insights.filter(i => i.template_key && i.template_key.startsWith('milestone_'));
  assert.ok(ms.length >= 1, 'Expected milestone_10 insight');
  assert.equal(ms[0].template_key, 'milestone_10');
});

test('L4: milestone does NOT fire when cost_milestones_hit contains 5 (int)', () => {
  const mem = emptyMem();
  const obs = makeObs({ cost_usd: 6.0, cost_milestones_hit: [5], session_duration_min: 30 });
  const insights = buildInsights(obs, mem);
  const ms = insights.filter(i => i.template_key && i.template_key.startsWith('milestone_'));
  assert.equal(ms.length, 0, 'Milestone should not fire when already in cost_milestones_hit as int');
});

test('L4: milestone does NOT fire when cost_milestones_hit contains 5.0 (float parity)', () => {
  /**
   * Python stores milestones as floats (5.0), Node should treat 5.0 === 5.
   * This guards against regressions where [5.0].includes(5) would fail if
   * types were incompatible.
   */
  const mem = emptyMem();
  const obs = makeObs({ cost_usd: 6.0, cost_milestones_hit: [5.0], session_duration_min: 30 });
  const insights = buildInsights(obs, mem);
  const ms = insights.filter(i => i.template_key && i.template_key.startsWith('milestone_'));
  assert.equal(ms.length, 0, 'Milestone should not fire when cost_milestones_hit=[5.0] (float)');
});

test('L4: milestone fires for $10 when $5 already in cost_milestones_hit', () => {
  const mem = emptyMem();
  const obs = makeObs({ cost_usd: 11.0, cost_milestones_hit: [5.0], session_duration_min: 60 });
  const insights = buildInsights(obs, mem);
  const ms = insights.filter(i => i.template_key && i.template_key.startsWith('milestone_'));
  assert.ok(ms.length >= 1, 'Milestone $10 should fire when $5 already hit but $10 not yet');
  assert.ok(ms[0].text.includes('$10'), `Expected '$10' in milestone text: ${ms[0].text}`);
});

test('L4: no milestone fires when all milestones already hit', () => {
  const mem = emptyMem();
  const obs = makeObs({
    cost_usd: 150.0,
    cost_milestones_hit: [5.0, 10.0, 25.0, 50.0, 100.0],
    session_duration_min: 120,
  });
  const insights = buildInsights(obs, mem);
  const ms = insights.filter(i => i.template_key && i.template_key.startsWith('milestone_'));
  assert.equal(ms.length, 0, 'No milestone should fire when all are already hit');
});

// ── H3: const→let regression guard ───────────────────────────────────────────
// Prior bug: `const rate = ...` inside the milestone block, then `rate = raw`
// re-assignment would throw TypeError in strict mode. Fixed to `let rate`.

test('H3: buildInsights does not throw when burn_10m=null, burn_session=null, session>=1, cost>0', () => {
  /**
   * This combination triggers the milestone fallback rate calculation:
   *   let rate = obs.burn_10m ?? obs.burn_session;   // null
   *   if (rate == null && session_duration_min >= 1 && cost_usd > 0) {
   *     const raw = cost_usd / (session_duration_min / 60);
   *     if (raw <= 200) rate = raw;   // <-- const→let bug was here
   *   }
   * The old `const rate` bug threw TypeError here.
   */
  const mem = emptyMem();
  const obs = makeObs({
    cost_usd: 6.0,
    burn_10m: null,
    burn_session: null,
    session_duration_min: 60,
    cost_milestones_hit: [],
  });

  let result;
  assert.doesNotThrow(() => {
    result = buildInsights(obs, mem);
  }, 'buildInsights must not throw when burn rates are null (H3 regression)');

  assert.ok(Array.isArray(result), 'buildInsights should return an array');
  // With cost_usd=6 and session_duration=60min, rate=6/1hr=6/hr → milestone fires
  const ms = result.filter(i => i.template_key && i.template_key.startsWith('milestone_'));
  assert.ok(ms.length >= 1, 'milestone insight should fire (rate computed from session data)');
});

test('H3: pick does not throw when burn_10m=null, burn_session=null, session>=1, cost>0', () => {
  const mem = emptyMem();
  const obs = makeObs({
    cost_usd: 6.0,
    burn_10m: null,
    burn_session: null,
    session_duration_min: 60,
    cost_milestones_hit: [],
  });

  let result;
  assert.doesNotThrow(() => {
    result = pick(obs, mem);
  }, 'pick must not throw when burn rates are null (H3 regression)');

  assert.ok(Array.isArray(result), 'pick should return an array');
  assert.ok(result.length <= 2, 'pick should return at most 2 insights');
});

// ── Novelty ───────────────────────────────────────────────────────────────────

test('novelty: first occurrence returns 10', () => {
  const mem = emptyMem();
  assert.equal(novelty('burn_high', mem), 10);
});

test('novelty: repeated template_key in last-3 returns 0', () => {
  const mem = emptyMem();
  mem.current.delivered_narratives = [
    { text: 'some text', template_key: 'burn_high', ts: 1000 },
  ];
  assert.equal(novelty('burn_high', mem), 0);
});

test('novelty: key outside last-3 window returns 10 (window = last 3)', () => {
  /**
   * 5 deliveries total; burn_high appears at positions 0,1,2 (oldest).
   * Last 3 = [burn_high@300, other@400, burn_low@500].
   * burn_high IS in last 3 → 0.
   */
  const mem = emptyMem();
  mem.current.delivered_narratives = [
    { text: 't1', template_key: 'burn_high', ts: 100 },
    { text: 't2', template_key: 'burn_high', ts: 200 },
    { text: 't3', template_key: 'burn_high', ts: 300 },  // in last 3
    { text: 't4', template_key: 'other',     ts: 400 },  // in last 3
    { text: 't5', template_key: 'burn_low',  ts: 500 },  // in last 3
  ];
  // burn_high IS in last 3 (position 300)
  assert.equal(novelty('burn_high', mem), 0);
  // burn_low IS in last 3
  assert.equal(novelty('burn_low', mem), 0);
  // Completely new key is NOT in last 3
  assert.equal(novelty('totally_new_key', mem), 10);
});

test('novelty: key only in older history (not in last 3) returns 10', () => {
  /**
   * 5 deliveries; key_x only at positions 0,1 (oldest, not in last 3).
   * Last 3 = [c@300, d@400, e@500].
   */
  const mem = emptyMem();
  mem.current.delivered_narratives = [
    { text: 't1', template_key: 'key_x', ts: 100 },
    { text: 't2', template_key: 'key_x', ts: 200 },
    { text: 't3', template_key: 'c',     ts: 300 },
    { text: 't4', template_key: 'd',     ts: 400 },
    { text: 't5', template_key: 'e',     ts: 500 },
  ];
  // key_x not in last 3 → should return 10
  assert.equal(novelty('key_x', mem), 10);
});

test('novelty: zero novelty depresses score, causing fresh insight to rank first', () => {
  /**
   * Memory has burn_high in recent narratives → novelty=0.
   * ctx_critical is fresh (novelty=10) and has urgency=10.
   * pick() should rank ctx_critical first.
   */
  const mem = emptyMem();
  mem.current.delivered_narratives = [
    { text: 'burn high text', template_key: 'burn_high', ts: 1000 },
  ];

  const obs = makeObs({
    burn_10m: 12.0,
    burn_session: 12.0,
    session_duration_min: 10,
    ctx_mins_left: 25,
    ctx_pct: 92,
    total_input_tokens: 185000,
    ctx_window_size: 200000,
  });

  const results = pick(obs, mem);
  assert.ok(results.length >= 1, 'Expected at least one insight');
  // ctx_critical has novelty=10 (fresh), burn_high has novelty=0 (seen recently)
  assert.ok(
    results[0].template_key === 'ctx_critical',
    `Expected ctx_critical first (fresh novelty beats stale burn_high), got: ${results[0].template_key}`,
  );
});

// ── pick() ordering / at-most-2 / empty ──────────────────────────────────────

test('pick: critical ctx beats moderate burn (priority ordering)', () => {
  const mem = emptyMem();
  const obs = makeObs({
    ctx_pct: 95,
    ctx_mins_left: 15,
    total_input_tokens: 190000,
    ctx_window_size: 200000,
    burn_10m: 7,
    burn_session: 7,
    session_duration_min: 30,
  });

  const results = pick(obs, mem);
  assert.ok(results.length >= 1, 'Expected at least one insight');
  // ctx_critical has urgency=10; moderate burn has urgency=4
  assert.ok(
    results[0].urgency >= 7,
    `Expected urgent insight first, got urgency=${results[0].urgency}: ${results[0].text}`,
  );
  assert.ok(
    results[0].text.toLowerCase().includes('compact now') ||
      results[0].text.toLowerCase().includes('fills in'),
    `Expected ctx_critical text, got: ${results[0].text}`,
  );
});

test('pick: returns at most 2 insights even when many conditions fire', () => {
  const mem = emptyMem();
  const obs = makeObs({
    ctx_pct: 95,
    ctx_mins_left: 20,
    total_input_tokens: 190000,
    ctx_window_size: 200000,
    burn_10m: 12,
    burn_session: 12,
    cache_pct: 20,
    cache_delta_5m: 2000,
    cache_read_tokens: 10000,
    is_peak: true,
    rate_limit_5h_pct: 85,
    session_duration_min: 30,
    cost_usd: 6,
    cost_milestones_hit: [],
  });

  const results = pick(obs, mem);
  assert.ok(results.length <= 2, `pick should return ≤ 2 insights, got ${results.length}`);
});

test('pick: returns empty array when no conditions fire', () => {
  const mem = emptyMem();
  const obs = makeObs({
    // all-zeros, no meaningful state
    total_input_tokens: 0,
    ctx_pct: 0,
    cache_pct: 0,
  });

  const results = pick(obs, mem);
  assert.ok(Array.isArray(results), 'pick should always return an array');
  assert.equal(results.length, 0, 'No insights should fire for a blank observation');
});

test('pick: high burn beats low cache in ordering', () => {
  const mem = emptyMem();
  const obs = makeObs({
    burn_10m: 12,
    burn_session: 12,
    cache_pct: 30,
    session_duration_min: 10,
    total_input_tokens: 50000,
  });

  const results = pick(obs, mem);
  assert.ok(results.length >= 1, 'Expected at least one insight');
  const texts = results.map(i => i.text);
  const burnIdx = texts.findIndex(t => t.toLowerCase().includes('burning'));
  const cacheIdx = texts.findIndex(t => t.toLowerCase().includes('cache hit'));
  assert.notEqual(burnIdx, -1, 'Expected burn_high insight in results');
  assert.notEqual(cacheIdx, -1, 'Expected cache_low insight in results');
  assert.ok(burnIdx < cacheIdx, 'burn_high should rank before cache_low');
});

// ── burn_high false-alarm fix regression ──────────────────────────────────────
// Bug history: hours_left used to be computed as max(0, (50 - obs.cost_usd) / rate)
// — a hardcoded $50 "budget" minus the SESSION-CUMULATIVE cost. Once a session
// passed $50 total (routine for long XHIGH sessions — observed at $154) this
// clamped to 0 and rendered "your 5-hour budget ends in ~0m", read downstream as
// "budget is spent" even though the REAL rate limits had huge headroom left
// (observed: 5h=3%, weekly=52%). Mirrors the Python
// TestBurnHighFalseAlarmFix suite in test_narrator_scoring.py.

test('burn_high: high cumulative cost does not imply budget exhausted (exact repro)', () => {
  const mem = emptyMem();
  const obs = makeObs({
    cost_usd: 154,
    burn_10m: 21.6,
    burn_session: 21.6,
    session_duration_min: 180,
    rate_limit_5h_pct: 3,
    rate_limit_7d_pct: 52,
  });

  const insights = buildInsights(obs, mem);
  const burn = insights.find(i => i.template_key === 'burn_high');
  assert.ok(burn, 'Expected a burn_high insight');

  const low = burn.text.toLowerCase();
  assert.ok(!low.includes('0m'), `Must not read as a zeroed-out countdown: ${burn.text}`);
  assert.ok(!low.includes('budget ends'), `Must not claim the budget ended: ${burn.text}`);
  assert.ok(!low.includes('spent'), `Must not claim the budget is spent: ${burn.text}`);
  assert.ok(
    burn.text.includes('3%') && burn.text.includes('52%'),
    `Expected the real 5h/weekly headroom (3%/52%) cited, got: ${burn.text}`,
  );
  assert.ok(burn.urgency <= 5, `Non-escalated burn_high must not dominate: urgency=${burn.urgency}`);

  assert.ok(!burn.text_he.includes('0m'));
  assert.ok(burn.text_he.includes('3%') && burn.text_he.includes('52%'));
});

test('burn_high: genuinely near a real limit still escalates', () => {
  const mem = emptyMem();
  const obs = makeObs({
    cost_usd: 40,
    burn_10m: 21.6,
    burn_session: 21.6,
    session_duration_min: 180,
    rate_limit_5h_pct: 85, // >= 80 → escalate
    rate_limit_7d_pct: 52,
  });

  const insights = buildInsights(obs, mem);
  const burn = insights.find(i => i.template_key === 'burn_high');
  assert.ok(burn, 'Expected a burn_high insight');
  assert.ok(burn.urgency >= 7, `Near-limit burn_high must escalate urgency, got ${burn.urgency}`);
  assert.ok(burn.text.includes('85%'));
  assert.ok(/ease off|cap/i.test(burn.text));
});

// ── Score formula ─────────────────────────────────────────────────────────────

test('score formula: urgency*3 + novelty*2 + actionability*2 + uniqueness', () => {
  /**
   * Verify the sort key used by pick() matches the Python Insight.score property:
   *   score = urgency*3 + novelty*2 + actionability*2 + uniqueness*1
   *
   * Node uses the same formula inline in the sort comparator.
   */
  const mem = emptyMem();
  // Trigger ctx_critical: urgency=10, novelty=10, actionability=10, uniqueness=10
  // score = 10*3 + 10*2 + 10*2 + 10*1 = 30+20+20+10 = 80
  const obsHigh = makeObs({ ctx_mins_left: 15, ctx_pct: 95, total_input_tokens: 190000 });
  const insightsHigh = buildInsights(obsHigh, mem);
  const ctxCritical = insightsHigh.find(i => i.template_key === 'ctx_critical');
  assert.ok(ctxCritical, 'ctx_critical should be present');
  const expectedScore = ctxCritical.urgency * 3 + ctxCritical.novelty * 2 +
    ctxCritical.actionability * 2 + ctxCritical.uniqueness;
  assert.equal(expectedScore, 80, `Expected score 80 for all-10s insight, got ${expectedScore}`);
});

// ── Session-management templates ──────────────────────────────────────────────

test('long_session fires after 2h with high context', () => {
  const mem = emptyMem();
  const obs = makeObs({ session_duration_min: 130, ctx_pct: 70 });
  const insights = buildInsights(obs, mem);
  const ls = insights.filter(i => i.template_key === 'long_session');
  assert.ok(ls.length >= 1, `Expected long_session insight, got: ${insights.map(i => i.template_key)}`);
  assert.ok(ls[0].text.includes('2h') || ls[0].text.includes('h '), 'Should mention hours');
  assert.equal(ls[0].actionability, 8);
});

test('long_session does NOT fire under 2h', () => {
  const mem = emptyMem();
  const obs = makeObs({ session_duration_min: 90, ctx_pct: 70 });
  const insights = buildInsights(obs, mem);
  const ls = insights.filter(i => i.template_key === 'long_session');
  assert.equal(ls.length, 0, 'long_session should not fire for 90 min session');
});

test('long_session does NOT nag when context is low (200k-bug fix)', () => {
  const mem = emptyMem();
  const obs = makeObs({ session_duration_min: 216, ctx_pct: 19 });
  const insights = buildInsights(obs, mem);
  const ls = insights.filter(i => i.template_key === 'long_session');
  assert.equal(ls.length, 0, 'Duration alone must not trigger a context nag');
});

test('ctx_high_long_session fires at ctx_pct=75 + session > 60min', () => {
  const mem = emptyMem();
  const obs = makeObs({ ctx_pct: 75, session_duration_min: 80 });
  const insights = buildInsights(obs, mem);
  const hi = insights.filter(i => i.template_key === 'ctx_high_long_session');
  assert.ok(hi.length >= 1, `Expected ctx_high_long_session, got: ${insights.map(i => i.template_key)}`);
  assert.ok(hi[0].text.toLowerCase().includes('compact'), 'Should mention compact');
  assert.equal(hi[0].urgency, 6);
  assert.equal(hi[0].actionability, 10);
});

test('ctx_high_long_session does NOT fire for short session', () => {
  const mem = emptyMem();
  const obs = makeObs({ ctx_pct: 75, session_duration_min: 30 });
  const insights = buildInsights(obs, mem);
  const hi = insights.filter(i => i.template_key === 'ctx_high_long_session');
  assert.equal(hi.length, 0, 'ctx_high_long_session should not fire for 30 min session');
});

test('ctx_very_high fires at ctx_pct=95 with urgency=9', () => {
  const mem = emptyMem();
  const obs = makeObs({ ctx_pct: 95 });
  const insights = buildInsights(obs, mem);
  const vh = insights.filter(i => i.template_key === 'ctx_very_high');
  assert.ok(vh.length >= 1, `Expected ctx_very_high, got: ${insights.map(i => i.template_key)}`);
  assert.equal(vh[0].urgency, 9);
  assert.equal(vh[0].actionability, 10);
  assert.ok(
    vh[0].text.toLowerCase().includes('auto-compact') ||
      vh[0].text.includes('/compact'),
    'Should mention auto-compact or /compact',
  );
});

test('many_prompts fires above 30 prompts with high context', () => {
  const mem = emptyMem();
  const obs = makeObs({ prompt_count: 35, ctx_pct: 70 });
  const insights = buildInsights(obs, mem);
  const mp = insights.filter(i => i.template_key === 'many_prompts');
  assert.ok(mp.length >= 1, `Expected many_prompts insight, got: ${insights.map(i => i.template_key)}`);
  assert.ok(mp[0].text.includes('35'), `Expected '35' in text: ${mp[0].text}`);
  assert.equal(mp[0].urgency, 3);
  assert.equal(mp[0].actionability, 8);
});

test('many_prompts does NOT fire at 25 prompts', () => {
  const mem = emptyMem();
  const obs = makeObs({ prompt_count: 25, ctx_pct: 70 });
  const insights = buildInsights(obs, mem);
  const mp = insights.filter(i => i.template_key === 'many_prompts');
  assert.equal(mp.length, 0, 'many_prompts should not fire at prompt_count=25');
});

test('many_prompts does NOT nag when context is low', () => {
  const mem = emptyMem();
  const obs = makeObs({ prompt_count: 35, ctx_pct: 12 });
  const insights = buildInsights(obs, mem);
  const mp = insights.filter(i => i.template_key === 'many_prompts');
  assert.equal(mp.length, 0, 'Prompt count alone must not trigger a context nag');
});

test('claude_md_oversized fires above 200 lines', () => {
  const mem = emptyMem();
  const obs = makeObs({ claude_md_lines: 340 });
  const insights = buildInsights(obs, mem);
  const md = insights.filter(i => i.template_key === 'claude_md_oversized');
  assert.ok(md.length >= 1, `Expected claude_md_oversized, got: ${insights.map(i => i.template_key)}`);
  assert.ok(md[0].text.includes('340'), `Expected '340' in text: ${md[0].text}`);
  assert.ok(md[0].text_he, 'Should have Hebrew text');
  assert.equal(md[0].urgency, 2);
});

test('claude_md_oversized does NOT fire when small', () => {
  const mem = emptyMem();
  const obs = makeObs({ claude_md_lines: 60 });
  const insights = buildInsights(obs, mem);
  const md = insights.filter(i => i.template_key === 'claude_md_oversized');
  assert.equal(md.length, 0, 'A 60-line CLAUDE.md is optimal — no tip');
});

// Regression (Codex review P2): Node-only installs must fall back to the
// session-scoped rolling sample for tokens, or every ctx_pct-gated insight
// stays silent because hook stdin carries no context_window block.
test('buildObservation falls back to rolling sample → ctx_pct computed (not 0)', () => {
  const sid = 'zzregressionnode';
  const home = process.env.HOME || process.env.USERPROFILE;
  const statePath = path.join(home, '.claude', `statusline-state-${sid.substring(0, 8)}.json`);
  const ctxDir = path.join(os.tmpdir(), 'claude');
  const ctxFile = path.join(ctxDir, 'statusline-context.json');
  let ctxBackup = null;
  try {
    rs.setSessionId(sid);
    rs.appendSample(50, 2000, 10, 158000, 0); // ~160k used (in + cache_read)
    fs.mkdirSync(ctxDir, { recursive: true });
    if (fs.existsSync(ctxFile)) ctxBackup = fs.readFileSync(ctxFile, 'utf8');
    fs.writeFileSync(ctxFile, JSON.stringify({ context_window_size: 1000000, model: 'Opus 4.8 (1M context)' }));

    const obs = buildObservation({ current: { started_at: Date.now() / 1000 - 7200 } });
    assert.equal(obs.ctx_window_size, 1000000, 'window resolves to 1M');
    assert.ok(obs.ctx_pct > 15 && obs.ctx_pct < 17, `ctx_pct ~16% expected, got ${obs.ctx_pct}`);
  } finally {
    try { fs.unlinkSync(statePath); } catch {}
    if (ctxBackup !== null) { try { fs.writeFileSync(ctxFile, ctxBackup); } catch {} }
    rs.setSessionId('');
  }
});

test('pivot_suggestion fires when deep in session with no fresh milestone', () => {
  const mem = emptyMem();
  const obs = makeObs({ ctx_pct: 60, prompt_count: 25, cost_usd: 0, cost_milestones_hit: [] });
  const insights = buildInsights(obs, mem);
  const pv = insights.filter(i => i.template_key === 'pivot_suggestion');
  assert.ok(pv.length >= 1, `Expected pivot_suggestion, got: ${insights.map(i => i.template_key)}`);
  assert.ok(pv[0].text.toLowerCase().includes('rewind'), 'Should mention rewind');
  assert.equal(pv[0].urgency, 5);
});

test('pivot_suggestion suppressed when fresh milestone is being crossed', () => {
  const mem = emptyMem();
  // cost_usd just crossed $5 and not yet in milestones_hit
  const obs = makeObs({ ctx_pct: 60, prompt_count: 25, cost_usd: 6.0, cost_milestones_hit: [] });
  const insights = buildInsights(obs, mem);
  const pv = insights.filter(i => i.template_key === 'pivot_suggestion');
  assert.equal(pv.length, 0, 'pivot_suggestion should be suppressed when milestone is fresh');
});

test('subagent_suggestion fires for heavy work (burn_10m > 8, session > 15m)', () => {
  const mem = emptyMem();
  const obs = makeObs({ session_duration_min: 20, burn_10m: 9.0 });
  const insights = buildInsights(obs, mem);
  const sa = insights.filter(i => i.template_key === 'subagent_suggestion');
  assert.ok(sa.length >= 1, `Expected subagent_suggestion, got: ${insights.map(i => i.template_key)}`);
  assert.ok(sa[0].text.toLowerCase().includes('subagent'), 'Should mention subagent');
  assert.equal(sa[0].urgency, 2);
});

test('subagent_suggestion does NOT fire when burn_10m <= 8', () => {
  const mem = emptyMem();
  const obs = makeObs({ session_duration_min: 20, burn_10m: 5.0 });
  const insights = buildInsights(obs, mem);
  const sa = insights.filter(i => i.template_key === 'subagent_suggestion');
  assert.equal(sa.length, 0, 'subagent_suggestion should not fire when burn_10m=5');
});

// ── Hebrew text parity ────────────────────────────────────────────────────────

test('every insight that fires has a non-empty text_he (Hebrew parity)', () => {
  /**
   * Build an observation that triggers as many templates as possible,
   * then verify every returned insight has a text_he field with Hebrew content.
   */
  const mem = emptyMem();
  const obs = makeObs({
    ctx_pct: 85,
    ctx_mins_left: 20,
    ctx_window_size: 200000,
    total_input_tokens: 170000,
    burn_10m: 12,
    burn_session: 12,
    cache_pct: 30,
    cache_delta_5m: 2000,
    cache_read_tokens: 30000,
    is_peak: true,
    rate_limit_5h_pct: 85,
    rate_limit_7d_pct: 20,
    session_duration_min: 130,
    cost_usd: 6,
    cost_milestones_hit: [],
    prompt_count: 35,
  });

  const insights = buildInsights(obs, mem);
  assert.ok(insights.length >= 1, 'Expected at least one insight from universal observation');

  const missingHebrew = insights.filter(
    i => !i.text_he || !Array.from(i.text_he).some(c => c >= 'א' && c <= 'ת'),
  );
  assert.equal(
    missingHebrew.length,
    0,
    `These templates lack valid Hebrew text: ${missingHebrew.map(i => i.template_key).join(', ')}`,
  );
});

// ── computeTrendFields ────────────────────────────────────────────────────────

test('computeTrendFields: empty rollingObs returns all nulls', () => {
  const result = computeTrendFields([], Date.now() / 1000);
  assert.equal(result.cost_5m_ago, null);
  assert.equal(result.cost_20m_ago, null);
  assert.equal(result.ctx_5m_ago, null);
});

test('computeTrendFields: returns cost_5m_ago from observation near 5m ago', () => {
  const now = Date.now() / 1000;
  const rollingObs = [
    { ts: now - 4 * 60, cost_usd: 1.5, ctx_pct: 20 },  // ~4m ago, close to 5m target
    { ts: now - 15 * 60, cost_usd: 0.5, ctx_pct: 10 }, // ~15m ago
  ];
  const result = computeTrendFields(rollingObs, now);
  // 4m ago is within 180s of the 5m target
  assert.equal(result.cost_5m_ago, 1.5);
  assert.equal(result.ctx_5m_ago, 20);
});

test('computeTrendFields: ignores observations outside tolerance window', () => {
  const now = Date.now() / 1000;
  const rollingObs = [
    // 10 minutes ago — too far from the 5m target (> 180s away)
    { ts: now - 10 * 60, cost_usd: 2.0, ctx_pct: 30 },
  ];
  const result = computeTrendFields(rollingObs, now);
  assert.equal(result.cost_5m_ago, null, 'Should not match when > 180s from 5m target');
});

// ── Cycle-aware rate-limit tiers (parity with test_narrator_rate_limits.py) ──

test('parseResetAt: parses Z-suffix and offset timestamps; null on bad input', () => {
  const z = parseResetAt({ resets_at: '2026-06-11T12:00:00Z' });
  const off = parseResetAt({ resets_at: '2026-06-11T12:00:00+00:00' });
  assert.ok(z instanceof Date && off instanceof Date);
  assert.equal(z.getTime(), off.getTime());
  assert.equal(parseResetAt(null), null);
  assert.equal(parseResetAt({}), null);
  assert.equal(parseResetAt({ resets_at: 'null' }), null);
  assert.equal(parseResetAt({ resets_at: 'not-a-date' }), null);
  assert.equal(parseResetAt({ resets_at: 12345 }), null);
});

test('rate-limit tier (a): high 7d% early in cycle → ahead_of_pace (urgency 7)', () => {
  const mem = emptyMem();
  // 6 days left of 7 → pace ~14%; 60% used >> pace → ahead.
  const obs = makeObs({ rate_limit_5h_pct: 20, rate_limit_7d_pct: 60, rate_limit_7d_hours_left: 6 * 24 });
  const insights = buildInsights(obs, mem);
  const keys = insights.map(i => i.template_key);
  assert.ok(keys.includes('rate_limit_ahead_of_pace'), `got: ${keys}`);
  assert.ok(!keys.includes('rate_limit_high'));
  const ahead = insights.find(i => i.template_key === 'rate_limit_ahead_of_pace');
  assert.equal(ahead.urgency, 7); // firm, not alarmist
  assert.ok(ahead.text.includes('ahead of an even'));
  assert.ok(ahead.text_he && Array.from(ahead.text_he).some(c => c >= 'א' && c <= 'ת'));
});

test('rate-limit: AHEAD fires on any day, not just early (e.g. day 5)', () => {
  const mem = emptyMem();
  // 2 days left → pace ~71%. 88% used → ahead by ~17 (<90 so not near-cap).
  const obs = makeObs({ rate_limit_5h_pct: 10, rate_limit_7d_pct: 88, rate_limit_7d_hours_left: 2 * 24 });
  const keys = buildInsights(obs, mem).map(i => i.template_key);
  assert.ok(keys.includes('rate_limit_ahead_of_pace'), `got: ${keys}`);
  assert.ok(!keys.includes('rate_limit_high'));
});

test('rate-limit tier (b): lowish 7d% on last day → headroom :) variant', () => {
  const mem = emptyMem();
  // 12h left → days_left=0.5; 40% used; pace ~93 so (pace-pct7)>=12.
  const obs = makeObs({ rate_limit_5h_pct: 10, rate_limit_7d_pct: 40, rate_limit_7d_hours_left: 12 });
  const insights = buildInsights(obs, mem);
  const keys = insights.map(i => i.template_key);
  assert.ok(keys.includes('rate_limit_headroom_near_reset'), `got: ${keys}`);
  assert.ok(!keys.includes('rate_limit_ahead_of_pace'));
  const head = insights.find(i => i.template_key === 'rate_limit_headroom_near_reset');
  assert.equal(head.urgency, 3); // gentle
  assert.ok(head.text.includes('resets in') && head.text.includes('before it resets'));
  assert.ok(head.text_he.includes(':)'));
});

test('rate-limit: BEHIND on a general day → calm phrasing (not :) variant)', () => {
  const mem = emptyMem();
  // 5 days left → pace ~29%. 10% used → behind by ~19.
  const obs = makeObs({ rate_limit_5h_pct: 10, rate_limit_7d_pct: 10, rate_limit_7d_hours_left: 5 * 24 });
  const insights = buildInsights(obs, mem);
  const head = insights.find(i => i.template_key === 'rate_limit_headroom_near_reset');
  assert.ok(head, `expected headroom insight, got: ${insights.map(i => i.template_key)}`);
  assert.equal(head.urgency, 3);
  assert.ok(head.text.includes('under an even weekly pace'));
  assert.ok(!head.text.includes('before it resets'));
});

test('rate-limit: ON-PACE fires near the line (urgency 2)', () => {
  const mem = emptyMem();
  // 3.5 days left → pace 50%. 45% used → abs(45-50)=5<12, pct7>=20.
  const obs = makeObs({ rate_limit_5h_pct: 10, rate_limit_7d_pct: 45, rate_limit_7d_hours_left: 3.5 * 24 });
  const insights = buildInsights(obs, mem);
  const keys = insights.map(i => i.template_key);
  assert.ok(keys.includes('rate_limit_on_pace'), `got: ${keys}`);
  assert.ok(!keys.includes('rate_limit_ahead_of_pace'));
  assert.ok(!keys.includes('rate_limit_headroom_near_reset'));
  const onp = insights.find(i => i.template_key === 'rate_limit_on_pace');
  assert.equal(onp.urgency, 2);
  assert.ok(onp.text.includes('on an even weekly pace'));
  assert.ok(onp.text_he);
});

test('rate-limit: ON-PACE stays silent when too early and pct7<20', () => {
  const mem = emptyMem();
  // 6 days left → pace ~14. 10% used: abs<12 but pct7<20 → no on-pace, no behind.
  const obs = makeObs({ rate_limit_5h_pct: 10, rate_limit_7d_pct: 10, rate_limit_7d_hours_left: 6 * 24 });
  const rl = buildInsights(obs, mem).map(i => i.template_key).filter(k => k.startsWith('rate_limit'));
  assert.deepEqual(rl, []);
});

test('rate-limit tier (c): >=90% fires near-cap regardless of cycle', () => {
  const mem = emptyMem();
  const obs = makeObs({ rate_limit_5h_pct: 30, rate_limit_7d_pct: 92, rate_limit_7d_hours_left: 3 * 24 });
  const insights = buildInsights(obs, mem);
  const keys = insights.map(i => i.template_key);
  assert.ok(keys.includes('rate_limit_high'), `got: ${keys}`);
  assert.ok(!keys.includes('rate_limit_ahead_of_pace'));
  assert.equal(insights.find(i => i.template_key === 'rate_limit_high').urgency, 10);
});

test('rate-limit tier (d): missing reset data → graceful old >80% fallback', () => {
  const mem = emptyMem();
  const obs = makeObs({ rate_limit_5h_pct: 85, rate_limit_7d_pct: 10, rate_limit_7d_hours_left: null });
  const insights = buildInsights(obs, mem);
  const keys = insights.map(i => i.template_key);
  assert.ok(keys.includes('rate_limit_high'), `got: ${keys}`);
  assert.ok(!keys.includes('rate_limit_ahead_of_pace'));
  assert.ok(!keys.includes('rate_limit_headroom_near_reset'));
  assert.ok(!keys.includes('rate_limit_on_pace'));
});

test('rate-limit 5h rolling tier fires in the weekly dead-band', () => {
  const mem = emptyMem();
  // 3 days left → pace ~57. pct7=70 → ahead by ~13: not on-pace (>=12), not
  // AHEAD (<15), not behind. pct5=88 (>85, <90) → 5h rolling surfaces.
  const obs = makeObs({ rate_limit_5h_pct: 88, rate_limit_7d_pct: 70, rate_limit_7d_hours_left: 3 * 24 });
  const insights = buildInsights(obs, mem);
  const keys = insights.map(i => i.template_key);
  assert.ok(keys.includes('rate_limit_5h_rolling'), `got: ${keys}`);
  assert.ok(!keys.includes('rate_limit_high'));
  assert.ok(!keys.includes('rate_limit_ahead_of_pace'));
  assert.ok(!keys.includes('rate_limit_on_pace'));
  assert.ok(!keys.includes('rate_limit_headroom_near_reset'));
  assert.equal(insights.find(i => i.template_key === 'rate_limit_5h_rolling').urgency, 9);
});

test('rate-limit tiers are mutually exclusive (near-cap wins precedence)', () => {
  const mem = emptyMem();
  const obs = makeObs({ rate_limit_5h_pct: 95, rate_limit_7d_pct: 92, rate_limit_7d_hours_left: 12 });
  const insights = buildInsights(obs, mem);
  const rl = insights.map(i => i.template_key).filter(k => k.startsWith('rate_limit'));
  assert.equal(rl.length, 1);
  assert.equal(rl[0], 'rate_limit_high');
});

test('rate-limit: 12–15 slightly-ahead dead-band emits no tier', () => {
  const mem = emptyMem();
  // 3 days left → pace ~57. pct7=70 → ahead by ~13: between on-pace and AHEAD.
  const obs = makeObs({ rate_limit_5h_pct: 30, rate_limit_7d_pct: 70, rate_limit_7d_hours_left: 3 * 24 });
  const rl = buildInsights(obs, mem).map(i => i.template_key).filter(k => k.startsWith('rate_limit'));
  assert.deepEqual(rl, []);
});
