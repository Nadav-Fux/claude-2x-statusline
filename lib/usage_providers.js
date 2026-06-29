'use strict';

const fs = require('fs');
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
    plan: null,
    tokens: null,
    source,
    stale_seconds: null,
  };
}

function usageWindow(usedPct, resetsAt) {
  const pct = Number(usedPct);
  if (!Number.isFinite(pct)) return null;
  const reset = resetsAt == null ? null : Number(resetsAt);
  return { used_pct: Math.max(0, Math.min(100, pct)), resets_at: Number.isFinite(reset) ? Math.trunc(reset) : null };
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

function formatProviderRowParts(record, nowSec = Date.now() / 1000, options = {}) {
  if (!record || typeof record !== 'object' || !record.available) return null;
  const formatDuration = typeof options.formatDuration === 'function' ? options.formatDuration : defaultFormatDuration;
  const label = String(record.label || record.provider || '').trim() || 'provider';
  const labelWidth = Math.max(0, Math.trunc(numberOrZero(options.labelWidth)));
  const paddedLabel = label + ' '.repeat(Math.max(0, labelWidth - label.length));
  const parts = [{ kind: 'label', label: paddedLabel, rawLabel: label, plan: record.plan ? String(record.plan) : '' }];

  for (const [windowLabel, window] of [['5h', record.five_hour], ['7d', record.weekly]]) {
    if (!window || typeof window !== 'object' || Array.isArray(window)) continue;
    const pct = Math.max(0, Math.min(100, Math.round(numberOrZero(window.used_pct))));
    parts.push({
      kind: 'window',
      label: windowLabel,
      pct,
      resetText: resetCountdown(window.resets_at, nowSec, formatDuration),
    });
  }

  const hasWindow = parts.some(part => part.kind === 'window');
  const tokensTotal = providerTokenTotal(record.tokens);
  if (!hasWindow && tokensTotal > 0) parts.push({ kind: 'tokens', total: tokensTotal });
  if (parts.length <= 1) return null;

  const staleSeconds = record.stale_seconds == null ? null : numberOrZero(record.stale_seconds);
  const stale = staleSeconds != null && staleSeconds > 600;
  return { label, parts, stale, staleText: stale ? ' \u00b7stale' : '' };
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
  const fiveHour = usageWindow(primary.used_percent, primary.resets_at);
  const weekly = usageWindow(secondary.used_percent, secondary.resets_at);
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
    const win = usageWindow(item.percentage, reset);
    if (item.type === 'TIME_LIMIT') fiveHour = win;
    else if (item.type === 'TOKENS_LIMIT') weekly = win;
  }

  return {
    ...unavailable('glm'),
    available: Boolean(fiveHour || weekly),
    five_hour: fiveHour,
    weekly,
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

function antigravityDbPath() {
  if (process.platform === 'darwin') {
    return path.join(homeDir(), 'Library', 'Application Support', 'Antigravity', 'User', 'globalStorage', 'state.vscdb');
  }
  if (process.platform === 'win32' && process.env.APPDATA) {
    return path.join(process.env.APPDATA, 'Antigravity', 'User', 'globalStorage', 'state.vscdb');
  }
  return path.join(homeDir(), '.config', 'Antigravity', 'User', 'globalStorage', 'state.vscdb');
}

function getAntigravityUsage(config = {}) {
  try {
    const dbPath = antigravityDbPath();
    if (!fs.existsSync(dbPath)) return unavailable('antigravity');
    // TODO: Add a SQLite reader if Antigravity usage schema becomes stable.
    return unavailable('antigravity');
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
  getProviderUsage,
  collectExternalUsage,
  formatProviderRowParts,
};
