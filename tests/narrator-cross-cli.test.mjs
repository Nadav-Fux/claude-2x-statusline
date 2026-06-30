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
  const obs = makeObs({
    external_usage: [{
      provider: 'glm',
      label: 'GLM',
      available: true,
      five_hour: { used_pct: 0 },
      weekly: { used_pct: 100, label: 'tok' },
    }],
  });

  const insights = buildInsights(obs, memory());
  const capped = insights.find(insight => insight.template_key === 'cross_cli_capped');

  assert.ok(capped);
  assert.ok(capped.text.includes('GLM tok quota is maxed (100%)'));
  assert.ok(capped.text_he);
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
