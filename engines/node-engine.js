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

// ── ANSI ──
const RST = '\x1b[0m', BOLD = '\x1b[1m', DIM = '\x1b[2m';
const RED = '\x1b[31m', GREEN = '\x1b[32m', YELLOW = '\x1b[33m';
const BLUE = '\x1b[34m', MAGENTA = '\x1b[35m', CYAN = '\x1b[36m';
const WHITE = '\x1b[38;2;220;220;220m';
const BG_GREEN = '\x1b[38;5;255;48;5;28m';
const BG_YELLOW = '\x1b[38;5;16;48;5;220m';
const BG_RED = '\x1b[38;5;255;48;5;124m';
const BG_GRAY = '\x1b[48;5;236m';
const BG_BLUE = '\x1b[38;5;255;48;5;27m';

// ── Config ──
const TIER_PRESETS = {
  minimal: ['peak_hours', 'model', 'context', 'git_branch', 'git_dirty', 'rate_limits', 'effort', 'env'],
  standard: ['peak_hours', 'model', 'context', 'vim_mode', 'agent', 'git_branch', 'git_dirty', 'cost', 'effort', 'env'],
  full: ['peak_hours', 'model', 'context', 'vim_mode', 'agent', 'git_branch', 'git_dirty', 'cost', 'effort', 'env'],
};

const DEFAULT_CONFIG = {
  tier: 'standard',
  mode: 'minimal',
  schedule_url: 'https://raw.githubusercontent.com/Nadav-Fux/claude-2x-statusline/main/schedule.json',
  schedule_cache_hours: 3,
};

const DEFAULT_SCHEDULE = {
  v: 2, mode: 'peak_hours', default_tier: 'full',
  peak: { enabled: true, tz: 'America/Los_Angeles', days: [1,2,3,4,5], start: 5, end: 11,
    label_peak: 'Peak', label_offpeak: 'Off-Peak' },
  banner: { text: '', expires: '', color: 'yellow' },
  release: {},
  features: { show_peak_segment: true, show_rate_limits: true, show_timeline: true },
};

function loadLocalVersion() {
  try {
    return JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'package.json'), 'utf8')).version || '';
  } catch { return ''; }
}
const CURRENT_VERSION = loadLocalVersion();

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
  const cacheHours = config.schedule_cache_hours || 3;
  try {
    const stat = fs.statSync(cachePath);
    const ageHours = (Date.now() - stat.mtimeMs) / 3600000;
    if (ageHours < cacheHours) return JSON.parse(fs.readFileSync(cachePath, 'utf8'));
  } catch {}
  try {
    const url = config.schedule_url || DEFAULT_CONFIG.schedule_url;
    const result = execFileSync('curl', ['-s', '--max-time', '3', url], { timeout: 5000, encoding: 'utf8' });
    if (result && result.trim().startsWith('{')) {
      const data = JSON.parse(result);
      fs.writeFileSync(cachePath, JSON.stringify(data, null, 2));
      return data;
    }
  } catch {}
  try { return JSON.parse(fs.readFileSync(cachePath, 'utf8')); } catch {}
  return DEFAULT_SCHEDULE;
}

// ── Helpers ──
function fmtDur(mins) { const h = Math.floor(mins/60), m = mins%60; return h > 0 ? `${h}h ${String(m).padStart(2,'0')}m` : `${m}m`; }
function fmtSecs(s) { const h=Math.floor(s/3600), m=Math.floor((s%3600)/60), sec=s%60; return h>0?`${h}h${String(m).padStart(2,'0')}m`:m>0?`${m}m${String(sec).padStart(2,'0')}s`:`${sec}s`; }
function colorPct(p) { return p >= 80 ? RED : p >= 50 ? YELLOW : GREEN; }
function git(...args) { try { return execFileSync('git', args, { timeout: 2000, encoding: 'utf8' }).trim(); } catch { return ''; } }
function fmtTokens(n) { return n >= 1e6 ? `${(n/1e6).toFixed(1)}M` : n >= 1e3 ? `${Math.floor(n/1e3)}K` : String(n); }

