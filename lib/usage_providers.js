'use strict';

const fs = require('fs');
const { execFileSync } = require('child_process');
const https = require('https');
const os = require('os');
const path = require('path');

const PROVIDERS = {
  codex: ['Codex', 'local-jsonl'],
  glm: ['GLM', 'api'],
  droid: ['Droid', 'local-jsonl'],
  antigravity: ['Antigravity', 'sqlite'],
};

const LOCAL_CACHE_TTL = 45;
const GLM_CACHE_TTL = 60;
const EXTERNAL_USAGE_CACHE_TTL = 15 * 60;
const GLM_ENDPOINT = '/api/monitor/usage/quota/limit';

function homeDir() {
  return process.env.HOME || process.env.USERPROFILE || os.homedir();
}

function unavailable(provider) {
  const [label, source] = PROVIDERS[provider];
  return {
    provider,
    label,
    available: false,
    five_hour: null,
    weekly: null,
    display: 'bars',
    metrics: null,
    plan: null,
    tokens: null,
    source,
    stale_seconds: null,
  };
}

function usageWindow(usedPct, resetsAt, label = null) {
  const pct = Number(usedPct);
  if (!Number.isFinite(pct)) return null;
  const reset = resetsAt == null ? null : Number(resetsAt);
  const window = { used_pct: Math.max(0, Math.min(100, pct)), resets_at: Number.isFinite(reset) ? Math.trunc(reset) : null };
  const cleanLabel = label == null ? '' : String(label).trim();
  if (cleanLabel) window.label = cleanLabel;
  return window;
}

function codexWindowLabel(windowMinutes, fallback) {
  const mins = Number(windowMinutes);
  if (!Number.isFinite(mins)) return fallback;
  if (mins <= 360) return '5h';
  if (mins >= 10080) return '7d';
  const hours = mins / 60;
  return `${Number.isInteger(hours) ? hours : Math.round(hours * 10) / 10}h`;
}

function numberOrZero(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : 0;
}

function defaultFormatDuration(mins) {
  mins = Math.max(0, Math.trunc(numberOrZero(mins)));
  const h = Math.floor(mins / 60), m = mins % 60;
  return h > 0 ? `${h}h ${String(m).padStart(2, '0')}m` : `${m}m`;
}

function providerTokenTotal(tokens) {
  if (!tokens || typeof tokens !== 'object' || Array.isArray(tokens)) return 0;
  const direct = numberOrZero(tokens.total ?? tokens.total_tokens ?? tokens.totalTokens);
  if (direct > 0) return direct;
  return numberOrZero(tokens.input) + numberOrZero(tokens.output) + numberOrZero(tokens.input_tokens) +
    numberOrZero(tokens.output_tokens) + numberOrZero(tokens.cache_read) + numberOrZero(tokens.cache_creation) +
    numberOrZero(tokens.cached_input_tokens) + numberOrZero(tokens.reasoning_output_tokens) + numberOrZero(tokens.thinking);
}

function resetCountdown(resetsAt, nowSec, formatDuration) {
  const reset = Number(resetsAt);
  const now = Number.isFinite(Number(nowSec)) ? Number(nowSec) : Date.now() / 1000;
  if (!Number.isFinite(reset) || reset <= now) return '';
  const mins = Math.floor((reset - now) / 60);
  return `\u27f3 ${formatDuration(mins)}`;
}

// A 5-hour window shows a bare clock (12:00pm); anything longer shows a
// date + clock (4/7 5:00am), mirroring the Claude rate-limit line.
function resetStyleForLabel(label) {
  return String(label || '').includes('5h') ? 'time' : 'datetime';
}

// Reset text for one window/metric. With a clock formatter the reset is an
// absolute end-time (\u27f3 12:00pm / \u27f3 4/7 5:00am); otherwise it falls back to the
// legacy duration countdown (\u27f3 3h 58m). A null/missing reset shows nothing.
function resetDisplay(resetsAt, label, nowSec, formatDuration, formatClock) {
  if (typeof formatClock === 'function') {
    if (resetsAt == null) return '';
    let clock = '';
    try { clock = formatClock(resetsAt, resetStyleForLabel(label)); } catch { clock = ''; }
    return clock ? `\u27f3 ${clock}` : '';
  }
  return resetCountdown(resetsAt, nowSec, formatDuration);
}

function normalizeDisplayMetric(metric, fallbackLabel = '') {
  if (!metric || typeof metric !== 'object' || Array.isArray(metric)) return null;
  const label = String(metric.label || fallbackLabel || '').trim();
  if (!label) return null;
  const pct = Math.max(0, Math.min(100, Math.round(numberOrZero(metric.used_pct))));
  const reset = metric.resets_at == null ? null : Number(metric.resets_at);
  return { label, used_pct: pct, resets_at: Number.isFinite(reset) ? Math.trunc(reset) : null };
}

