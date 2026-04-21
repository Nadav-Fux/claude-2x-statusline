/**
 * Rolling-window state for statusline metrics (Node.js).
 *
 * Direct port of lib/rolling_state.py — stores a 60-minute ring of samples
 * at ~/.claude/statusline-state.json.  Each sample:
 *   { t: epoch_sec, cost: float, tokens_in: int, tokens_out: int,
 *     cache_read: int, cache_creation: int }
 */

const fs = require('fs');
const os = require('os');
const path = require('path');

const HOME = process.env.HOME || process.env.USERPROFILE;
const CLAUDE_DIR = path.join(HOME, '.claude');
const STATE_PATH = path.join(CLAUDE_DIR, 'statusline-state.json');
const TMP_PATH = path.join(CLAUDE_DIR, 'statusline-state.json.tmp');
const MAX_AGE_SECS = 3600;

const MIN_SPAN_SECS = 180;
const MAX_PLAUSIBLE_RATE = 200.0;

function ensureDir() {
  try { fs.mkdirSync(CLAUDE_DIR, { recursive: true, mode: 0o700 }); } catch {}
}

function load() {
  try {
    return JSON.parse(fs.readFileSync(STATE_PATH, 'utf8'));
  } catch {
    return { samples: [] };
  }
}

function save(state) {
  try {
    ensureDir();
    const text = JSON.stringify(state);
    fs.writeFileSync(TMP_PATH, text, 'utf8');
    fs.renameSync(TMP_PATH, STATE_PATH);
  } catch {}
}

function windowSamples(samples, windowMin) {
  const cutoff = Date.now() / 1000 - windowMin * 60;
  return samples.filter(s => s.t >= cutoff);
}

function appendSample(cost, tokensIn, tokensOut, cacheRead, cacheCreation) {
  const state = load();
  const samples = state.samples || [];
  const now = Date.now() / 1000;
  const cutoff = now - MAX_AGE_SECS;
  const kept = samples.filter(s => s.t >= cutoff);
  kept.push({
    t: now,
    cost: Number(cost),
    tokens_in: Number(tokensIn),
    tokens_out: Number(tokensOut),
    cache_read: Number(cacheRead),
    cache_creation: Number(cacheCreation),
  });
  save({ samples: kept });
}

function rollingRate(windowMin = 10) {
  const state = load();
  const samples = windowSamples(state.samples || [], windowMin);
  if (samples.length < 2) return null;

  const oldest = samples[0];
  const latest = samples[samples.length - 1];
  const elapsedSecs = latest.t - oldest.t;
  if (elapsedSecs < MIN_SPAN_SECS) return null;

  const costDelta = latest.cost - oldest.cost;
  if (costDelta < 0) return null;

  const elapsedHours = elapsedSecs / 3600;
  if (elapsedHours <= 0) return null;

  const rate = costDelta / elapsedHours;
  if (rate > MAX_PLAUSIBLE_RATE) return null;
  return rate;
}

function rollingTokensOut(windowMin = 10) {
  const state = load();
  const samples = windowSamples(state.samples || [], windowMin);
  if (samples.length < 2) return null;

  const oldest = samples[0];
  const latest = samples[samples.length - 1];
  const elapsedSecs = latest.t - oldest.t;
  if (elapsedSecs < MIN_SPAN_SECS) return null;

  const delta = latest.tokens_out - oldest.tokens_out;
  return delta >= 0 ? delta : null;
}

function cacheDelta(windowMin = 5) {
  const state = load();
  const samples = windowSamples(state.samples || [], windowMin);
  if (samples.length < 2) return null;

  const oldest = samples[0];
  const latest = samples[samples.length - 1];
  const elapsedSecs = latest.t - oldest.t;
  if (elapsedSecs < 60) return null;

  const delta = latest.cache_read - oldest.cache_read;
  return delta >= 0 ? delta : null;
}

module.exports = {
  appendSample,
  rollingRate,
  rollingTokensOut,
  cacheDelta,
};