function fmtHour(h) {
  h = ((h % 24) + 24) % 24;
  const hInt = Math.floor(h), mInt = Math.round((h - hInt) * 60);
  const ampm = hInt < 12 ? 'am' : 'pm', display = hInt % 12 || 12;
  return mInt ? `${display}:${String(mInt).padStart(2,'0')}${ampm}` : `${display}${ampm}`;
}

function buildUsageBar(pct, width = 10) {
  pct = Math.max(0, Math.min(100, pct));
  const filled = Math.floor(pct * width / 100), empty = width - filled;
  return `${colorPct(pct)}${'\u25b0'.repeat(filled)}${DIM}${'\u25b1'.repeat(empty)}${RST}`;
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

// ── Segments ──
const SEGMENTS = {
  banner(ctx) {
    const badges = [];
    const rel = buildReleaseNotice(ctx.schedule);
    if (rel) badges.push(rel);
    const b = ctx.schedule.banner || {};
    if (b.text) {
      const today = new Date().toISOString().slice(0, 10);
      if (!b.expires || today <= b.expires) {
        const map = { yellow: BG_YELLOW, red: BG_RED, green: BG_GREEN, blue: BG_BLUE, gray: BG_GRAY };
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
  cost(ctx) { const c = (ctx.stdin.cost || {}).total_cost_usd; return c != null ? `${MAGENTA}$${c.toFixed(2)}${RST}` : ''; },
  duration(ctx) { const ms = (ctx.stdin.cost || {}).total_duration_ms; return ms ? `${BLUE}${fmtSecs(Math.floor(ms/1000))}${RST}` : ''; },
  effort(ctx) {
    try {
      const s = JSON.parse(fs.readFileSync(path.join(CLAUDE_DIR, 'settings.json'), 'utf8'));
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
    const peakTag = ctx.isPeak ? ` ${YELLOW}\u26a1${RST}` : '';
    const tier = (ctx.config || {}).tier || 'standard';
    if (tier === 'minimal') return `${colorPct(fhPct)}${fhPct}%${RST} ${DIM}5H${RST}${peakTag}`;
    return `${buildUsageBar(fhPct)} ${colorPct(fhPct)}${fhPct}%${RST}${peakTag}`;
  },
  burn_rate(ctx) {
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
    const savingsPct = Math.max(0, Math.min(90, Math.floor(hitPct * 0.9)));
    const delta = rs.cacheDelta(5);
    if (delta !== null && delta > 0) {
      const dStr = delta >= 1000 ? `${(delta/1000).toFixed(1)}k` : String(delta);
      return `${DIM}cache reuse${RST} ${delta > 500 ? GREEN : DIM}${hitPct}% \u2191${dStr} saving ~${savingsPct}% cost${RST}`;
    }
    return `${DIM}cache reuse${RST} ${DIM}${hitPct}% idle (saves ~${savingsPct}% when active)${RST}`;
  },
};
SEGMENTS.promo_2x = SEGMENTS.peak_hours;

// ── Full mode lines ──
function buildTimeline(ctx) {
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
  if (!isPeakDay) return `${DIM}\u2502${RST} ${bar} ${DIM}\u2502${RST}  ${GREEN}\u2501 Off-Peak all day \u2714${RST}`;
  return `${DIM}\u2502${RST} ${bar} ${DIM}\u2502${RST}  ${GREEN}\u2501${RST}${DIM} off-peak${RST} ${YELLOW}\u2501${RST}${DIM} peak (${fmtHour(peakStart)}-${fmtHour(peakEnd)})${RST}`;
}

function buildRateLimitsLine(ctx) {
  const ud = ctx.usageData;
  if (!ud) return '';
  const fh = ud.five_hour || {}, fhPct = Math.round(fh.utilization || 0);
  const sd = ud.seven_day || {}, sdPct = Math.round(sd.utilization || 0);
  const peakTag = ctx.isPeak ? ` ${YELLOW}\u26a1 peak${RST}` : ` ${GREEN}\u2713${RST}`;
  const labels = (ctx.schedule || {}).labels || {};
  const fhLabel = labels.five_hour || '5h', wkLabel = labels.weekly || 'weekly';
  const cur = `${DIM}\u2502${RST} ${GREEN}\u25b8${RST} ${WHITE}${fhLabel}${RST} ${buildUsageBar(fhPct)} ${colorPct(fhPct)}${String(fhPct).padStart(3)}%${RST} ${DIM}\u27f3${RST} ${WHITE}${formatReset(fh.resets_at, 'time')}${RST}`;
  const wk = `${WHITE}${wkLabel}${RST} ${buildUsageBar(sdPct)} ${colorPct(sdPct)}${String(sdPct).padStart(3)}%${RST} ${DIM}\u27f3${RST} ${WHITE}${formatReset(sd.resets_at, 'datetime')}${RST}`;
  return `${cur}${peakTag} ${DIM}\u00b7${RST} ${wk} ${DIM}\u2502${RST}`;
}

function buildMetricsLine(ctx) {
  const parts = [];
  const burn = SEGMENTS.burn_rate(ctx);
  if (burn) parts.push(`${GREEN}\u25b8${RST} ${burn}`);
  const cache = SEGMENTS.cache_hit(ctx);
  if (cache) parts.push(cache);
  if (ctx.isPeak) parts.push(`${YELLOW}\u26a1 peak = limits drain faster${RST}`);
  if (!parts.length) return '';
  return `${DIM}\u2502${RST} ${parts.join(` ${DIM}\u00b7${RST} `)} ${DIM}\u2502${RST}`;
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
  return config.telemetry === false || process.env.STATUSLINE_DISABLE_TELEMETRY === '1';
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
    const child = spawn('curl', ['-s', '-o', '/dev/null', '--max-time', '3', '-X', 'POST', '-H', 'Content-Type: application/json', '-d', payload, TELEMETRY_URL], { stdio: 'ignore', detached: true });
    child.unref();
  } catch {}
}

// ── Main ──
function main() {
  const config = loadConfig();
  maybeHeartbeat(config);
  let stdin = {};
  try { const raw = fs.readFileSync(0, 'utf8').trim(); if (raw) stdin = JSON.parse(raw); } catch {}

  const mode = config.mode || 'minimal';
  for (const arg of process.argv.slice(2)) {
    if (arg === '--full') config._mode = 'full';
    else if (arg === '--minimal') config._mode = 'minimal';
    else if (arg.startsWith('--tier=')) { config.tier = arg.split('=', 2)[1]; if (config.tier !== 'full') config._mode = 'minimal'; }
  }
  const effectiveMode = config._mode || mode;

  const { now, tzName, offsetHours } = getLocalTime();
  const schedule = loadSchedule(config);
  const ctx = { config, stdin, now, tzName, offsetHours, schedule, isPeak: false };
  const enabled = getEnabled(config, schedule);
  if (!enabled.includes('banner')) enabled.unshift('banner');

  const tier = config.tier || 'standard';
  const isFull = tier === 'full' || effectiveMode === 'full';
  const isStandard = tier === 'standard' && !isFull;
  if (isFull || isStandard) SEGMENTS.rate_limits(ctx);

  const parts = [], gitParts = [];
  for (const name of enabled) {
    const fn = SEGMENTS[name];
    if (!fn) continue;
    const r = fn(ctx);
    if (!r) continue;
    if (['git_branch', 'git_dirty'].includes(name)) gitParts.push(r);
    else parts.push(r);
  }
  if (gitParts.length) parts.push(gitParts.join(' '));

  const arrowColor = ctx.isPeak ? YELLOW : GREEN;
  process.stdout.write(parts.join(` ${arrowColor}\u25b8${RST} `));

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
    const ml = buildMetricsLine(ctx);
    if (ml) process.stdout.write(`\n${ml}`);
  }
}

main();