function compactMetricsForRecord(record) {
  const rawMetrics = Array.isArray(record.metrics) && record.metrics.length
    ? record.metrics
    : [
        record.five_hour ? { label: record.five_hour.label || '5h', used_pct: record.five_hour.used_pct, resets_at: record.five_hour.resets_at } : null,
        record.weekly ? { label: record.weekly.label || '7d', used_pct: record.weekly.used_pct, resets_at: record.weekly.resets_at } : null,
      ].filter(Boolean);
  return rawMetrics
    .map(metric => normalizeDisplayMetric(metric))
    .filter(Boolean);
}

function soonestResetText(metrics, nowSec, formatDuration, formatClock) {
  let soonest = null, soonestAt = null;
  const clockMode = typeof formatClock === 'function';
  for (const metric of metrics) {
    if (metric.resets_at == null) continue; // skip null/missing (Number(null)===0 is finite)
    const reset = Number(metric.resets_at);
    if (!Number.isFinite(reset)) continue;
    // Legacy duration mode hides already-elapsed resets; clock mode keeps the
    // absolute end-time regardless.
    if (!clockMode && reset <= nowSec) continue;
    if (soonestAt == null || reset < soonestAt) { soonestAt = reset; soonest = metric; }
  }
  return soonest == null ? '' : resetDisplay(soonest.resets_at, soonest.label, nowSec, formatDuration, formatClock);
}

function plainUsageBar(pct, width = 10) {
  const cleanPct = Math.max(0, Math.min(100, Math.round(numberOrZero(pct))));
  const filled = Math.floor(cleanPct * width / 100);
  return '▰'.repeat(filled) + '▱'.repeat(width - filled);
}

// Plain (uncolored) text rendering of a formatted row — mirrors the python
// _format_provider_row_text. The engine renders colored parts; this gives a
// stable string for tests and any plain consumer.
function formatProviderRowText(row) {
  const parts = Array.isArray(row.parts) ? row.parts : [];
  if (row.display === 'compact') {
    const labelPart = parts.find(p => p && p.kind === 'label') || {};
    const labelPlan = String(labelPart.plan || '');
    const labelText = `${labelPart.label || ''}${labelPlan ? ' ' + labelPlan : ''}`;
    const metrics = parts
      .filter(p => p && p.kind === 'metric')
      .map(p => `${p.label} ${p.pct}%`);
    const reset = row.resetText ? ` ${row.resetText}` : '';
    return `${labelText}  ${metrics.join(' · ')}${reset}${row.staleText || ''}`;
  }
  const chunks = [];
  for (const part of parts) {
    if (!part || typeof part !== 'object') continue;
    if (part.kind === 'label') {
      const plan = String(part.plan || '');
      chunks.push(`${part.label || ''}${plan ? ' ' + plan : ''}`);
    } else if (part.kind === 'window') {
      const reset = part.resetText ? ` ${part.resetText}` : '';
      const pct = Math.trunc(numberOrZero(part.pct));
      chunks.push(`${part.label} ${plainUsageBar(pct)} ${String(pct).padStart(3)}%${reset}`);
    } else if (part.kind === 'tokens') {
      chunks.push(`tokens ${Math.trunc(numberOrZero(part.total))}`);
    }
  }
  return `${chunks.join('  ')}${row.staleText || ''}`;
}

// Two compact rows (5h + weekly) for an Antigravity per-model record. Returns
// null when the record has no metrics_5h / metrics_weekly lists, so callers
// fall through to the normal compact/bars rendering.
function antigravityDualRows(record, label, nowSec, formatDuration, formatClock, stale) {
  const metrics5h = record.metrics_5h, metricsWeekly = record.metrics_weekly;
  if (!Array.isArray(metrics5h) && !Array.isArray(metricsWeekly)) return null;

  const subRows = [];
  for (const [windowLabel, rawMetrics] of [['5h', metrics5h], ['7d', metricsWeekly]]) {
    if (!Array.isArray(rawMetrics)) continue;
    const norm = rawMetrics.map(item => normalizeDisplayMetric(item)).filter(Boolean);
    if (!norm.length) continue;
    const subLabel = `${label} ${windowLabel}`;
    const subParts = [{ kind: 'label', label: subLabel, rawLabel: subLabel, plan: '' }];
    for (const metric of norm) subParts.push({ kind: 'metric', label: metric.label, pct: metric.used_pct, resetsAt: metric.resets_at });
    const resets = norm.map(metric => metric.resets_at).filter(value => value != null);
    const soonestReset = resets.length ? Math.min(...resets) : null;
    const sub = {
      label: subLabel,
      display: 'compact',
      parts: subParts,
      resetText: resetDisplay(soonestReset, windowLabel, nowSec, formatDuration, formatClock),
      stale,
      staleText: stale ? ' \u00b7stale' : '',
    };
    sub.text = formatProviderRowText(sub);
    subRows.push(sub);
  }
  if (!subRows.length) return null;
  const row = {
    label,
    display: 'agy_dual',
    parts: [{ kind: 'label', label, rawLabel: label, plan: '' }],
    subRows,
    stale,
    staleText: stale ? ' \u00b7stale' : '',
  };
  row.text = subRows.map(sub => sub.text).join('\n');
  return row;
}

