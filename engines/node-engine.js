#!/usr/bin/env node
/**
 * Claude Code statusline — Node.js engine (full feature parity with Python).
 * v2.2 — Peak hours, rate limits, rolling metrics, timeline, burn rate, cache.
 */

const { execFileSync, spawn } = require('child_process');
const crypto = require('crypto');
const fs = require('fs');
const os = require('os');
const path = require('path');
const https = require('https');
const rs = require(path.join(__dirname, '..', 'lib', 'rolling_state'));
const usageProviders = require(path.join(__dirname, '..', 'lib', 'usage_providers'));
const gatewayUtil = require(path.join(__dirname, '..', 'lib', 'gateway'));
const sessionCockpit = require(path.join(__dirname, '..', 'lib', 'session_cockpit'));
const jobMonitor = require(path.join(__dirname, '..', 'lib', 'job_monitor'));

// ── ANSI ──
const RST = '\x1b[0m', BOLD = '\x1b[1m', DIM = '\x1b[2m';
const RED = '\x1b[31m', GREEN = '\x1b[32m', YELLOW = '\x1b[33m';
const BLUE = '\x1b[34m', MAGENTA = '\x1b[35m', CYAN = '\x1b[36m';
const WHITE = '\x1b[38;2;220;220;220m';
// Truecolor purple — owner-requested addition to the palette (session-quality
// line: the ⚒ tool-call counter and the eff efficiency dots).
const PURPLE = '\x1b[38;2;178;148;255m';
const BG_GREEN = '\x1b[38;5;255;48;5;28m';
const BG_YELLOW = '\x1b[38;5;16;48;5;220m';
const BG_RED = '\x1b[38;5;255;48;5;124m';
const BG_GRAY = '\x1b[48;5;236m';
const BG_BLUE = '\x1b[38;5;255;48;5;27m';

// ── Config ──
const TIER_PRESETS = {
  minimal: ['model', 'context', 'workflows', 'tasks', 'git_branch', 'git_dirty', 'rate_limits', 'effort', 'env'],
  standard: ['model', 'context', 'vim_mode', 'agent', 'workflows', 'tasks', 'git_branch', 'git_dirty', 'cost', 'effort', 'env'],
  full: ['model', 'context', 'vim_mode', 'agent', 'workflows', 'tasks', 'git_branch', 'git_dirty', 'cost', 'usage_credits', 'effort', 'env'],
  // Line 1 stays clean: model, context, cost, effort, LOCAL, git. The Claude
  // rate-limit dashboard + external provider rows + metrics render below in
  // full mode; the promo banner is moved to the very last line (see main()).
  'multi-cli': ['model', 'context', 'cost', 'effort', 'env', 'git_branch', 'git_dirty'],
};

const DEFAULT_CONFIG = {
  tier: 'standard',
  mode: 'minimal',
  gateway_awareness: true,
  // fork note: override via schedule_url in config
  schedule_url: 'https://raw.githubusercontent.com/Nadav-Fux/claude-2x-statusline/main/schedule.json',
  schedule_cache_hours: 3,
  external_providers: {
    enabled: false,
    codex: { enabled: true },
    glm: { enabled: true, base_url: 'https://api.z.ai', api_key: '' },
    droid: { enabled: false },
    antigravity: { enabled: false },
  },
};

const DEFAULT_SCHEDULE = {
  v: 2, mode: 'peak_hours', default_tier: 'full',
  peak: { enabled: true, tz: 'America/Los_Angeles', days: [1,2,3,4,5], start: 5, end: 11,
    label_peak: 'Peak', label_offpeak: 'Off-Peak' },
  banner: { text: '', expires: '', color: 'yellow' },
  release: {},
  features: { show_peak_segment: true, show_rate_limits: true, show_timeline: true },
};

function normalizeSchedule(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const schedule = { ...DEFAULT_SCHEDULE, ...value };
  if (schedule.peak && typeof schedule.peak === 'object' && !Array.isArray(schedule.peak)) {
    schedule.peak = { ...DEFAULT_SCHEDULE.peak, ...schedule.peak };
  } else {
    schedule.peak = { ...DEFAULT_SCHEDULE.peak };
  }
  for (const key of ['features', 'banner', 'release', 'labels']) {
    if (!schedule[key] || typeof schedule[key] !== 'object' || Array.isArray(schedule[key])) {
      schedule[key] = { ...(DEFAULT_SCHEDULE[key] || {}) };
    }
  }
  return schedule;
}

function loadLocalVersion() {
  try {
    return JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'package.json'), 'utf8')).version || '';
  } catch { return ''; }
}
const CURRENT_VERSION = loadLocalVersion();
let wfCache = {};

// ── Version helpers ──
function parseVersion(value) {
  const core = String(value || '').split('-', 1)[0].split('+', 1)[0];
  return core.split('.').map(t => { const d = t.replace(/[^0-9]/g, ''); return d ? parseInt(d, 10) : 0; });
}
function compareVersions(left, right) {
  const lp = parseVersion(left), rp = parseVersion(right);
  const len = Math.max(lp.length, rp.length);
  while (lp.length < len) lp.push(0);
  while (rp.length < len) rp.push(0);
  for (let i = 0; i < len; i++) { if (lp[i] < rp[i]) return -1; if (lp[i] > rp[i]) return 1; }
  return 0;
}

function buildReleaseNotice(schedule) {
  const rel = schedule.release || {};
  const latest = String(rel.latest_version || '').trim();
  const minimum = String(rel.minimum_version || '').trim();
  if (!CURRENT_VERSION || (!latest && !minimum)) return '';
  const cmd = String(rel.command || '/statusline-update').trim() || '/statusline-update';
  const target = latest || minimum;
  if (minimum && compareVersions(CURRENT_VERSION, minimum) < 0) {
    return `${BG_RED} ${rel.required_text || `Update required v${target} via ${cmd}`} ${RST}`;
  }
  if (latest && compareVersions(CURRENT_VERSION, latest) < 0) {
    return `${BG_YELLOW} ${rel.available_text || `Update available v${latest} via ${cmd}`} ${RST}`;
  }
  return '';
}

// ── Config ──
const HOME = process.env.HOME || process.env.USERPROFILE;
const CLAUDE_DIR = path.join(HOME, '.claude');

function loadConfig() {
  try { return { ...DEFAULT_CONFIG, ...JSON.parse(fs.readFileSync(path.join(CLAUDE_DIR, 'statusline-config.json'), 'utf8')) }; }
  catch { return { ...DEFAULT_CONFIG }; }
}

function loadClaudeSettings() {
  try {
    const data = JSON.parse(fs.readFileSync(path.join(CLAUDE_DIR, 'settings.json'), 'utf8'));
    return data && typeof data === 'object' && !Array.isArray(data) ? data : {};
  } catch { return {}; }
}

function getEnabled(config, schedule) {
  const tier = config.tier || 'standard';
  const features = schedule.features || {};
  if (tier === 'custom') {
    return Object.entries(config.segments || {}).filter(([,v]) => v).map(([k]) => k === 'promo_2x' ? 'peak_hours' : k);
  }
  let enabled = [...(TIER_PRESETS[tier] || TIER_PRESETS.standard)];
  if (!features.show_peak_segment) enabled = enabled.filter(s => s !== 'peak_hours');
  if (!features.show_rate_limits) enabled = enabled.filter(s => s !== 'rate_limits');
  return enabled;
}

// ── Schedule ──
function loadSchedule(config) {
  const cachePath = path.join(CLAUDE_DIR, 'statusline-schedule.json');
  const configCacheHours = config.schedule_cache_hours || 3;
  try {
    const stat = fs.statSync(cachePath);
    const ageHours = (Date.now() - stat.mtimeMs) / 3600000;
    const cached = normalizeSchedule(JSON.parse(fs.readFileSync(cachePath, 'utf8')));
    if (cached) {
      const remoteTtl = cached.cache_hours;
      const effectiveTtl = remoteTtl != null ? remoteTtl : configCacheHours;
      if (ageHours < effectiveTtl) return cached;
    }
  } catch {}
  try {
    const url = config.schedule_url || DEFAULT_CONFIG.schedule_url;
    const result = execFileSync('curl', ['-s', '--max-time', '3', url], { timeout: 5000, encoding: 'utf8' });
    if (result && result.trim().startsWith('{')) {
      const data = normalizeSchedule(JSON.parse(result));
      if (!data) throw new Error('invalid schedule payload');
      fs.writeFileSync(cachePath, JSON.stringify(data, null, 2));
      return data;
    }
  } catch {}
  try {
    const cached = normalizeSchedule(JSON.parse(fs.readFileSync(cachePath, 'utf8')));
    if (cached) return cached;
  } catch {}
  return DEFAULT_SCHEDULE;
}

