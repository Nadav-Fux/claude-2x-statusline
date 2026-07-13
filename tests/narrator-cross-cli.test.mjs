import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const narratorPath = path.join(repoRoot, 'narrator', 'narrator-node.js');
const { buildInsights } = await import(narratorPath);

function memory() {
  return { current: { delivered_narratives: [] }, prior_sessions: [] };
}

function makeObs(overrides = {}) {
  return Object.assign({
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
    rate_limit_7d_hours_left: null,
    total_input_tokens: 0,
    cache_read_tokens: 0,
    cost_milestones_hit: [],
    external_usage: [],
    active_workflow_agents: 0,
    subagent_tokens_live: 0,
    claude_md_lines: 0,
  }, overrides);
}

function keys(obs) {
  return new Set(buildInsights(obs, memory()).map(insight => insight.template_key));
}

test('cross_cli_capped fires for external cap', () => {
  // source: 'local-jsonl' + a small stale_seconds is the ONE trustworthy
  // per-record recency signal (see providerRecentlyActive) — this is the
  // "active multi-CLI flow" case, so the insight should fire.
  const obs = makeObs({
    external_usage: [{
      provider: 'glm',
      label: 'GLM',
      available: true,
      source: 'local-jsonl',
      stale_seconds: 30,
      five_hour: { used_pct: 0 },
      weekly: { used_pct: 100, label: 'tok' },
    }],
  });

  const insights = buildInsights(obs, memory());
  const capped = insights.find(insight => insight.template_key === 'cross_cli_capped');

  assert.ok(capped);
  assert.ok(capped.text.includes("GLM's tok quota is maxed (100%)"));
  assert.ok(capped.text.includes('Your Claude budget'));
  assert.ok(capped.text_he);
  assert.ok(capped.text_he.includes('GLM'));
});

test('cross_cli_capped suppressed when the capped CLI is idle', () => {
  // Same cap, but the record's own recency signal shows it hasn't been
  // touched in an hour (source: 'local-jsonl', stale_seconds way past the
  // 10-minute window) — an idle CLI's cap must not surface as an insight.
  const obs = makeObs({
    external_usage: [{
      provider: 'glm',
      label: 'GLM',
      available: true,
      source: 'local-jsonl',
      stale_seconds: 3600,
      five_hour: { used_pct: 0 },
      weekly: { used_pct: 100, label: 'tok' },
    }],
  });

  assert.equal(keys(obs).has('cross_cli_capped'), false);
});

test('cross_cli_capped suppressed for untrusted live source when Claude is cool', () => {
  // Reproduces the reported false alarm: Codex's LIVE ('app-server') snapshot
  // always carries stale_seconds === 0 — written fresh on every background
  // poll regardless of whether Codex was actually used (see
  // usage_providers.js's normalizeCodexRateLimits / CODEX_LIVE_TTL). That '0'
  // looks fresh but is not proof of recent human activity, so 'app-server' is
  // not a trusted source (see LOCAL_ACTIVITY_SOURCES) and the conservative
  // fallback applies instead. With Claude's own 5h usage at 2% and no
  // weekly-pace data, the fallback must suppress — this is exactly the
  // "Claude at 2%, Codex maxed" false alarm from the bug report.
  const obs = makeObs({
    rate_limit_5h_pct: 2,
    external_usage: [{
      provider: 'codex',
      label: 'Codex',
      available: true,
      source: 'app-server',
      stale_seconds: 0,
      five_hour: { used_pct: 100, label: '5h' },
      weekly: { used_pct: 0, label: '7d' },
    }],
  });

  assert.equal(keys(obs).has('cross_cli_capped'), false);
});

test('cross_cli_capped fallback fires when Claude 5h is hot', () => {
  // Same untrusted-source record as above, but Claude's OWN 5h usage is
  // already warm (>= 50%) — the conservative fallback now judges the
  // cross-CLI mention relevant even without a trusted per-record signal, and
  // the wording still names the other CLI and clarifies Claude is unaffected.
  const obs = makeObs({
    rate_limit_5h_pct: 60,
    external_usage: [{
      provider: 'codex',
      label: 'Codex',
      available: true,
      source: 'app-server',
      stale_seconds: 0,
      five_hour: { used_pct: 100, label: '5h' },
      weekly: { used_pct: 0, label: '7d' },
    }],
  });

  const insights = buildInsights(obs, memory());
  const capped = insights.find(insight => insight.template_key === 'cross_cli_capped');

  assert.ok(capped);
  assert.ok(capped.text.includes('Codex'));
  assert.ok(capped.text.includes('Your Claude budget'));
});

test('cross_cli_offload fires when Claude weekly is hot and external provider is cool', () => {
  const obs = makeObs({
    rate_limit_7d_pct: 70,
    external_usage: [{
      provider: 'codex',
      label: 'Codex',
      available: true,
      five_hour: { used_pct: 10, label: '5h' },
      weekly: { used_pct: 10, label: '7d' },
    }],
  });

  assert.ok(keys(obs).has('cross_cli_offload'));
});

test('cross_cli_offload skips a provider busy on any window', () => {
  // Codex weekly is cool (25%) but 5h is at 90% — a bad offload target; with no
  // genuinely-cool provider, offload must stay silent.
  const obs = makeObs({
    rate_limit_7d_pct: 70,
    external_usage: [{
      provider: 'codex',
      label: 'Codex',
      available: true,
      five_hour: { used_pct: 90, label: '5h' },
      weekly: { used_pct: 25, label: '7d' },
    }],
  });

  assert.equal(keys(obs).has('cross_cli_offload'), false);
});

test('cross-CLI templates do not fire without external usage', () => {
  const obs = makeObs({ rate_limit_7d_pct: 70, external_usage: [] });
  const templateKeys = keys(obs);

  assert.equal(templateKeys.has('cross_cli_capped'), false);
  assert.equal(templateKeys.has('cross_cli_offload'), false);
});