function formatProviderRowParts(record, nowSec = Date.now() / 1000, options = {}) {
  if (!record || typeof record !== 'object' || !record.available) return null;
  const formatDuration = typeof options.formatDuration === 'function' ? options.formatDuration : defaultFormatDuration;
  const formatClock = typeof options.formatClock === 'function' ? options.formatClock : null;
  const label = String(record.label || record.provider || '').trim() || 'provider';
  const labelWidth = Math.max(0, Math.trunc(numberOrZero(options.labelWidth)));
  const paddedLabel = label + ' '.repeat(Math.max(0, labelWidth - label.length));
  const parts = [{ kind: 'label', label: paddedLabel, rawLabel: label, plan: record.plan ? String(record.plan) : '' }];
  const display = record.display === 'compact' ? 'compact' : 'bars';
  const staleSeconds = record.stale_seconds == null ? null : numberOrZero(record.stale_seconds);
  const stale = staleSeconds != null && staleSeconds > 600;

  // Antigravity per-model two-row layout (Opus/Pro/Flash) \u2014 a 5-hour row and a
  // weekly row \u2014 when the record carries metrics_5h / metrics_weekly lists.
  const dual = antigravityDualRows(record, label, nowSec, formatDuration, formatClock, stale);
  if (dual) return dual;

  if (display === 'compact') {
    const metrics = compactMetricsForRecord(record);
    for (const metric of metrics) {
      parts.push({
        kind: 'metric',
        label: metric.label,
        pct: metric.used_pct,
        resetsAt: metric.resets_at,
      });
    }
    if (parts.length <= 1) return null;
    const row = {
      label,
      display,
      parts,
      resetText: soonestResetText(metrics, nowSec, formatDuration, formatClock),
      stale,
      staleText: stale ? ' \u00b7stale' : '',
    };
    row.text = formatProviderRowText(row);
    return row;
  }

  for (const [fallbackLabel, window] of [['5h', record.five_hour], ['7d', record.weekly]]) {
    if (!window || typeof window !== 'object' || Array.isArray(window)) continue;
    const windowLabel = String(window.label || '').trim() || fallbackLabel;
    const pct = Math.max(0, Math.min(100, Math.round(numberOrZero(window.used_pct))));
    parts.push({
      kind: 'window',
      label: windowLabel,
      pct,
      resetText: resetDisplay(window.resets_at, windowLabel, nowSec, formatDuration, formatClock),
    });
  }

  const hasWindow = parts.some(part => part.kind === 'window');
  const tokensTotal = providerTokenTotal(record.tokens);
  if (!hasWindow && tokensTotal > 0) parts.push({ kind: 'tokens', total: tokensTotal });
  if (parts.length <= 1) return null;

  const row = { label, display, parts, stale, staleText: stale ? ' \u00b7stale' : '' };
  row.text = formatProviderRowText(row);
  return row;
}

function cachePath(provider) {
  return path.join(homeDir(), '.claude', `statusline-usage-${provider}.json`);
}

function readJson(file) {
  try { return JSON.parse(fs.readFileSync(file, 'utf8')); } catch { return null; }
}

function writeJson(file, value) {
  try {
    fs.mkdirSync(path.dirname(file), { recursive: true, mode: 0o700 });
    const tmp = `${file}.${process.pid}.tmp`;
    fs.writeFileSync(tmp, JSON.stringify(value), 'utf8');
    fs.renameSync(tmp, file);
    try { fs.chmodSync(file, 0o600); } catch {}
  } catch {}
}

function readCachedRecord(provider, ttl) {
  const file = cachePath(provider);
  try {
    const age = Date.now() / 1000 - fs.statSync(file).mtimeMs / 1000;
    if (age >= ttl) return null;
    const data = readJson(file);
    return data && typeof data.record === 'object' && !Array.isArray(data.record) ? data.record : null;
  } catch { return null; }
}

function isAvailableRecord(record) {
  return record && typeof record === 'object' && !Array.isArray(record) && record.available === true;
}

function readFreshCache(provider, ttl = EXTERNAL_USAGE_CACHE_TTL) {
  try {
    const file = cachePath(provider);
    const age = Date.now() / 1000 - fs.statSync(file).mtimeMs / 1000;
    if (age > ttl) return [null, null];
    return [readJson(file), Math.max(0, Math.trunc(age))];
  } catch {
    return [null, null];
  }
}

function readCachedExternalUsage(config = {}) {
  try {
    const external = config && typeof config.external_providers === 'object' ? config.external_providers : null;
    if (!external || external.enabled !== true) return [];

    const records = [];
    for (const provider of ['codex', 'glm', 'droid', 'antigravity']) {
      const providerConfig = external[provider];
      if (!providerConfig || providerConfig.enabled !== true) continue;

      const [data, stale] = readFreshCache(provider);
      if (!data || typeof data !== 'object' || Array.isArray(data)) continue;

      let record = null;
      if (provider === 'glm') {
        const response = data.response && typeof data.response === 'object' && !Array.isArray(data.response) ? data.response : null;
        if (response) record = parseGlmQuotaResponse(response, stale);
      } else {
        record = data.record && typeof data.record === 'object' && !Array.isArray(data.record) ? data.record : null;
      }

      if (isAvailableRecord(record)) records.push(record);
    }
    return records;
  } catch {
    return [];
  }
}