// ── Helpers ──
function fmtDur(mins) { const h = Math.floor(mins/60), m = mins%60; return h > 0 ? `${h}h ${String(m).padStart(2,'0')}m` : `${m}m`; }
function fmtSecs(s) { const h=Math.floor(s/3600), m=Math.floor((s%3600)/60), sec=s%60; return h>0?`${h}h${String(m).padStart(2,'0')}m`:m>0?`${m}m${String(sec).padStart(2,'0')}s`:`${sec}s`; }
// Window-duration rule for usage-bar color thresholds (see colorPct). A label
// naming a sub-day window ('5h', '12h', ...) is SHORT. Every other label --
// '7d'/'30d' (Codex/Antigravity), 'weekly'/'wk' (Claude/Antigravity), GLM's
// token-quota 'tok', Copilot's monthly meter -- is LONG: it covers a
// week/month/token-quota, not hours, so it should warn earlier. Mirrors the
// existing 5h-vs-longer split used for reset-clock formatting
// (resetStyleForLabel in lib/usage_providers). An unlabeled/unrecognized bar
// defaults to SHORT (today's thresholds) rather than guessing.
function isLongWindowLabel(label) {
  const text = String(label || '').trim().toLowerCase();
  if (!text) return false;
  return !/^\d+h$/.test(text);
}

// Usage-bar color thresholds. Windows longer than a day (weekly/monthly/
// token-quota) warn earlier -- red >=75 / yellow >=45 -- than sub-day windows
// like the Claude 5h bucket, which keep the tighter red >=80 / yellow >=50.
// Pass longWindow=true for any weekly-or-longer bar; see isLongWindowLabel
// for the label rule that decides this at the call site.
function colorPct(p, longWindow = false) {
  if (longWindow) return p >= 75 ? RED : p >= 45 ? YELLOW : GREEN;
  return p >= 80 ? RED : p >= 50 ? YELLOW : GREEN;
}
function git(...args) { try { return execFileSync('git', args, { timeout: 2000, encoding: 'utf8' }).trim(); } catch { return ''; } }
function fmtTokens(n) { return n >= 1e6 ? `${(n/1e6).toFixed(1)}M` : n >= 1e3 ? `${Math.floor(n/1e3)}K` : String(n); }
function toNum(value, fallback = 0) { const n = Number(value); return Number.isFinite(n) ? n : fallback; }
function localDateStr(d) { return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; }

function parseGitShortstat(text) {
  const s = String(text || '');
  const read = re => {
    const match = s.match(re);
    return match ? parseInt(match[1], 10) || 0 : 0;
  };
  return {
    insertions: read(/(\d+)\s+insertions?\(\+\)/),
    deletions: read(/(\d+)\s+deletions?\(-\)/),
    files: read(/(\d+)\s+files?\s+changed/),
  };
}

function repoCwd(ctx) {
  const stdin = (ctx || {}).stdin || {};
  const workspace = stdin.workspace && typeof stdin.workspace === 'object' ? stdin.workspace : {};
  return String(stdin.cwd || workspace.current_dir || process.cwd() || '');
}

function fmtHour(h) {
  h = ((h % 24) + 24) % 24;
  const hInt = Math.floor(h), mInt = Math.floor((h - hInt) * 60);
  const ampm = hInt < 12 ? 'am' : 'pm', display = hInt % 12 || 12;
  return mInt ? `${display}:${String(mInt).padStart(2,'0')}${ampm}` : `${display}${ampm}`;
}

function buildUsageBar(pct, width = 10, longWindow = false) {
  pct = Math.max(0, Math.min(100, pct));
  const filled = Math.floor(pct * width / 100), empty = width - filled;
  return `${colorPct(pct, longWindow)}${'\u25b0'.repeat(filled)}${DIM}${'\u25b1'.repeat(empty)}${RST}`;
}