function writeCachedRecord(provider, record) {
  if (record && record.available) writeJson(cachePath(provider), { cached_at: Date.now() / 1000, record });
}

function isoSeconds(value) {
  if (!value) return null;
  const ms = Date.parse(String(value));
  return Number.isFinite(ms) ? ms / 1000 : null;
}

function normalizeCodexTokenCountEvent(event, staleSeconds = null, nowSeconds = null) {
  const payload = event && typeof event === 'object' ? event.payload : null;
  if (!payload || typeof payload !== 'object' || payload.type !== 'token_count') return unavailable('codex');

  const rateLimits = payload.rate_limits || {};
  const primary = rateLimits.primary || {};
  const secondary = rateLimits.secondary || {};
  const fiveHour = usageWindow(primary.used_percent, primary.resets_at, codexWindowLabel(primary.window_minutes, '5h'));
  const weekly = usageWindow(secondary.used_percent, secondary.resets_at, codexWindowLabel(secondary.window_minutes, '7d'));
  const tokens = payload.info && payload.info.total_token_usage && typeof payload.info.total_token_usage === 'object'
    ? payload.info.total_token_usage
    : null;

  let stale = staleSeconds;
  if (stale == null) {
    const ts = isoSeconds(event.timestamp);
    if (ts != null) stale = Math.max(0, Math.trunc((nowSeconds || Date.now() / 1000) - ts));
  }

  return {
    ...unavailable('codex'),
    available: Boolean(fiveHour || weekly || tokens),
    five_hour: fiveHour,
    weekly,
    plan: rateLimits.plan_type || null,
    tokens,
    stale_seconds: stale,
  };
}

function parseCodexTokenCountLine(line, staleSeconds = null, nowSeconds = null) {
  try { return normalizeCodexTokenCountEvent(JSON.parse(line), staleSeconds, nowSeconds); } catch { return unavailable('codex'); }
}

function newestCodexRollout() {
  const sessions = path.join(homeDir(), '.codex', 'sessions');
  const files = [];
  function walk(dir, depth) {
    if (depth > 4) return;
    let entries;
    try { entries = fs.readdirSync(dir, { withFileTypes: true }); } catch { return; }
    for (const entry of entries) {
      const file = path.join(dir, entry.name);
      if (entry.isDirectory()) walk(file, depth + 1);
      else if (/^rollout-.*\.jsonl$/.test(entry.name)) {
        try { files.push({ file, mtime: fs.statSync(file).mtimeMs }); } catch {}
      }
    }
  }
  walk(sessions, 0);
  if (!files.length) return null;
  files.sort((a, b) => (b.mtime - a.mtime) || b.file.localeCompare(a.file));
  return files[0].file;
}

function getCodexUsage(config = {}) {
  try {
    const cached = readCachedRecord('codex', LOCAL_CACHE_TTL);
    if (cached) return cached;

    const rollout = newestCodexRollout();
    if (!rollout) return unavailable('codex');
    let lastEvent = null;
    for (const line of fs.readFileSync(rollout, 'utf8').split(/\r?\n/)) {
      if (!line) continue;
      try {
        const event = JSON.parse(line);
        if (event && event.payload && event.payload.type === 'token_count') lastEvent = event;
      } catch {}
    }
    if (!lastEvent) return unavailable('codex');
    const stale = Math.max(0, Math.trunc(Date.now() / 1000 - fs.statSync(rollout).mtimeMs / 1000));
    const record = normalizeCodexTokenCountEvent(lastEvent, stale);
    writeCachedRecord('codex', record);
    return record;
  } catch { return unavailable('codex'); }
}

function parseGlmQuotaResponse(data, staleSeconds = null) {
  let body = data;
  try { if (typeof body === 'string') body = JSON.parse(body); } catch { return unavailable('glm'); }
  if (!body || typeof body !== 'object') return unavailable('glm');

  const dataObj = body.data && typeof body.data === 'object' ? body.data : {};
  const limits = Array.isArray(dataObj.limits) ? dataObj.limits : [];
  let fiveHour = null, weekly = null;
  for (const item of limits) {
    if (!item || typeof item !== 'object') continue;
    let reset = null;
    const ms = Number(item.nextResetTime);
    if (Number.isFinite(ms)) reset = Math.round(ms / 1000);
    if (item.type === 'TIME_LIMIT') fiveHour = usageWindow(item.percentage, reset, '5h');
    else if (item.type === 'TOKENS_LIMIT') weekly = usageWindow(item.percentage, reset, 'tok');
  }

  return {
    ...unavailable('glm'),
    available: Boolean(fiveHour || weekly),
    five_hour: fiveHour,
    weekly,
    display: 'compact',
    metrics: [
      fiveHour ? { label: '5h', used_pct: fiveHour.used_pct, resets_at: fiveHour.resets_at } : null,
      weekly ? { label: 'tok', used_pct: weekly.used_pct, resets_at: weekly.resets_at } : null,
    ].filter(Boolean),
    plan: dataObj.level || body.level || null,
    stale_seconds: staleSeconds,
  };
}

function readProviderEnvKey() {
  const file = path.join(homeDir(), '.codex', 'providers.env');
  let text = '';
  try { text = fs.readFileSync(file, 'utf8'); } catch { return ''; }
  for (const line of text.split(/\r?\n/)) {
    const match = line.match(/^\s*(?:export\s+)?(ZAI_API_KEY|ZHIPU_API_KEY)\s*=\s*(.+?)\s*$/);
    if (!match) continue;
    const value = match[2].trim().replace(/^['"]|['"]$/g, '');
    if (value) return value;
  }
  return '';
}

function glmKey(config = {}) {
  return process.env.ZAI_API_KEY || process.env.ZHIPU_API_KEY || String(config.api_key || '').trim() || readProviderEnvKey();
}

function readGlmCache() {
  const file = cachePath('glm');
  try {
    const data = readJson(file);
    const response = data && data.response && typeof data.response === 'object' ? data.response : null;
    if (!response) return [null, null];
    const stale = Math.max(0, Math.trunc(Date.now() / 1000 - fs.statSync(file).mtimeMs / 1000));
    return [response, stale];
  } catch { return [null, null]; }
}

function fetchGlmResponse(config, key) {
  const baseUrl = String((config && config.base_url) || 'https://api.z.ai').replace(/\/+$/, '');
  const url = new URL(`${baseUrl}${GLM_ENDPOINT}`);
  return new Promise((resolve, reject) => {
    const req = https.request(url, {
      method: 'GET',
      timeout: 1500,
      headers: {
        Authorization: key,
        'Accept-Language': 'en-US,en',
        'Content-Type': 'application/json',
      },
    }, res => {
      let body = '';
      res.setEncoding('utf8');
      res.on('data', chunk => { body += chunk; });
      res.on('end', () => {
        try { resolve(JSON.parse(body)); } catch (err) { reject(err); }
      });
    });
    req.on('timeout', () => req.destroy(new Error('timeout')));
    req.on('error', reject);
    req.end();
  });
}

async function getGlmUsage(config = {}) {
  try {
    const key = glmKey(config);
    if (!key) return unavailable('glm');

    const [cachedResponse, stale] = readGlmCache();
    if (cachedResponse && stale != null && stale < GLM_CACHE_TTL) {
      return parseGlmQuotaResponse(cachedResponse, stale);
    }

    try {
      const response = await fetchGlmResponse(config, key);
      writeJson(cachePath('glm'), { cached_at: Date.now() / 1000, response });
      return parseGlmQuotaResponse(response, 0);
    } catch {
      if (cachedResponse) return parseGlmQuotaResponse(cachedResponse, stale);
      return unavailable('glm');
    }
  } catch { return unavailable('glm'); }
}

function projectSlug(cwd) {
  return String(cwd || '').replace(/[^A-Za-z0-9]/g, '-');
}

function asNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function normalizeDroidTokens(raw) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
  const mapping = {
    input: ['inputTokens', 'input_tokens', 'input'],
    output: ['outputTokens', 'output_tokens', 'output'],
    cache_creation: ['cacheCreationTokens', 'cache_creation_tokens'],
    cache_read: ['cacheReadTokens', 'cache_read_tokens'],
    thinking: ['thinkingTokens', 'reasoningTokens', 'reasoning_output_tokens'],
    factory_credits: ['factoryCredits', 'factory_credits'],
  };
  const tokens = {};
  for (const [outKey, keys] of Object.entries(mapping)) {
    for (const key of keys) {
      const number = asNumber(raw[key]);
      if (number != null) { tokens[outKey] = number; break; }
    }
  }
  let total = Object.entries(tokens).reduce((sum, [key, value]) => key === 'factory_credits' ? sum : sum + value, 0);
  for (const key of ['totalTokens', 'total_tokens', 'total']) {
    const number = asNumber(raw[key]);
    if (number != null) { total = number; break; }
  }
  const anyPositive = Object.entries(tokens).some(([key, value]) => key !== 'factory_credits' && value > 0);
  if (total <= 0 && !anyPositive) return null;
  tokens.total = total;
  return tokens;
}

function findTokenDict(value) {
  if (!value || typeof value !== 'object') return null;
  const direct = normalizeDroidTokens(value);
  if (direct) return direct;
  if (Array.isArray(value)) {
    for (const item of value) {
      const found = findTokenDict(item);
      if (found) return found;
    }
    return null;
  }
  for (const key of ['inclusiveTokenUsage', 'tokenUsage', 'usage', 'tokens']) {
    const found = normalizeDroidTokens(value[key]);
    if (found) return found;
  }
  for (const child of Object.values(value)) {
    const found = findTokenDict(child);
    if (found) return found;
  }
  return null;
}

function droidSettingsCandidates() {
  const factory = path.join(homeDir(), '.factory');
  const candidates = [];
  const index = readJson(path.join(factory, 'sessions-index.json'));
  if (index && Array.isArray(index.entries)) {
    for (const entry of [...index.entries].sort((a, b) => Number(b.settingsMtime || b.mtime || 0) - Number(a.settingsMtime || a.mtime || 0)).slice(0, 20)) {
      if (!entry || !entry.sessionId) continue;
      candidates.push(path.join(factory, 'sessions', projectSlug(entry.cwd || ''), `${entry.sessionId}.settings.json`));
    }
  }
  try {
    const sessions = path.join(factory, 'sessions');
    const files = [];
    for (const project of fs.readdirSync(sessions)) {
      const dir = path.join(sessions, project);
      let st;
      try { st = fs.statSync(dir); } catch { continue; }
      if (!st.isDirectory()) continue;
      for (const name of fs.readdirSync(dir)) {
        if (!name.endsWith('.settings.json')) continue;
        const file = path.join(dir, name);
        try { files.push({ file, mtime: fs.statSync(file).mtimeMs }); } catch {}
      }
    }
    files.sort((a, b) => b.mtime - a.mtime);
    candidates.push(...files.slice(0, 20).map(item => item.file));
  } catch {}
  return candidates;
}

function getDroidUsage(config = {}) {
  try {
    const cached = readCachedRecord('droid', LOCAL_CACHE_TTL);
    if (cached) return cached;

    const seen = new Set();
    for (const file of droidSettingsCandidates()) {
      if (seen.has(file)) continue;
      seen.add(file);
      const data = readJson(file);
      const tokens = findTokenDict(data);
      if (!tokens) continue;
      const record = {
        ...unavailable('droid'),
        available: true,
        tokens,
        stale_seconds: Math.max(0, Math.trunc(Date.now() / 1000 - fs.statSync(file).mtimeMs / 1000)),
      };
      writeCachedRecord('droid', record);
      return record;
    }
    return unavailable('droid');
  } catch { return unavailable('droid'); }
}

function decodeAntigravityValue(value) {
  try {
    if (Buffer.isBuffer(value)) value = value.toString('utf8');
    if (typeof value === 'string') {
      const text = value.trim();
      if (!text) return null;
      return JSON.parse(text);
    }
    if (value && typeof value === 'object') return value;
  } catch {}
  return null;
}

function normalizeAntigravityReset(value) {
  if (value == null || value === '') return null;
  const number = Number(value);
  if (Number.isFinite(number)) {
    const seconds = number > 100_000_000_000 ? number / 1000 : number;
    return Math.trunc(seconds);
  }
  const ms = Date.parse(String(value));
  return Number.isFinite(ms) ? Math.trunc(ms / 1000) : null;
}

function findAntigravityReset(obj) {
  if (!obj || typeof obj !== 'object' || Array.isArray(obj)) return null;
  for (const key of ['resetsAt', 'resets_at', 'resetAt', 'nextResetTime', 'nextResetAt', 'nextReset', 'resetTime']) {
    const reset = normalizeAntigravityReset(obj[key]);
    if (reset != null) return reset;
  }
  return null;
}

function antigravityPct(obj) {
  if (!obj || typeof obj !== 'object' || Array.isArray(obj)) return null;
  for (const key of ['usedPercent', 'used_percent', 'percentage', 'percent', 'pct', 'usedPercentage', 'usedPct']) {
    const pct = asNumber(obj[key]);
    if (pct != null) return pct;
  }
  const used = asNumber(obj.used);
  const remaining = asNumber(obj.remaining);
  const limit = asNumber(obj.limit);
  if (used != null && limit != null && limit > 0) return (used / limit) * 100;
  if (remaining != null && limit != null && limit > 0) return ((limit - remaining) / limit) * 100;
  if (used != null && used >= 0 && used <= 100) return used;
  return null;
}

function classifyAntigravityModel(pathParts, obj) {
  const hints = [];
  for (const value of pathParts) hints.push(String(value || ''));
  if (obj && typeof obj === 'object' && !Array.isArray(obj)) {
    for (const key of ['key', 'name', 'label', 'model', 'modelName', 'displayName', 'id', 'type']) {
      if (obj[key] != null) hints.push(String(obj[key]));
    }
  }
  const text = hints.join(' ').toLowerCase();
  if (text.includes('flash')) return 'Flash';
  if (text.includes('opus') || text.includes('claude') || text.includes('sonnet')) return 'Opus';
  if (/(^|[^a-z])pro([^a-z]|$)/.test(text)) return 'Pro';
  return null;
}

function collectAntigravityModelMetrics(value, pathParts, found) {
  if (Array.isArray(value)) {
    value.forEach((item, idx) => collectAntigravityModelMetrics(item, [...pathParts, String(idx)], found));
    return;
  }
  if (!value || typeof value !== 'object') return;

  const pct = antigravityPct(value);
  const label = pct == null ? null : classifyAntigravityModel(pathParts, value);
  if (label && !found[label]) {
    const metric = usageWindow(pct, findAntigravityReset(value), label);
    if (metric) found[label] = metric;
  }

  for (const [key, childValue] of Object.entries(value)) {
    if (childValue && typeof childValue === 'object') {
      collectAntigravityModelMetrics(childValue, [...pathParts, key], found);
    }
  }
}

function parseAntigravityModels(raw) {
  try {
    if (!raw || typeof raw !== 'object') return null;
    const found = {};
    collectAntigravityModelMetrics(raw, [], found);
    const metrics = ['Flash', 'Pro', 'Opus'].map(label => found[label]).filter(Boolean);
    return metrics.length ? metrics : null;
  } catch {
    return null;
  }
}

function classifyAntigravityWindow(pathParts, obj) {
  const hints = [];
  for (const value of pathParts) hints.push(String(value || ''));
  if (obj && typeof obj === 'object' && !Array.isArray(obj)) {
    for (const key of ['type', 'window', 'period', 'scope', 'name', 'limitType']) {
      if (obj[key] != null) hints.push(String(obj[key]));
    }
  }
  const text = hints.join(' ').toLowerCase();
  if (text.includes('weekly') || /\b(week|seven|7d|wk)\b/.test(text)) return 'weekly';
  if (
    text.includes('sprint') ||
    text.includes('five_hour') ||
    text.includes('five-hour') ||
    text.includes('five hour') ||
    text.includes('fivehour') ||
    text.includes('time_limit') ||
    text.includes('time-limit') ||
    text.includes('time limit') ||
    /\b5h\b/.test(text)
  ) return 'five_hour';
  return null;
}

function findAntigravityWindows(value, pathParts = []) {
  const found = { five_hour: null, weekly: null };
  if (Array.isArray(value)) {
    for (const item of value) {
      const child = findAntigravityWindows(item, pathParts);
      if (!found.five_hour && child.five_hour) found.five_hour = child.five_hour;
      if (!found.weekly && child.weekly) found.weekly = child.weekly;
    }
    return found;
  }
  if (!value || typeof value !== 'object') return found;

  const pct = antigravityPct(value);
  const kind = pct == null ? null : classifyAntigravityWindow(pathParts, value);
  if (kind) found[kind] = usageWindow(pct, findAntigravityReset(value), kind === 'weekly' ? 'wk' : '5h');

  for (const [key, childValue] of Object.entries(value)) {
    if (!childValue || typeof childValue !== 'object') continue;
    const child = findAntigravityWindows(childValue, [...pathParts, key]);
    if (!found.five_hour && child.five_hour) found.five_hour = child.five_hour;
    if (!found.weekly && child.weekly) found.weekly = child.weekly;
  }
  return found;
}

function parseAntigravityItemTable(rows) {
  try {
    if (!Array.isArray(rows)) return unavailable('antigravity');
    let fiveHour = null, weekly = null;
    const modelMetrics = [];
    for (const row of rows) {
      if (!row) continue;
      const key = Array.isArray(row) ? row[0] : row.key;
      const value = decodeAntigravityValue(Array.isArray(row) ? row[1] : row.value);
      if (value == null) continue;
      const metrics = parseAntigravityModels(value);
      if (metrics) {
        for (const metric of metrics) {
          if (!modelMetrics.some(existing => existing.label === metric.label)) modelMetrics.push(metric);
        }
      }
      const found = findAntigravityWindows(value, [key]);
      if (!fiveHour && found.five_hour) fiveHour = found.five_hour;
      if (!weekly && found.weekly) weekly = found.weekly;
    }
    if (modelMetrics.length) {
      const order = { Flash: 0, Pro: 1, Opus: 2 };
      modelMetrics.sort((left, right) => (order[left.label] ?? 99) - (order[right.label] ?? 99));
      return {
        ...unavailable('antigravity'),
        label: 'AGY',
        available: true,
        five_hour: fiveHour,
        weekly,
        display: 'compact',
        metrics: modelMetrics.map(metric => ({
          label: metric.label,
          used_pct: metric.used_pct,
          resets_at: metric.resets_at == null ? null : metric.resets_at,
        })),
      };
    }
    if (!fiveHour && !weekly) return unavailable('antigravity');
    return {
      ...unavailable('antigravity'),
      available: true,
      five_hour: fiveHour,
      weekly,
    };
  } catch { return unavailable('antigravity'); }
}

function antigravityDbPath() {
  if (process.platform === 'darwin') {
    return path.join(homeDir(), 'Library', 'Application Support', 'Antigravity', 'User', 'globalStorage', 'state.vscdb');
  }
  if (process.platform === 'win32' && process.env.APPDATA) {
    return path.join(process.env.APPDATA, 'Antigravity', 'User', 'globalStorage', 'state.vscdb');
  }
  return path.join(homeDir(), '.config', 'Antigravity', 'User', 'globalStorage', 'state.vscdb');
}

function antigravityQuery() {
  const patterns = ['%antigravity%', '%usage%', '%quota%', '%limit%', '%credit%', '%ratelimit%'];
  const where = patterns.map(pattern => `LOWER(key) LIKE '${pattern}'`).join(' OR ');
  return `SELECT key,value FROM ItemTable WHERE ${where};`;
}

function parseSqliteRows(output) {
  return String(output || '').split(/\r?\n/)
    .map(line => {
      const idx = line.indexOf('|');
      if (idx < 0) return null;
      return { key: line.slice(0, idx), value: line.slice(idx + 1) };
    })
    .filter(Boolean);
}

// Map an `antigravity-usage quota --json` snapshot (models[].remainingPercentage
// is a 0..1 fraction) into our Opus/Pro/Flash compact metrics.
function mapAntigravitySnapshot(snapshot) {
  if (!snapshot || typeof snapshot !== 'object') return null;
  const models = Array.isArray(snapshot.models) ? snapshot.models : [];
  const pick = { Opus: null, Pro: null, Flash: null };
  for (const m of models) {
    if (!m || typeof m !== 'object' || m.isAutocompleteOnly) continue;
    const id = `${m.label || ''} ${m.modelId || ''}`.toLowerCase();
    let group = null;
    if (id.includes('opus') || id.includes('claude') || id.includes('sonnet')) group = 'Opus';
    else if (id.includes('pro')) group = 'Pro';
    else if (id.includes('flash')) group = 'Flash';
    if (!group || pick[group]) continue;
    const frac = Number(m.remainingPercentage);
    if (!Number.isFinite(frac)) continue;
    let resetsAt = null;
    if (m.resetTime) { const ms = Date.parse(m.resetTime); if (Number.isFinite(ms)) resetsAt = Math.trunc(ms / 1000); }
    pick[group] = { label: group, used_pct: Math.max(0, Math.min(100, Math.round((1 - frac) * 100))), resets_at: resetsAt };
  }
  const metrics = ['Opus', 'Pro', 'Flash'].map(g => pick[g]).filter(Boolean);
  return metrics.length ? metrics : null;
}

// Antigravity quota via the `antigravity-usage` CLI (it owns OAuth refresh +
// local-IDE/cloud fallback). We cache BOTH hits and misses for GLM_CACHE_TTL so a
// logged-out machine never re-spawns the CLI on every render.
function getAntigravityUsage(config = {}) {
  try {
    const cached = readCachedRecord('antigravity', GLM_CACHE_TTL);
    if (cached) return cached;
    const bin = String((config && config.bin) || 'antigravity-usage');
    let out = '';
    try {
      out = execFileSync(bin, ['quota', '--json', '--method', 'auto'], {
        encoding: 'utf8', timeout: 5000, stdio: ['ignore', 'pipe', 'ignore'],
      });
    } catch (e) { out = (e && e.stdout) ? String(e.stdout) : ''; }
    let snapshot = null;
    try { snapshot = JSON.parse(out); } catch { snapshot = null; }
    const metrics = mapAntigravitySnapshot(snapshot);
    const record = metrics
      ? { ...unavailable('antigravity'), available: true, label: 'AGY', display: 'compact', metrics,
          plan: snapshot && snapshot.planType ? String(snapshot.planType) : null, source: 'api', stale_seconds: 0 }
      : unavailable('antigravity');
    writeJson(cachePath('antigravity'), { cached_at: Date.now() / 1000, record });
    return record;
  } catch { return unavailable('antigravity'); }
}

async function getProviderUsage(provider, config = {}) {
  try {
    if (provider === 'codex') return getCodexUsage(config);
    if (provider === 'glm') return getGlmUsage(config);
    if (provider === 'droid') return getDroidUsage(config);
    if (provider === 'antigravity') return getAntigravityUsage(config);
  } catch {}
  return PROVIDERS[provider] ? unavailable(provider) : null;
}

async function collectExternalUsage(config = {}) {
  const external = config && typeof config.external_providers === 'object' ? config.external_providers : null;
  if (!external || external.enabled !== true) return [];

  const records = [];
  for (const provider of ['codex', 'glm', 'droid', 'antigravity']) {
    const providerConfig = external[provider];
    if (!providerConfig || providerConfig.enabled !== true) continue;
    const record = await getProviderUsage(provider, providerConfig);
    if (record && typeof record === 'object') records.push(record);
  }
  return records;
}

module.exports = {
  unavailable,
  normalizeCodexTokenCountEvent,
  parseCodexTokenCountLine,
  getCodexUsage,
  parseGlmQuotaResponse,
  getGlmUsage,
  getDroidUsage,
  getAntigravityUsage,
  parseAntigravityItemTable,
  parseAntigravityModels,
  getProviderUsage,
  collectExternalUsage,
  readCachedExternalUsage,
  formatProviderRowParts,
};