// \u2500\u2500 Responsive width (mirror of python-engine resolve_render_width/reflow_parts) \u2500\u2500
const ANSI_RE = /\x1b\[[0-9;]*m/g;
function isWideChar(cp) {
  return (
    (cp >= 0x1100 && cp <= 0x115F) || (cp >= 0x2E80 && cp <= 0x303E) ||
    (cp >= 0x3041 && cp <= 0x33FF) || (cp >= 0x3400 && cp <= 0x4DBF) ||
    (cp >= 0x4E00 && cp <= 0x9FFF) || (cp >= 0xA000 && cp <= 0xA4CF) ||
    (cp >= 0xAC00 && cp <= 0xD7A3) || (cp >= 0xF900 && cp <= 0xFAFF) ||
    (cp >= 0xFE30 && cp <= 0xFE4F) || (cp >= 0xFF00 && cp <= 0xFF60) ||
    (cp >= 0xFFE0 && cp <= 0xFFE6) || (cp >= 0x1F000 && cp <= 0x1FAFF)
  );
}
function visibleWidth(s) {
  let w = 0;
  for (const ch of s.replace(ANSI_RE, '')) w += isWideChar(ch.codePointAt(0)) ? 2 : 1;
  return w;
}
function resolveRenderWidth(config) {
  if (config.reflow === false) return 0;
  let cols = parseInt(process.env.COLUMNS || '0', 10); if (!Number.isFinite(cols) || cols < 0) cols = 0;
  let cap = parseInt(config.max_width || '0', 10); if (!Number.isFinite(cap) || cap < 0) cap = 0;
  if (cols > 0 && cap > 0) return Math.min(cols, cap);
  return cols || cap;
}
function reflowParts(parts, sep, width) {
  const lines = []; let cur = [], curW = 0; const sepW = visibleWidth(sep);
  for (const p of parts) {
    const pw = visibleWidth(p);
    const add = cur.length ? pw + sepW : pw;
    if (cur.length && curW + add > width) { lines.push(cur.join(sep)); cur = [p]; curW = pw; }
    else { cur.push(p); curW += add; }
  }
  if (cur.length) lines.push(cur.join(sep));
  return lines;
}

// Bordered dashboard row(s): one "│ ▸ a · b · c │" line, or several bordered
// rows when it would exceed width. Mirror of python render_dashboard_line.
function renderDashboardLine(parts, width, trailing = '') {
  if (!parts.length) return '';
  const border = `${DIM}│${RST}`;
  const head = `${border} ${GREEN}▸${RST} `;
  const cont = `${border}   `;
  const sep = ` ${DIM}·${RST} `;
  const oneLine = `${head}${parts.join(sep)}${trailing} ${border}`;
  if (width <= 0 || visibleWidth(oneLine) <= width) return oneLine;
  // Reserve columns for the prefix and the closing " │" so rows stay <= width.
  const avail = Math.max(1, width - visibleWidth(head) - 2);
  const rows = reflowParts(parts, sep, avail);
  const last = rows.length - 1;
  const out = rows.map((row, i) => `${i === 0 ? head : cont}${row}${i === last ? trailing : ''} ${border}`);
  return out.join('\n');
}

// ── Timezone ──
function getLocalTime() {
  const now = new Date();
  const offsetHours = -now.getTimezoneOffset() / 60;
  const tzName = Intl.DateTimeFormat().resolvedOptions().timeZone || `UTC${offsetHours >= 0 ? '+' : ''}${offsetHours}`;
  return { now, tzName, offsetHours };
}

function getPacificOffset() {
  const now = new Date(), year = now.getUTCFullYear();
  const mar1 = new Date(Date.UTC(year, 2, 1));
  const dstStart = new Date(Date.UTC(year, 2, 1 + ((7 - mar1.getUTCDay()) % 7) + 7, 10));
  const nov1 = new Date(Date.UTC(year, 10, 1));
  const dstEnd = new Date(Date.UTC(year, 10, 1 + ((7 - nov1.getUTCDay()) % 7), 9));
  return (now >= dstStart && now < dstEnd) ? -7 : -8;
}

function getSourceOffset(tz) {
  if (!tz || tz === 'America/Los_Angeles') return getPacificOffset();
  if (tz === 'UTC' || tz === 'Etc/UTC') return 0;
  const p = getPacificOffset();
  return { 'America/New_York': p+3, 'America/Chicago': p+2, 'America/Denver': p+1 }[tz] ?? p;
}

function peakHoursToLocal(schedule, localOffset) {
  const peak = schedule.peak || {};
  const srcOffset = getSourceOffset(peak.tz);
  const rawStart = (peak.start || 5) - srcOffset + localOffset;
  return {
    startLocal: ((rawStart % 24) + 24) % 24,
    endLocal: (((peak.end || 11) - srcOffset + localOffset) % 24 + 24) % 24,
    peakDayOffset: Math.floor(rawStart / 24),
  };
}

function shiftWeekday(d, delta) { return ((d - 1 + delta) % 7 + 7) % 7 + 1; }
function minsUntilNextPeak(now, peakDays, startHour) {
  const hour = now.getHours() + now.getMinutes() / 60;
  const wd = now.getDay() === 0 ? 7 : now.getDay();
  for (let o = 1; o <= 7; o++) {
    const nd = ((wd - 1 + o) % 7) + 1;
    if (peakDays.includes(nd)) return Math.floor((24 - hour) * 60) + (o - 1) * 1440 + Math.floor(startHour * 60);
  }
  return 0;
}

// ── OAuth ──
function getOAuthToken() {
  const env = process.env.CLAUDE_CODE_OAUTH_TOKEN;
  if (env) return env;
  try {
    const creds = JSON.parse(fs.readFileSync(path.join(CLAUDE_DIR, '.credentials.json'), 'utf8'));
    const t = creds?.claudeAiOauth?.accessToken;
    if (t) return t;
  } catch {}
  if (process.platform === 'darwin') {
    try {
      const r = execFileSync('security', ['find-generic-password', '-s', 'Claude Code-credentials', '-w'], { timeout: 3000, encoding: 'utf8' });
      if (r.trim()) { const d = JSON.parse(r.trim()); if (d?.claudeAiOauth?.accessToken) return d.claudeAiOauth.accessToken; }
    } catch {}
  }
  return '';
}

function formatReset(isoStr, style) {
  if (!isoStr || isoStr === 'null') return '';
  try {
    const d = new Date(isoStr.replace('Z', '+00:00'));
    const local = new Date(d.getTime() + d.getTimezoneOffset() * -60000);
    const h = local.getHours() % 12 || 12, ampm = local.getHours() < 12 ? 'am' : 'pm';
    if (style === 'time') return `${h}:${String(local.getMinutes()).padStart(2, '0')}${ampm}`;
    return `${local.getDate()}/${local.getMonth() + 1} ${h}:${String(local.getMinutes()).padStart(2, '0')}${ampm}`;
  } catch { return ''; }
}

// ── Workflow helpers ──
const USAGE_RE = /"usage"\s*:\s*\{\s*"input_tokens"\s*:\s*(\d+)\s*,\s*"cache_creation_input_tokens"\s*:\s*(\d+)\s*,\s*"cache_read_input_tokens"\s*:\s*(\d+)\s*,\s*"output_tokens"\s*:\s*(\d+)/g;

// A tool-use content block inside a transcript JSONL line, e.g.
// {"type":"tool_use","id":"toolu_...",...}. Matched as raw text (not parsed
// JSON) so a multi-MB transcript is one regex scan, not N JSON.parse calls --
// same tradeoff as USAGE_RE above. Mirrors python's _TOOL_USE_RE.
const TOOL_USE_RE = /"type"\s*:\s*"tool_use"/g;

function projectSlug(cwd) {
  // Empirical Claude Code rule: every char outside [A-Za-z0-9] becomes '-'
  // ('C:\Users\nadav\github\Nadav-Plugins&Skils' -> 'C--Users-nadav-github-Nadav-Plugins-Skils').
  return String(cwd || '').replace(/[^A-Za-z0-9]/g, '-');
}

function normalizeCwd(p) {
  const normalized = path.normalize(String(p || ''));
  return process.platform === 'win32' ? normalized.toLowerCase() : normalized;
}

function findSessionDir(stdin) {
  const tp = stdin.transcript_path || '';
  if (tp) {
    const candidate = tp.endsWith('.jsonl') ? tp.slice(0, -6) : tp;
    try { if (fs.statSync(candidate).isDirectory()) return candidate; } catch {}
  }

  const sessionId = stdin.session_id || '', cwd = stdin.cwd || '';
  if (sessionId && cwd) {
    const candidate = path.join(CLAUDE_DIR, 'projects', projectSlug(cwd), sessionId);
    try { if (fs.statSync(candidate).isDirectory()) return candidate; } catch {}
  }

  // The statusline runs as a grandchild of Claude Code (CC -> shell -> node),
  // so PID matching can never work; match the session entry by cwd instead,
  // preferring busy status and the freshest updatedAt.
  const sessionsDir = path.join(CLAUDE_DIR, 'sessions');
  try {
    let targetCwd = '';
    try { targetCwd = normalizeCwd(cwd || process.cwd()); } catch {}
    let best = null, bestRank = null;
    if (targetCwd) {
      for (const name of fs.readdirSync(sessionsDir)) {
        if (!name.endsWith('.json')) continue;
        try {
          const data = JSON.parse(fs.readFileSync(path.join(sessionsDir, name), 'utf8'));
          const sid = data.sessionId || '', cwd2 = data.cwd || '';
          if (!sid || !cwd2 || normalizeCwd(cwd2) !== targetCwd) continue;
          const rank = [data.status === 'busy' ? 1 : 0, toNum(data.updatedAt, 0)];
          if (bestRank && (rank[0] < bestRank[0] || (rank[0] === bestRank[0] && rank[1] <= bestRank[1]))) continue;
          const candidate = path.join(CLAUDE_DIR, 'projects', projectSlug(cwd2), sid);
          try {
            if (fs.statSync(candidate).isDirectory()) { best = candidate; bestRank = rank; }
          } catch {}
        } catch {}
      }
    }
    if (best) return best;
  } catch {}
  return null;
}

function workflowCacheKey(sessionDir) {
  const wfDir = path.join(sessionDir, 'workflows');
  const liveDir = path.join(sessionDir, 'subagents', 'workflows');
  let mtime1 = 0, count1 = 0, mtime2 = 0, count2 = 0;
  try {
    const st = fs.statSync(wfDir);
    if (st.isDirectory()) {
      mtime1 = st.mtimeMs;
      count1 = fs.readdirSync(wfDir).filter(n => /^wf_.*\.json$/.test(n)).length;
    }
  } catch {}
  try {
    const st = fs.statSync(liveDir);
    if (st.isDirectory()) {
      mtime2 = st.mtimeMs;
      count2 = fs.readdirSync(liveDir).filter(n => n.startsWith('wf_')).length;
    }
  } catch {}
  return JSON.stringify([sessionDir, mtime1, count1, mtime2, count2]);
}

function readAgentLastUsageTokens(jsonlPath) {
  try {
    const fd = fs.openSync(jsonlPath, 'r');
    try {
      const stat = fs.fstatSync(fd);
      const chunkSize = Math.min(65536, stat.size);
      const buffer = Buffer.alloc(chunkSize);
      fs.readSync(fd, buffer, 0, chunkSize, Math.max(0, stat.size - chunkSize));
      const tail = buffer.toString('utf8');
      const matches = [...tail.matchAll(USAGE_RE)];
      if (!matches.length) return 0;
      // The last match may be a partially-written usage block (live agent file).
      // It is complete iff the match ends before EOF and the next char is not a
      // digit (a digit would mean output_tokens was truncated mid-number).
      let last = matches[matches.length - 1];
      const end = last.index + last[0].length;
      const complete = end < tail.length && !/[0-9]/.test(tail[end]);
      if (!complete) {
        if (matches.length < 2) return 0;
        last = matches[matches.length - 2];
      }
      return Number(last[1]) + Number(last[2]) + Number(last[3]);
    } finally {
      fs.closeSync(fd);
    }
  } catch { return 0; }
}

function detectLiveWorkflows(sessionDir) {
  const liveBase = path.join(sessionDir, 'subagents', 'workflows');
  const completedDir = path.join(sessionDir, 'workflows');
  const results = [];
  try {
    for (const name of fs.readdirSync(liveBase)) {
      if (!name.startsWith('wf_')) continue;
      const wfSubdir = path.join(liveBase, name);
      try { if (!fs.statSync(wfSubdir).isDirectory()) continue; } catch { continue; }
      if (fs.existsSync(path.join(completedDir, `${name}.json`))) continue;

      let agents = 0, tokens = 0;
      for (const fileName of fs.readdirSync(wfSubdir)) {
        if (!/^agent-.*\.jsonl$/.test(fileName) || fileName.endsWith('.meta.json')) continue;
        agents += 1;
        tokens += readAgentLastUsageTokens(path.join(wfSubdir, fileName));
      }
      if (agents > 0) results.push({ name, agents, tokens });
    }
  } catch {}
  return results;
}

function readCompletedWorkflows(sessionDir) {
  const wfDir = path.join(sessionDir, 'workflows');
  const completed = { total_tokens: 0, run_count: 0, agent_count: 0 };
  try {
    for (const fileName of fs.readdirSync(wfDir)) {
      if (!/^wf_.*\.json$/.test(fileName)) continue;
      try {
        const data = JSON.parse(fs.readFileSync(path.join(wfDir, fileName), 'utf8'));
        if (data.status !== 'completed') continue;
        completed.total_tokens += Number(data.totalTokens || 0);
        completed.run_count += 1;
        completed.agent_count += Number(data.agentCount || 0);
      } catch {}
    }
  } catch {}
  return completed;
}

// Session high-water-mark of workflow tokens/runs (survives idle + tier switch).
function wfPeakPath(sessionDir) { return path.join(sessionDir, '.statusline-wf-peak.json'); }
function loadWfPeak(sessionDir) {
  try {
    const d = JSON.parse(fs.readFileSync(wfPeakPath(sessionDir), 'utf8'));
    return { peak_tokens: Number(d.peak_tokens || 0), peak_runs: Number(d.peak_runs || 0) };
  } catch { return { peak_tokens: 0, peak_runs: 0 }; }
}
function saveWfPeak(sessionDir, tokens, runs) {
  try {
    const p = wfPeakPath(sessionDir);
    const tmp = `${p}.${process.pid}.tmp`;
    fs.writeFileSync(tmp, JSON.stringify({ peak_tokens: tokens, peak_runs: runs }));
    fs.renameSync(tmp, p);
  } catch {}
}

// ── Segments ──
const SEGMENTS = {
  banner(ctx) {
    const badges = [];
    const rel = buildReleaseNotice(ctx.schedule);
    if (rel) badges.push(rel);
    let banners = Array.isArray(ctx.schedule.banners) ? ctx.schedule.banners : [];
    const single = ctx.schedule.banner || {};
    if (!banners.length && single.text) banners = [single];
    // Compare against the LOCAL date (python parity) so both engines flip
    // banners at the same local midnight, not at UTC midnight.
    const today = localDateStr(ctx.now || new Date());
    const map = { yellow: BG_YELLOW, red: BG_RED, green: BG_GREEN, blue: BG_BLUE, gray: BG_GRAY };
    for (const b of banners) {
      if (!b || !b.text) continue;
      if (!b.expires || today <= b.expires) {
        badges.push(`${map[b.color] || BG_YELLOW} ${b.text} ${RST}`);
      }
    }
    return badges.join(' ');
  },
  peak_hours(ctx) {
    const { now, schedule, offsetHours } = ctx;
    const peak = schedule.peak || {};
    if (schedule.mode === 'normal') return '';
    if (!peak.enabled) return `${BG_GREEN} OFF-PEAK ${RST}`;
    const hour = now.getHours() + now.getMinutes() / 60;
    const weekday = now.getDay() === 0 ? 7 : now.getDay();
    const peakDays = peak.days || [1,2,3,4,5];
    const { startLocal, endLocal, peakDayOffset } = peakHoursToLocal(schedule, offsetHours);
    const effectiveDays = peakDays.map(d => shiftWeekday(d, peakDayOffset));
    ctx.peakStartLocal = startLocal; ctx.peakEndLocal = endLocal; ctx.peakDays = effectiveDays;
    const isPeakDay = effectiveDays.includes(weekday);
    const prevWd = weekday === 1 ? 7 : weekday - 1;
    const prevWasPeak = effectiveDays.includes(prevWd);
    let isPeak = false, minsLeft = 0, minsUntil = 0;
    if (isPeakDay || prevWasPeak) {
      if (endLocal > startLocal) {
        if (isPeakDay) isPeak = hour >= startLocal && hour < endLocal;
        if (isPeak) minsLeft = Math.floor((endLocal - hour) * 60);
        else if (isPeakDay && hour < startLocal) minsUntil = Math.floor((startLocal - hour) * 60);
        else minsUntil = minsUntilNextPeak(now, effectiveDays, startLocal);
      } else {
        if (isPeakDay && hour >= startLocal) isPeak = true;
        else if (prevWasPeak && hour < endLocal) isPeak = true;
        if (isPeak) minsLeft = hour >= startLocal ? Math.floor((24 - hour + endLocal) * 60) : Math.floor((endLocal - hour) * 60);
        else minsUntil = (isPeakDay && hour < startLocal) ? Math.floor((startLocal - hour) * 60) : minsUntilNextPeak(now, effectiveDays, startLocal);
      }
    } else { minsUntil = minsUntilNextPeak(now, effectiveDays, startLocal); }
    ctx.isPeak = isPeak;
    const lp = peak.label_peak || 'Peak', lo = peak.label_offpeak || 'Off-Peak';
    if (isPeak) {
      const t = fmtDur(minsLeft), bg = minsLeft <= 30 ? BG_GREEN : minsLeft <= 120 ? BG_YELLOW : BG_RED;
      return `${bg} ${lp} ${RST} ${WHITE}\u2192 ends in ${t}${RST} ${DIM}${fmtHour(startLocal)}-${fmtHour(endLocal)}${RST}`;
    }
    return minsUntil > 0 ? `${BG_GREEN} ${lo} ${RST} ${DIM}peak in ${fmtDur(minsUntil)}${RST}` : `${BG_GREEN} ${lo} ${RST}`;
  },
  model(ctx) { const n = (ctx.stdin.model || {}).display_name || ''; return n ? `${BLUE}${n.split('(')[0].trim()}${RST}` : ''; },
  gateway(ctx) {
    const text = gatewayUtil.gatewayBadgeText(ctx.gateway);
    return text ? `${DIM}${CYAN}${text}${RST}` : '';
  },
  context(ctx) {
    const cw = ctx.stdin.context_window || {}, size = cw.context_window_size || 0;
    if (!size) return '';
    const u = cw.current_usage || {};
    const cur = (u.input_tokens||0) + (u.cache_creation_input_tokens||0) + (u.cache_read_input_tokens||0);
    const pct = Math.floor(cur * 100 / size);
    const tier = (ctx.config || {}).tier || 'standard';
    if (tier === 'minimal') return `${DIM}CTX${RST} ${colorPct(pct)}${pct}%${RST}`;
    return `${colorPct(pct)}${fmtTokens(cur)}/${fmtTokens(size)}${RST} ${colorPct(pct)}${pct}%${RST}`;
  },
  vim_mode(ctx) {
    const vim = ctx.stdin.vim || {};
    const mode = vim.mode || '';
    if (!mode) return '';
    const label = String(mode).toUpperCase();
    const color = mode === 'normal' ? BLUE : GREEN;
    return `${color}${label}${RST}`;
  },
  agent(ctx) {
    const parts = [];
    const agent = ctx.stdin.agent || {};
    const agentName = agent.name || '';
    if (agentName) parts.push(`${CYAN}${agentName}${RST}`);

    const worktree = ctx.stdin.worktree || {};
    const worktreeName = worktree.name || '';
    if (worktreeName) parts.push(`${DIM}wt:${worktreeName}${RST}`);

    return parts.join(' ');
  },
  workflows(ctx) {
    const sessionDir = findSessionDir(ctx.stdin || {});
    if (!sessionDir) {
      ctx._wfLive = [];
      ctx._wfCompleted = {};
      return '';
    }

    const key = workflowCacheKey(sessionDir);
    if (wfCache.key === key) {
      const payload = wfCache.payload || {};
      ctx._wfLive = payload.live || [];
      ctx._wfCompleted = payload.completed || {};
      return wfCache.result || '';
    }

    const live = detectLiveWorkflows(sessionDir);
    const completed = readCompletedWorkflows(sessionDir);
    const liveAgents = live.reduce((sum, item) => sum + item.agents, 0);
    const liveTokens = live.reduce((sum, item) => sum + item.tokens, 0);

    // Update the session high-water-mark (cumulative = completed + current live).
    const sessionTokens = completed.total_tokens + liveTokens;
    const sessionRuns = completed.run_count + live.length;
    const peak = loadWfPeak(sessionDir);
    const peakTokens = Math.max(peak.peak_tokens, sessionTokens);
    const peakRuns = Math.max(peak.peak_runs, sessionRuns);
    if (peakTokens !== peak.peak_tokens || peakRuns !== peak.peak_runs) saveWfPeak(sessionDir, peakTokens, peakRuns);

    let result;
    if (live.length) {
      result = `${CYAN}\u2699 ${liveAgents} agents ctx \u03a3 ${fmtTokens(liveTokens)}${RST}`;
    } else if (peakTokens > 0) {
      result = `${DIM}wf idle \u00b7 \u03a3 ${RST}${WHITE}${fmtTokens(peakTokens)}${RST}${DIM} \u00b7 ${peakRuns} runs${RST}`;
    } else {
      result = '';
    }

    ctx._wfLive = live;
    ctx._wfCompleted = completed;
    wfCache = { key, result, payload: { live, completed } };
    return result;
  },
  tasks(ctx) {
    // Show task progress from ~/.claude/tasks/<session_id>/<N>.json.
    // Counts numeric task files (^\d+\.json$) and reports done/total.
    // Self-hides when there is no session_id, no tasks dir, or no task files.
    const sessionId = (ctx.stdin || {}).session_id || '';
    if (!sessionId) return '';
    const tasksDir = path.join(HOME, '.claude', 'tasks', sessionId);
    try { if (!fs.statSync(tasksDir).isDirectory()) return ''; } catch { return ''; }
    const TASK_NAME_RE = /^\d+\.json$/;
    let total = 0, done = 0;
    try {
      for (const entry of fs.readdirSync(tasksDir)) {
        if (!TASK_NAME_RE.test(entry)) continue;
        total += 1;
        try {
          const data = JSON.parse(fs.readFileSync(path.join(tasksDir, entry), 'utf8'));
          if (data.status === 'completed') done += 1;
        } catch {} // unreadable/corrupt task file — ignore
      }
    } catch { return ''; }
    if (total === 0) return '';
    if (done === total) return `${GREEN}✓ ${done}/${total} tasks${RST}`;
    return `${CYAN}◔ ${done}/${total} tasks${RST}`;
  },
  sessions() {
    const text = sessionCockpit.renderSessionSummary(sessionCockpit.collectSessionCounts());
    return text ? `${CYAN}${text}${RST}` : '';
  },
  jobs() {
    const text = jobMonitor.renderJobsSummary(jobMonitor.collectActiveJobs());
    return text ? `${CYAN}${text}${RST}` : '';
  },
  git_branch(ctx) { const b = git('branch','--show-current'); ctx.gitBranch=b; return b ? `${DIM}${b}${RST}` : ''; },
  git_dirty(ctx) {
    const p = git('status','--porcelain');
    const uncommitted = p ? p.split('\n').filter(Boolean).length : 0;
    let unpushed = 0;
    if (ctx.gitBranch) { const a = git('rev-list','--count','@{u}..HEAD'); if (a && a !== '0') unpushed = parseInt(a); }
    if (!uncommitted && !unpushed) return `${GREEN}saved${RST}`;
    if (uncommitted && unpushed) return `${YELLOW}${uncommitted} changed, ${unpushed} unpushed${RST}`;
    if (uncommitted) return `${YELLOW}${uncommitted} unsaved${RST}`;
    return `${YELLOW}${unpushed} unpushed${RST}`;
  },
  churn(ctx) {
    const cwd = repoCwd(ctx);
    const stats = parseGitShortstat(git('-C', cwd, 'diff', '--shortstat', 'HEAD'));
    if (!stats.files && !stats.insertions && !stats.deletions) return '';
    return `${DIM}${BLUE}\u0394 +${stats.insertions} \u2212${stats.deletions} \u00b7 ${stats.files}f${RST}`;
  },
  cost(ctx) {
    if ((ctx.gateway || {}).foreign) return '';
    const c = (ctx.stdin.cost || {}).total_cost_usd;
    return c != null ? `${MAGENTA}$${c.toFixed(2)}${RST}` : '';
  },
  duration(ctx) { const ms = (ctx.stdin.cost || {}).total_duration_ms; return ms ? `${BLUE}${fmtSecs(Math.floor(ms/1000))}${RST}` : ''; },
  effort(ctx) {
    try {
      const s = ctx.settings || JSON.parse(fs.readFileSync(path.join(CLAUDE_DIR, 'settings.json'), 'utf8'));
      const level = s.effortLevel || '';
      if (!level) return '';
      const labels = { low: 'e:LO', medium: 'e:MED', high: 'e:HI' };
      const colors = { low: DIM, medium: YELLOW, high: GREEN };
      return `${colors[level] || DIM}${labels[level] || level.toUpperCase()}${RST}`;
    } catch { return ''; }
  },
  env(ctx) {
    return (process.env.SSH_CLIENT || process.env.SSH_TTY || process.env.SSH_CONNECTION) ? `${MAGENTA}REMOTE${RST}` : `${CYAN}LOCAL${RST}`;
  },
  rate_limits(ctx) {
    if ((ctx.gateway || {}).foreign) return '';
    const cacheFile = path.join(CLAUDE_DIR, 'statusline-usage-cache.json');
    let usageData = null, now = Date.now() / 1000;
    try { const st = fs.statSync(cacheFile); if (now - st.mtimeMs / 1000 < 60) usageData = JSON.parse(fs.readFileSync(cacheFile, 'utf8')); } catch {}
    if (!usageData) {
      const token = getOAuthToken();
      if (token) {
        try {
          const result = execFileSync('curl', ['-s', '--max-time', '5', '-H', `Authorization: Bearer ${token}`,
            '-H', 'Accept: application/json', '-H', 'anthropic-beta: oauth-2025-04-20',
            '-H', 'User-Agent: claude-code/2.1.34', 'https://api.anthropic.com/api/oauth/usage'],
            { timeout: 8000, encoding: 'utf8' });
          if (result && result.trim().startsWith('{')) {
            usageData = JSON.parse(result);
            fs.writeFileSync(cacheFile, JSON.stringify(usageData, null, 2));
            try { fs.chmodSync(cacheFile, 0o600); } catch {}
          }
        } catch {}
      }
      if (!usageData) { try { usageData = JSON.parse(fs.readFileSync(cacheFile, 'utf8')); } catch {} }
    }
    if (!usageData) return '';
    ctx.usageData = usageData;
    const fh = usageData.five_hour || {}, fhPct = Math.round(fh.utilization || 0);
    const tier = (ctx.config || {}).tier || 'standard';
    if (tier === 'minimal') return `${colorPct(fhPct)}${fhPct}%${RST} ${DIM}5H${RST}`;
    return `${buildUsageBar(fhPct)} ${colorPct(fhPct)}${fhPct}%${RST}`;
  },
  usage_credits(ctx) {
    const usageData = ctx.usageData;
    if (!usageData) return '';
    const extra = usageData.extra_usage;
    if (!extra || typeof extra !== 'object' || Array.isArray(extra) || !Object.keys(extra).length) return '';
    const enabled = Boolean(extra.enabled);
    const consumed = toNum(extra.consumed_usd, 0);
    const limit = toNum(extra.limit_usd, 0);
    if (!enabled && consumed === 0) return '';
    if (!enabled) return `${DIM}overflow: off${RST}`;
    if (limit > 0) {
      const pct = Math.floor(consumed * 100 / limit);
      return `${DIM}overflow${RST} ${buildUsageBar(pct, 8)} ${colorPct(pct)}$${consumed.toFixed(2)}/$${limit.toFixed(0)}${RST}`;
    }
    return `${DIM}overflow${RST} ${YELLOW}$${consumed.toFixed(2)}${RST}`;
  },
  auth_mode() {
    const apiKey = process.env.ANTHROPIC_API_KEY || '';
    const oauthToken = process.env.CLAUDE_CODE_OAUTH_TOKEN || '';
    if (apiKey) return `${BG_RED} API-KEY EXPORTED - claude -p bills API acct ${RST}`;
    if (oauthToken) return oauthToken.startsWith('sk-ant-oat01-') ? `${DIM}auth:setup-token${RST}` : `${DIM}auth:oauth${RST}`;
    try {
      const data = JSON.parse(fs.readFileSync(path.join(CLAUDE_DIR, '.credentials.json'), 'utf8'));
      if (((data.claudeAiOauth || {}).accessToken)) return `${DIM}auth:oauth${RST}`;
    } catch {}
    return `${DIM}auth:?${RST}`;
  },
  sdk_meter(ctx) {
    const extra = (ctx.usageData || {}).extra_usage || {};
    const direct = (ctx.usageData || {}).sdk_credit || {};
    if (direct.remaining_usd != null) {
      const limit = toNum(direct.limit_usd, 0);
      const remaining = toNum(direct.remaining_usd, 0);
      const consumed = Math.max(0, limit - remaining);
      if (limit <= 0 || consumed === 0) return '';
      const pct = Math.floor(consumed * 100 / limit);
      let suffix = '';
      if (pct >= 100 && !extra.enabled) suffix = ` ${BG_RED} BLOCKED ${RST}`;
      else if (pct >= 100 && extra.enabled) suffix = ` ${YELLOW}overflow ON${RST}`;
      return `${DIM}sdk${RST} ${buildUsageBar(pct, 8)} ${colorPct(pct)}$${consumed.toFixed(2)}/$${limit.toFixed(0)}${RST}${suffix}`;
    }
    let ledger;
    try { ledger = JSON.parse(fs.readFileSync(path.join(CLAUDE_DIR, 'statusline-sdk-ledger.json'), 'utf8')); } catch { return ''; }
    // Ledger honesty: a stale ledger from a previous month is no-data, not a meter.
    const nowDate = ctx.now || new Date();
    const currentMonth = localDateStr(nowDate).slice(0, 7);
    if (String(ledger.month || '') !== currentMonth) return '';
    const consumed = toNum(ledger.month_total_usd, 0), ceiling = toNum(ledger.plan_ceiling_usd ?? 20, 20);
    if (consumed === 0) return '';
    const pct = ceiling > 0 ? Math.floor(consumed * 100 / ceiling) : 0;
    let suffix = '';
    if (pct >= 100 && !extra.enabled) suffix = ` ${BG_RED} BLOCKED ${RST}`;
    else if (pct >= 100 && extra.enabled) suffix = ` ${YELLOW}overflow ON${RST}`;
    return `${DIM}sdk${RST} ${buildUsageBar(pct, 8)} ${colorPct(pct)}$${consumed.toFixed(2)}/$${ceiling.toFixed(0)}${RST}${DIM} ~per-machine approx${RST}${suffix}`;
  },
  burn_rate(ctx) {
    if ((ctx.gateway || {}).foreign) return '';
    const costData = ctx.stdin.cost || {}, cost = costData.total_cost_usd, durMs = costData.total_duration_ms;
    if (!cost || !durMs || durMs < 60000) return `${DIM}$?/hr${RST}`;
    const cw = ctx.stdin.context_window || {}, u = cw.current_usage || {};
    rs.appendSample(Number(cost), u.input_tokens||0, u.output_tokens||0, u.cache_read_input_tokens||0, u.cache_creation_input_tokens||0);
    let rate = rs.rollingRate(10), windowLabel = '10m';
    if (rate === null || rate < 0.01) { const hours = durMs / 3600000; rate = hours > 0 ? cost / hours : 0; windowLabel = 'session'; }
    if (!rate || rate < 0.01) return `${DIM}$?/hr${RST}`;
    const rateColor = rate >= 10 ? RED : rate >= 5 ? YELLOW : MAGENTA;
    const sev = rate >= 10 ? 'high' : rate >= 5 ? 'moderate' : 'low';
    const parts = [`${DIM}spending${RST} ${rateColor}$${rate.toFixed(1)}/hr ${sev} (${windowLabel})${RST}`];
    const size = cw.context_window_size || 0;
    const cur = (u.input_tokens||0) + (u.cache_creation_input_tokens||0) + (u.cache_read_input_tokens||0);
    if (size > 0 && cur > 0) {
      const tokDelta = rs.rollingTokensOut(10);
      if (tokDelta !== null && tokDelta > 0) {
        const tpMin = tokDelta / 10, remaining = size - cur;
        if (remaining > 0) { const mLeft = Math.floor(remaining / tpMin); if (mLeft < 180) parts.push(`${mLeft < 30 ? RED : mLeft < 60 ? YELLOW : DIM}ctx full ~${fmtDur(mLeft)}${RST}`); }
      }
    }
    return parts.join(' ');
  },
  cache_hit(ctx) {
    const cw = ctx.stdin.context_window || {}, u = cw.current_usage || {};
    const cacheRead = u.cache_read_input_tokens || 0, cacheCreate = u.cache_creation_input_tokens || 0;
    const totalCache = cacheRead + cacheCreate;
    if (totalCache < 1000) return '';
    const hitPct = Math.floor(cacheRead * 100 / totalCache);
    // Stashed for the eff segment, which turns this same ratio into purple
    // dots on the session-quality line instead of recomputing it.
    ctx.cacheHitPct = hitPct;
    const savingsPct = Math.max(0, Math.min(90, Math.floor(hitPct * 0.9)));
    const delta = rs.cacheDelta(5);
    if (delta !== null && delta > 0) {
      const dStr = delta >= 1000 ? `${(delta/1000).toFixed(1)}k` : String(delta);
      return `${DIM}cache reuse${RST} ${delta > 500 ? GREEN : DIM}${hitPct}% \u2191${dStr} saving ~${savingsPct}% cost${RST}`;
    }
    return `${DIM}cache reuse${RST} ${DIM}${hitPct}% idle (saves ~${savingsPct}% when active)${RST}`;
  },
  // Efficiency dots: the cache-reuse ratio cache_hit() already computed,
  // mapped 0-100% -> 0-5 filled purple dots (round half up). No letters, no
  // "grade" wording -- just dots. Self-hides whenever cache_hit() did (not
  // enough cache data yet), so it never shows a score with nothing behind it.
  eff(ctx) {
    const hitPct = ctx.cacheHitPct;
    if (hitPct == null) return '';
    const filled = Math.max(0, Math.min(5, Math.floor(hitPct / 100 * 5 + 0.5)));
    const filledDots = '\u25cf'.repeat(filled);
    const emptyDots = '\u25cb'.repeat(5 - filled);
    return `${DIM}eff${RST} ${PURPLE}${filledDots}${DIM}${emptyDots}${RST}`;
  },
  // This session's tool-call count: literal '"type":"tool_use"' occurrences in
  // the transcript JSONL named by stdin.transcript_path. Cached by session_id
  // + transcript mtime under $TMPDIR/claude/ (never under ~/.claude/ -- this
  // is a throwaway render cache, not user config/state). A missing/unreadable
  // transcript omits the whole segment; it never renders a placeholder.
  tool_count(ctx) {
    const stdin = ctx.stdin || {};
    const sessionId = stdin.session_id || '', transcriptPath = stdin.transcript_path || '';
    if (!sessionId || !transcriptPath) return '';
    let mtime;
    try { mtime = fs.statSync(transcriptPath).mtimeMs; } catch { return ''; }

    const h = crypto.createHash('sha256').update(sessionId).digest('hex').slice(0, 16);
    const cacheDir = path.join(os.tmpdir(), 'claude');
    const cacheFile = path.join(cacheDir, `statusline-toolcount-${h}.json`);

    let count = null;
    try {
      const cached = JSON.parse(fs.readFileSync(cacheFile, 'utf8'));
      if (cached.mtime === mtime) count = Number(cached.count) || 0;
    } catch {}

    if (count === null) {
      let text;
      try { text = fs.readFileSync(transcriptPath, 'utf8'); } catch { return ''; }
      count = (text.match(TOOL_USE_RE) || []).length;
      try {
        fs.mkdirSync(cacheDir, { recursive: true });
        const tmp = `${cacheFile}.${process.pid}.tmp`;
        fs.writeFileSync(tmp, JSON.stringify({ mtime, count }));
        fs.renameSync(tmp, cacheFile);
      } catch {}
    }

    return `${PURPLE}\u2692${RST} ${DIM}${count}${RST}`;
  },
};
SEGMENTS.promo_2x = SEGMENTS.peak_hours;

function runSegment(name, ctx) {
  // No single segment may ever kill the statusline (python engine parity).
  try { return SEGMENTS[name](ctx) || ''; } catch { return ''; }
}

// ── Full mode lines ──
function buildTimeline(ctx) {
  // No peak schedule in 'normal' mode — a peak/off-peak timeline would be
  // misleading (mirrors seg_peak_hours, which also bails out in normal mode).
  if (((ctx.schedule || {}).mode) === 'normal') return '';
  const hour = ctx.now.getHours(), minute = ctx.now.getMinutes();
  const weekday = ctx.now.getDay() === 0 ? 7 : ctx.now.getDay();
  const peakStart = ctx.peakStartLocal ?? 15, peakEnd = ctx.peakEndLocal ?? 21;
  const peakDays = ctx.peakDays || [1,2,3,4,5];
  const isPeakDay = peakDays.includes(weekday);
  const cursorPos = hour * 2 + (minute >= 30 ? 1 : 0);
  let bar = '';
  for (let i = 0; i < 48; i++) {
    const h = i / 2.0;
    if (i === cursorPos) bar += `${WHITE}${BOLD}\u25cf${RST}`;
    else if (!isPeakDay) bar += `${GREEN}\u2501${RST}`;
    else {
      const inPeak = peakEnd > peakStart ? (h >= peakStart && h < peakEnd) : (h >= peakStart || h < peakEnd);
      bar += inPeak ? `${YELLOW}\u2501${RST}` : `${GREEN}\u2501${RST}`;
    }
  }
  let timeline;
  if (!isPeakDay) {
    timeline = `${DIM}\u2502${RST} ${bar} ${DIM}\u2502${RST}  ${GREEN}\u2501 Off-Peak all day \u2714${RST}`;
  } else {
    timeline = `${DIM}\u2502${RST} ${bar} ${DIM}\u2502${RST}  ${GREEN}\u2501${RST}${DIM} off-peak${RST} ${YELLOW}\u2501${RST}${DIM} peak (${fmtHour(peakStart)}-${fmtHour(peakEnd)})${RST}`;
  }
  // Responsive guard: a 48-slot bar is ~48 visible columns plus legend text.
  // On narrow terminals it overflows and wraps mid-bar, which is worse than
  // no timeline at all.  Hide when the rendered string won't fit.
  const renderWidth = ctx.renderWidth || 0;
  if (renderWidth > 0 && visibleWidth(timeline) > renderWidth) return '';
  return timeline;
}

function buildRateLimitsLine(ctx) {
  if ((ctx.gateway || {}).foreign) {
    const label = gatewayUtil.gatewayNoteLabel(ctx.gateway);
    return renderDashboardLine([`${DIM}rate limits n/a on gateway (via ${label})${RST}`], ctx.renderWidth || 0);
  }
  const ud = ctx.usageData;
  if (!ud) return '';
  const fh = ud.five_hour || {}, fhPct = Math.round(fh.utilization || 0);
  const sd = ud.seven_day || {}, sdPct = Math.round(sd.utilization || 0);
  const sds = ud.seven_day_sonnet || {}, sdsPct = Math.round(sds.utilization || 0);
  const labels = (ctx.schedule || {}).labels || {};
  const fhLabel = labels.five_hour || '5h', wkLabel = labels.weekly || 'weekly';
  const cur = `${WHITE}${fhLabel}${RST} ${buildUsageBar(fhPct)} ${colorPct(fhPct)}${String(fhPct).padStart(3)}%${RST} ${DIM}\u27f3${RST} ${WHITE}${formatReset(fh.resets_at, 'time')}${RST}`;
  // Weekly window (and its sonnet sub-window below): longer than a day -> earlier warning thresholds.
  const wk = `${WHITE}${wkLabel}${RST} ${buildUsageBar(sdPct, 10, true)} ${colorPct(sdPct, true)}${String(sdPct).padStart(3)}%${RST} ${DIM}\u27f3${RST} ${WHITE}${formatReset(sd.resets_at, 'datetime')}${RST}`;
  let line = renderDashboardLine([cur, wk], ctx.renderWidth || 0, checkOffloopDrain(ctx, ud));
  // sonnet weekly resets with the weekly window \u2014 drop the redundant \u27f3 stamp and
  // put it on its own continuation row below instead of off to the right.
  if (sdsPct > 0) {
    const sonnet = `${DIM}sonnet${RST} ${buildUsageBar(sdsPct, 10, true)} ${colorPct(sdsPct, true)}${String(sdsPct).padStart(3)}%${RST}`;
    line += `\n${DIM}\u2502${RST}   ${sonnet} ${DIM}\u2502${RST}`;
  }
  return line;
}

function renderExternalProviderParts(row) {
  if (row && row.display === 'combined') {
    // GLM + Copilot merged into one bottom-slot row (see
    // usageProviders.formatCombinedGlmCopilotRow): render each segment through
    // this same function and join with the same dim ' · ' separator used
    // between metrics inside a single compact row.
    const segments = (row.segments || [])
      .map(segment => renderExternalProviderParts(segment))
      .filter(Boolean);
    if (!segments.length) return '';
    return segments.join(` ${DIM}·${RST} `);
  }

  if (row && row.display === 'compact') {
    const labelPart = (row.parts || []).find(part => part.kind === 'label') || {};
    const label = `${WHITE}${labelPart.label || ''}${RST}${labelPart.plan ? `${DIM} ${labelPart.plan}${RST}` : ''}`;
    const metrics = (row.parts || [])
      .filter(part => part.kind === 'metric')
      .map(part => {
        const pct = Number.isFinite(Number(part.pct)) ? Math.max(0, Math.min(100, Math.round(Number(part.pct)))) : 0;
        const longWindow = isLongWindowLabel(part.label);
        return `${WHITE}${part.label}${RST} ${colorPct(pct, longWindow)}${pct}%${RST}`;
      });
    if (!metrics.length) return '';
    const reset = row.resetText ? ` ${DIM}${row.resetText}${RST}` : '';
    const stale = row.staleText ? `${DIM}${row.staleText}${RST}` : '';
    return `${label}  ${metrics.join(` ${DIM}\u00b7${RST} `)}${reset}${stale}`;
  }

  const chunks = [];
  for (const part of row.parts || []) {
    if (part.kind === 'label') {
      chunks.push(`${WHITE}${part.label}${RST}${part.plan ? `${DIM} ${part.plan}${RST}` : ''}`);
    } else if (part.kind === 'window') {
      const reset = part.resetText ? ` ${DIM}${part.resetText}${RST}` : '';
      const longWindow = isLongWindowLabel(part.label);
      chunks.push(`${WHITE}${part.label}${RST} ${buildUsageBar(part.pct, 10, longWindow)} ${colorPct(part.pct, longWindow)}${String(part.pct).padStart(3)}%${RST}${reset}`);
    } else if (part.kind === 'tokens') {
      chunks.push(`${DIM}tokens${RST} ${WHITE}${fmtTokens(part.total)}${RST}`);
    }
  }
  return `${chunks.join('  ')}${row.staleText ? `${DIM}${row.staleText}${RST}` : ''}`;
}

function effectiveExternalUsageConfig(config = {}, isMultiCli = false) {
  if (!isMultiCli) return config || {};

  const source = config && typeof config.external_providers === 'object' && !Array.isArray(config.external_providers)
    ? config.external_providers
    : {};
  const external = { ...source, enabled: true };

  // Codex + GLM are forced on by default in multi-cli. Droid only ever showed a
  // cumulative token count (confusing), so it is opt-in like Antigravity now:
  // it appears only when the user explicitly enables it.
  for (const provider of ['codex', 'glm']) {
    const raw = source[provider];
    const providerConfig = raw && typeof raw === 'object' && !Array.isArray(raw) ? raw : {};
    external[provider] = {
      ...((DEFAULT_CONFIG.external_providers || {})[provider] || {}),
      ...providerConfig,
      enabled: !(raw === false || providerConfig.enabled === false),
    };
  }

  for (const provider of ['droid', 'antigravity']) {
    const raw = source[provider];
    const providerConfig = raw && typeof raw === 'object' && !Array.isArray(raw) ? raw : {};
    external[provider] = {
      ...((DEFAULT_CONFIG.external_providers || {})[provider] || {}),
      ...providerConfig,
      enabled: raw === true || providerConfig.enabled === true,
    };
  }

  return { ...(config || {}), external_providers: external };
}

async function buildExternalUsageLines(ctx) {
  const config = effectiveExternalUsageConfig(ctx.config || {}, Boolean(ctx.isMultiCli));
  const external = (config || {}).external_providers;
  if (!(ctx.isMultiCli || (ctx.isFull && external && external.enabled === true))) return '';
  let records = [];
  try { records = await usageProviders.collectExternalUsage(config || {}); } catch { return ''; }
  const nowSec = Date.now() / 1000;
  const candidates = [];
  for (const record of records) {
    try {
      const row = usageProviders.formatProviderRowParts(record, nowSec);
      if (row) candidates.push({ record, label: row.label });
    } catch {}
  }
  const labelWidth = candidates.reduce((max, item) => Math.max(max, item.label.length), 0);
  // External records carry resets_at as epoch seconds; convert to the engine's
  // formatReset so the row shows an absolute end-time (⟳ 12:00pm / ⟳ 4/7 5:00am)
  // exactly like the Claude rate-limit line above.
  const formatClock = (epochSec, style) => {
    const ms = Number(epochSec) * 1000;
    if (!Number.isFinite(ms)) return '';
    return formatReset(new Date(ms).toISOString(), style);
  };
  // GLM + Copilot now combine into ONE bottom row when both are enabled and
  // available; otherwise each candidate renders exactly as before.
  const candidateByProvider = {};
  for (const { record } of candidates) candidateByProvider[record.provider] = record;
  const combineGlmCopilot = Boolean(candidateByProvider.glm && candidateByProvider.copilot);
  let combinedRendered = false;
  const lines = [];
  for (const { record } of candidates) {
    const provider = record.provider;
    try {
      let row;
      if (combineGlmCopilot && (provider === 'glm' || provider === 'copilot')) {
        if (combinedRendered) continue;
        combinedRendered = true;
        row = usageProviders.formatCombinedGlmCopilotRow(
          candidateByProvider.glm, candidateByProvider.copilot, nowSec, { labelWidth, formatDuration: fmtDur, formatClock },
        );
      } else {
        row = usageProviders.formatProviderRowParts(record, nowSec, { labelWidth, formatDuration: fmtDur, formatClock });
      }
      if (!row) continue;
      const subRows = Array.isArray(row.subRows) && row.subRows.length ? row.subRows : [row];
      for (const sub of subRows) {
        lines.push(renderDashboardLine([renderExternalProviderParts(sub)], ctx.renderWidth || 0));
      }
    } catch {}
  }
  return lines.join('\n');
}

const OFFLOOP_STATE_PATH = path.join(CLAUDE_DIR, 'statusline-offloop-state.json');

function readOffloopState() {
  try {
    const data = JSON.parse(fs.readFileSync(OFFLOOP_STATE_PATH, 'utf8'));
    if (data && typeof data === 'object' && !Array.isArray(data)) return data;
  } catch {}
  return null;
}

function writeOffloopState(state) {
  try {
    const tmpPath = `${OFFLOOP_STATE_PATH}.${process.pid}.${crypto.randomBytes(4).toString('hex')}.tmp`;
    fs.writeFileSync(tmpPath, JSON.stringify(state));
    fs.renameSync(tmpPath, OFFLOOP_STATE_PATH);
  } catch {}
}

function checkOffloopDrain(ctx, usageData) {
  // Each render is a fresh process, so the prior reading must be persisted to
  // disk: in-memory ctx state never survives between statusline refreshes.
  const fhPct = toNum((usageData.five_hour || {}).utilization, 0);
  const now = Date.now() / 1000;
  const sessionCost = toNum(((ctx.stdin || {}).cost || {}).total_cost_usd, 0);
  const prev = readOffloopState();
  const prevPct = prev ? Number(prev.utilization) : NaN;
  if (!Number.isFinite(prevPct)) {
    writeOffloopState({ utilization: fhPct, session_cost: sessionCost, t: now });
    return '';
  }
  const prevTime = toNum(prev.t, now);
  const elapsedMin = (now - prevTime) / 60;
  // Keep the baseline until it is old enough to compare against; overwriting
  // on every refresh would pin elapsed near zero and the check could never fire.
  if (elapsedMin < 2) return '';
  writeOffloopState({ utilization: fhPct, session_cost: sessionCost, t: now });
  const delta = fhPct - prevPct;
  if (delta <= 0) return '';
  const sessionRate = rs.rollingRate(10);
  if (sessionRate == null) return '';
  const expectedPctPerHr = sessionRate / 0.80;
  const actualPctPerHr = delta / elapsedMin * 60;
  return actualPctPerHr > expectedPctPerHr * 2.5 && delta > 3 ? ` ${YELLOW}\u26a0 off-loop drain${RST}` : '';
}

// Line 4 (session-quality line): spending + cache metrics + efficiency dots +
// tool-call count. eff runs after cache_hit so it can read the cache-reuse
// ratio the latter stashes on ctx.cacheHitPct instead of recomputing it.
function buildMetricsLine(ctx) {
  const parts = [];
  const burn = SEGMENTS.burn_rate(ctx);
  if (burn) parts.push(burn);
  const cache = SEGMENTS.cache_hit(ctx);
  if (cache) parts.push(cache);
  const eff = SEGMENTS.eff(ctx);
  if (eff) parts.push(eff);
  const tools = SEGMENTS.tool_count(ctx);
  if (tools) parts.push(tools);
  const wf = SEGMENTS.workflows(ctx);
  if (wf) parts.push(wf);
  if (!parts.length) return '';
  return renderDashboardLine(parts, ctx.renderWidth || 0);
}

// ── VS Code context ──
function writeVscodeContext(ctx) {
  // Write statusline data to %TEMP%/claude/statusline-context.json (python parity).
  const contextDir = path.join(os.tmpdir(), 'claude');
  fs.mkdirSync(contextDir, { recursive: true });
  const contextPath = path.join(contextDir, 'statusline-context.json');

  const usageData = ctx.usageData || {};
  const wfLive = ctx._wfLive || [];
  const wfCompleted = ctx._wfCompleted || {};
  const stdin = ctx.stdin || {};
  const cw = stdin.context_window || {};
  const u = cw.current_usage || {};
  const current = toNum(u.input_tokens, 0) + toNum(u.cache_creation_input_tokens, 0) + toNum(u.cache_read_input_tokens, 0);
  const size = toNum(cw.context_window_size, 0);
  const pct = size > 0 ? Math.trunc(current * 100 / size) : 0;

  const payload = {
    ts: Math.floor(Date.now() / 1000),
    updated_at: new Date().toISOString(),
    five_hour_pct: Math.trunc(toNum((usageData.five_hour || {}).utilization, 0)),
    seven_day_pct: Math.trunc(toNum((usageData.seven_day || {}).utilization, 0)),
    cost_usd: (stdin.cost || {}).total_cost_usd ?? 0,
    current_usage: current,
    context_window_size: size,
    pct,
    // session_id lets the narrator confirm this session-specific current_usage
    // is ours before trusting it (the file is global, last render wins).
    session_id: stdin.session_id || '',
    model: (stdin.model || {}).display_name || '',
    is_peak: Boolean(ctx.isPeak),
    active_workflow_agents: wfLive.reduce((sum, item) => sum + item.agents, 0),
    subagent_tokens_live: wfLive.reduce((sum, item) => sum + item.tokens, 0),
    subagent_runs_session: wfCompleted.run_count || 0,
  };

  const tmpPath = `${contextPath}.${process.pid}.${crypto.randomBytes(4).toString('hex')}.tmp`;
  fs.writeFileSync(tmpPath, JSON.stringify(payload));
  fs.renameSync(tmpPath, contextPath);
}

// ── Telemetry ──
const TELEMETRY_URL = 'https://statusline-telemetry.nadavf.workers.dev/ping';
const HEARTBEAT_PATH = path.join(CLAUDE_DIR, '.statusline-heartbeat');
const TELEMETRY_ID_PATH = path.join(CLAUDE_DIR, '.statusline-telemetry-id');

function getTelemetryId() {
  try {
    if (!fs.existsSync(CLAUDE_DIR)) fs.mkdirSync(CLAUDE_DIR, { recursive: true, mode: 0o700 });
    if (fs.existsSync(TELEMETRY_ID_PATH)) {
      const e = fs.readFileSync(TELEMETRY_ID_PATH, 'utf8').trim().toLowerCase();
      if (/^[0-9a-f]{16}$/.test(e)) return e;
    }
    const id = crypto.randomBytes(8).toString('hex');
    fs.writeFileSync(TELEMETRY_ID_PATH, id, { mode: 0o600 });
    return id;
  } catch { return ''; }
}

function telemetryDisabled(config) {
  // Telemetry is opt-in: requires telemetry: true in config (default is off).
  // STATUSLINE_DISABLE_TELEMETRY=1 is a hard override that always wins.
  return config.telemetry !== true || process.env.STATUSLINE_DISABLE_TELEMETRY === '1';
}

function maybeHeartbeat(config) {
  if (telemetryDisabled(config)) return;
  try {
    const today = new Date().toISOString().slice(0, 10);
    if (fs.existsSync(HEARTBEAT_PATH)) { if (fs.statSync(HEARTBEAT_PATH).mtime.toISOString().slice(0, 10) === today) return; }
    const uid = getTelemetryId();
    if (!uid) return;
    fs.writeFileSync(HEARTBEAT_PATH, today);
    const payload = JSON.stringify({ id: uid, v: '2.2', engine: 'node', tier: config.tier || 'standard', os: process.platform, event: 'heartbeat' });
    const devnull = process.platform === 'win32' ? 'NUL' : '/dev/null';
    const child = spawn('curl', ['-s', '-o', devnull, '--max-time', '3', '-X', 'POST', '-H', 'Content-Type: application/json', '-d', payload, TELEMETRY_URL], { stdio: 'ignore', detached: true });
    child.unref();
  } catch {}
}

// Subtle end-of-line-1 render-time stamp (HH:MM, local time), multi-cli only.
// Distinct from the (unwired) python seg_time -- this one is dim and reuses
// ctx.now, the engine's existing local-time resolution (getLocalTime()).
function renderClock(ctx) {
  const now = ctx.now;
  if (!now) return '';
  const hh = String(now.getHours()).padStart(2, '0');
  const mm = String(now.getMinutes()).padStart(2, '0');
  return `${DIM}${hh}:${mm}${RST}`;
}

// ── Main ──
async function main() {
  const config = loadConfig();
  maybeHeartbeat(config);
  const settings = loadClaudeSettings();
  let stdin = {};
  try { if (!process.stdin.isTTY) { const raw = fs.readFileSync(0, 'utf8').trim(); if (raw) stdin = JSON.parse(raw); } } catch {}

  if (stdin.session_id) rs.setSessionId(stdin.session_id);

  const mode = config.mode || 'minimal';
  for (const arg of process.argv.slice(2)) {
    if (arg === '--full') config._mode = 'full';
    else if (arg === '--minimal') config._mode = 'minimal';
    else if (arg.startsWith('--tier=')) { config.tier = arg.split('=', 2)[1]; if (config.tier !== 'full') config._mode = 'minimal'; }
  }
  const effectiveMode = config._mode || mode;

  const { now, tzName, offsetHours } = getLocalTime();
  const schedule = loadSchedule(config);
  const tier = config.tier || 'standard';
  const isMultiCli = tier === 'multi-cli';
  const isFull = isMultiCli || tier === 'full' || effectiveMode === 'full';
  const isStandard = tier === 'standard' && !isFull;
  const ctx = {
    config, stdin, settings, now, tzName, offsetHours, schedule,
    gateway: isMultiCli ? gatewayUtil.gatewayInfo({ config, settings }) : { foreign: false },
    isPeak: false, renderWidth: resolveRenderWidth(config),
  };
  const enabled = getEnabled(config, schedule);
  // In multi-cli the banner moves to the very last line of output (rendered
  // after the metrics line below); every other tier keeps it on line 1.
  if (!isMultiCli && !enabled.includes('banner')) enabled.unshift('banner');
  if (process.env.ANTHROPIC_API_KEY && !enabled.includes('auth_mode')) {
    enabled.splice(enabled[0] === 'banner' ? 1 : 0, 0, 'auth_mode');
  }

  ctx.isFull = isFull;
  ctx.isMultiCli = isMultiCli;
  if (isFull || isStandard) runSegment('rate_limits', ctx);

  const parts = [], gitParts = [];
  for (const name of enabled) {
    const fn = SEGMENTS[name];
    if (!fn) continue;
    const r = runSegment(name, ctx);
    if (!r) continue;
    if (['git_branch', 'git_dirty', 'git_ahead_behind', 'churn'].includes(name)) gitParts.push(r);
    else parts.push(r);
  }
  if (gitParts.length) parts.push(gitParts.join(' '));

  // multi-cli only: a subtle render-time stamp at the tail of line 1. Not the
  // Claude Code version (owner rejected that) -- just HH:MM, dim, so a stale
  // statusline render is visible at a glance. Every other tier stays as-is.
  if (isMultiCli) {
    const clock = renderClock(ctx);
    if (clock) parts.push(clock);
  }

  const arrowColor = ctx.isPeak ? YELLOW : GREEN;
  const arrow = ` ${arrowColor}\u25b8${RST} `;
  // Responsive width: reflow the segment line to fit the terminal (COLUMNS)
  // instead of one wide line; falls back to a single line when width is unknown.
  const renderWidth = ctx.renderWidth;
  process.stdout.write(renderWidth > 0 && parts.length ? reflowParts(parts, arrow, renderWidth).join('\n') : parts.join(arrow));

  if (isStandard) {
    const rl = buildRateLimitsLine(ctx);
    if (rl) process.stdout.write(`\n${rl}`);
  }

  if (isFull) {
    const features = schedule.features || {};
    if (features.show_timeline !== false) {
      const tl = buildTimeline(ctx);
      if (tl) process.stdout.write(`\n\n${tl}`);
    }
    const rl = buildRateLimitsLine(ctx);
    if (rl) process.stdout.write(`\n${rl}`);
    const ext = await buildExternalUsageLines(ctx);
    if (ext) process.stdout.write(`\n${ext}`);
    const ml = buildMetricsLine(ctx);
    if (ml) process.stdout.write(`\n${ml}`);
  }

  // multi-cli: the promo banner renders as the final line (it was removed from
  // line 1 above), so line 1 stays clean and the banner anchors the bottom.
  if (isMultiCli) {
    const banner = runSegment('banner', ctx);
    if (banner) process.stdout.write(`\n${banner}`);
  }

  try { writeVscodeContext(ctx); } catch {}
}

module.exports = { parseGitShortstat, TIER_PRESETS };

if (require.main === module) {
  main().catch(() => {});
}
