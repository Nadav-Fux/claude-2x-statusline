#!/usr/bin/env node
/**
 * Claude Code statusline — Node.js fallback engine.
 * Used when Python is not available.
 * v2.1 — Peak hours awareness with auto-timezone and remote schedule.
 *
 * Supports: time, peak_hours, model, context, git, cost, duration, lines, effort, env.
 * Does NOT support: rate_limits, ts_errors (use Python for those).
 */

const { execFileSync, spawn } = require('child_process');
const crypto = require('crypto');
const fs = require('fs');
const os = require('os');
const path = require('path');
const https = require('https');

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
  minimal: ['peak_hours', 'model', 'context', 'git_branch', 'git_dirty', 'effort', 'env'],
  standard: ['peak_hours', 'model', 'context', 'git_branch', 'git_dirty', 'cost', 'effort', 'env'],
  full: ['peak_hours', 'model', 'context', 'git_branch', 'git_dirty', 'cost', 'effort', 'env'],
};

const DEFAULT_SCHEDULE = {
  v: 2, mode: 'peak_hours',
  peak: { enabled: true, tz: 'America/Los_Angeles', days: [1,2,3,4,5], start: 5, end: 11,
    label_peak: 'Peak', label_offpeak: 'Off-Peak', note: 'Session limits consumed faster' },
  banner: { text: '', expires: '', color: 'yellow' },
  release: {},
};

function loadLocalVersion() {
  try {
    const packagePath = path.join(__dirname, '..', 'package.json');
    return JSON.parse(fs.readFileSync(packagePath, 'utf8')).version || '';
  } catch {
    return '';
  }
}

const CURRENT_VERSION = loadLocalVersion();

function parseVersion(value) {
  const core = String(value || '').split('-', 1)[0].split('+', 1)[0];
  const parts = core.split('.').map(token => {
    const digits = token.replace(/[^0-9]/g, '');
    return digits ? parseInt(digits, 10) : 0;
  });
  while (parts.length < 3) {
    parts.push(0);
  }
  return parts;
}

function compareVersions(left, right) {
  const leftParts = parseVersion(left);
  const rightParts = parseVersion(right);
  const length = Math.max(leftParts.length, rightParts.length);
  while (leftParts.length < length) {
    leftParts.push(0);
  }
  while (rightParts.length < length) {
    rightParts.push(0);
  }
  for (let index = 0; index < length; index++) {
    if (leftParts[index] < rightParts[index]) {
      return -1;
    }
    if (leftParts[index] > rightParts[index]) {
      return 1;
    }
  }
  return 0;
}

function buildReleaseNotice(schedule) {
  const release = schedule.release || {};
  const latestVersion = String(release.latest_version || '').trim();
  const minimumVersion = String(release.minimum_version || '').trim();
  if (!CURRENT_VERSION || (!latestVersion && !minimumVersion)) {
    return '';
  }

  const command = String(release.command || '/statusline-update').trim() || '/statusline-update';
  const targetVersion = latestVersion || minimumVersion;

  if (minimumVersion && compareVersions(CURRENT_VERSION, minimumVersion) < 0) {
    const text = release.required_text || `Update required v${targetVersion} via ${command}`;
    return `${BG_RED} ${text} ${RST}`;
  }
  if (latestVersion && compareVersions(CURRENT_VERSION, latestVersion) < 0) {
    const text = release.available_text || `Update available v${latestVersion} via ${command}`;
    return `${BG_YELLOW} ${text} ${RST}`;
  }
  return '';
}

function localDateString(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function loadConfig() {
  const p = path.join(process.env.HOME || process.env.USERPROFILE, '.claude', 'statusline-config.json');
  try { return JSON.parse(fs.readFileSync(p, 'utf8')); } catch { return { tier: 'standard' }; }
}

function getEnabled(config) {
  const tier = config.tier || 'standard';
  if (tier === 'custom') {
    return Object.entries(config.segments || {}).filter(([,v]) => v)
      .map(([k]) => k === 'promo_2x' ? 'peak_hours' : k);
  }
  return TIER_PRESETS[tier] || TIER_PRESETS.standard;
}

function loadSchedule(config) {
  const cachePath = path.join(process.env.HOME || process.env.USERPROFILE, '.claude', 'statusline-schedule.json');
  // Default matches python-engine (3h). Was 6h here, causing the two engines
  // to refresh the schedule on different cadences when no explicit config.
  const cacheHours = config.schedule_cache_hours || 3;

  // Check cache
  try {
    const stat = fs.statSync(cachePath);
    const ageHours = (Date.now() - stat.mtimeMs) / 3600000;
    if (ageHours < cacheHours) {
      return JSON.parse(fs.readFileSync(cachePath, 'utf8'));
    }
  } catch {}

  // Try synchronous fetch via child process (Node has no sync HTTP)
  try {
    const url = config.schedule_url || 'https://raw.githubusercontent.com/Nadav-Fux/claude-2x-statusline/main/schedule.json';
    const result = execFileSync('curl', ['-s', '--max-time', '3', url], { timeout: 5000, encoding: 'utf8' });
    if (result && result.trim().startsWith('{')) {
      const data = JSON.parse(result);
      fs.writeFileSync(cachePath, JSON.stringify(data, null, 2));
      return data;
    }
  } catch {}

  // Stale cache fallback
  try { return JSON.parse(fs.readFileSync(cachePath, 'utf8')); } catch {}

  return DEFAULT_SCHEDULE;
}

// ── Helpers ──
function fmtDur(mins) { const h = Math.floor(mins/60), m = mins%60; return h > 0 ? `${h}h ${String(m).padStart(2,'0')}m` : `${m}m`; }
function fmtSecs(s) { const h=Math.floor(s/3600), m=Math.floor((s%3600)/60), sec=s%60; return h>0?`${h}h${String(m).padStart(2,'0')}m`:m>0?`${m}m${String(sec).padStart(2,'0')}s`:`${sec}s`; }
function colorPct(p) { return p >= 80 ? RED : p >= 50 ? YELLOW : GREEN; }
function git(...args) { try { return execFileSync('git', args, { timeout: 2000, encoding: 'utf8' }).trim(); } catch { return ''; } }

function fmtHour(h) {
  h = ((h % 24) + 24) % 24;
  const hInt = Math.floor(h);
  const mInt = Math.round((h - hInt) * 60);
  const ampm = hInt < 12 ? 'am' : 'pm';
  const display = hInt % 12 || 12;
  return mInt ? `${display}:${String(mInt).padStart(2,'0')}${ampm}` : `${display}${ampm}`;
}

// ── Timezone ──
function getLocalTime() {
  const now = new Date();
  const offsetMin = -now.getTimezoneOffset(); // JS returns inverted
  const offsetHours = offsetMin / 60;
  const tzName = Intl.DateTimeFormat().resolvedOptions().timeZone || `UTC${offsetHours >= 0 ? '+' : ''}${offsetHours}`;
  return { now, tzName, offsetHours };
}

function getPacificOffset(utcDate) {
  // US DST: Second Sunday of March → First Sunday of November
  const year = utcDate.getUTCFullYear();
  // Second Sunday of March
  const mar1 = new Date(Date.UTC(year, 2, 1));
  const mar1dow = mar1.getUTCDay();
  const dstStart = new Date(Date.UTC(year, 2, 1 + ((7 - mar1dow) % 7) + 7, 10)); // 2AM PST = 10 UTC
  // First Sunday of November
  const nov1 = new Date(Date.UTC(year, 10, 1));
  const nov1dow = nov1.getUTCDay();
  const dstEnd = new Date(Date.UTC(year, 10, 1 + ((7 - nov1dow) % 7), 9)); // 2AM PDT = 9 UTC

  return (utcDate >= dstStart && utcDate < dstEnd) ? -7 : -8;
}

function getSourceOffset(tz) {
  if (!tz || tz === 'America/Los_Angeles') { return getPacificOffset(new Date()); }
  if (tz === 'UTC' || tz === 'Etc/UTC') { return 0; }
  const pacificOff = getPacificOffset(new Date());
  const tzOffsets = {
    'America/New_York': pacificOff + 3,
    'America/Chicago': pacificOff + 2,
    'America/Denver': pacificOff + 1,
  };
  return tzOffsets[tz] ?? getPacificOffset(new Date());
}

function peakHoursToLocal(schedule, localOffset) {
  const peak = schedule.peak || {};
  const startH = peak.start || 5;
  const endH = peak.end || 11;
  const srcOffset = getSourceOffset(peak.tz);

  const startLocal = ((startH - srcOffset + localOffset) % 24 + 24) % 24;
  const endLocal = ((endH - srcOffset + localOffset) % 24 + 24) % 24;
  return { startLocal, endLocal, duration: endH - startH };
}

function minsUntilNextPeak(now, peakDays, startLocalHour) {
  const hour = now.getHours() + now.getMinutes() / 60;
  // JS getDay: 0=Sun; convert to ISO: 1=Mon..7=Sun
  const weekday = now.getDay() === 0 ? 7 : now.getDay();
  for (let offset = 1; offset <= 7; offset++) {
    const nextDay = ((weekday - 1 + offset) % 7) + 1;
    if (peakDays.includes(nextDay)) {
      return Math.floor((24 - hour) * 60) + (offset - 1) * 1440 + Math.floor(startLocalHour * 60);
    }
  }
  return 0;
}

// ── Segments ──
const SEGMENTS = {
  banner(ctx) {
    const badges = [];
    const releaseNotice = buildReleaseNotice(ctx.schedule);
    if (releaseNotice) {
      badges.push(releaseNotice);
    }

    const banner = ctx.schedule.banner || {};
    if (banner.text) {
      const today = localDateString(ctx.now);
      if (!banner.expires || today <= banner.expires) {
        const colorMap = {
          yellow: BG_YELLOW,
          red: BG_RED,
          green: BG_GREEN,
          blue: BG_BLUE,
          gray: BG_GRAY,
        };
        const bg = colorMap[banner.color] || BG_YELLOW;
        badges.push(`${bg} ${banner.text} ${RST}`);
      }
    }

    return badges.join(' ');
  },
  time(ctx) {
    const h = String(ctx.now.getHours()).padStart(2,'0');
    const m = String(ctx.now.getMinutes()).padStart(2,'0');
    return `${WHITE}${BOLD}${h}:${m}${RST}`;
  },
  peak_hours(ctx) {
    const { now, schedule, offsetHours } = ctx;
    const peak = schedule.peak || {};
    if (!peak.enabled) return `${BG_GREEN} OFF-PEAK ${RST}`;

    const hour = now.getHours() + now.getMinutes() / 60;
    const weekday = now.getDay() === 0 ? 7 : now.getDay();
    const peakDays = peak.days || [1,2,3,4,5];
    const { startLocal, endLocal } = peakHoursToLocal(schedule, offsetHours);

    ctx.peakStartLocal = startLocal;
    ctx.peakEndLocal = endLocal;
    ctx.peakDays = peakDays;

    const isPeakDay = peakDays.includes(weekday);
    const prevWeekday = weekday === 1 ? 7 : weekday - 1;
    const prevWasPeak = peakDays.includes(prevWeekday);
    let isPeak = false, minsLeft = 0, minsUntil = 0;

    if (isPeakDay || prevWasPeak) {
      if (endLocal > startLocal) {
        if (isPeakDay) { isPeak = hour >= startLocal && hour < endLocal; }
        if (isPeak) { minsLeft = Math.floor((endLocal - hour) * 60); }
        else if (isPeakDay && hour < startLocal) { minsUntil = Math.floor((startLocal - hour) * 60); }
        else { minsUntil = minsUntilNextPeak(now, peakDays, startLocal); }
      } else {
        // Crosses midnight: peak if today is peak day and past start,
        // OR previous day was peak and before end (spillover)
        if (isPeakDay && hour >= startLocal) { isPeak = true; }
        else if (prevWasPeak && hour < endLocal) { isPeak = true; }
        if (isPeak) {
          minsLeft = hour >= startLocal
            ? Math.floor((24 - hour + endLocal) * 60)
            : Math.floor((endLocal - hour) * 60);
        } else {
          minsUntil = (isPeakDay && hour < startLocal)
            ? Math.floor((startLocal - hour) * 60)
            : minsUntilNextPeak(now, peakDays, startLocal);
        }
      }
    } else {
      minsUntil = minsUntilNextPeak(now, peakDays, startLocal);
    }

    ctx.isPeak = isPeak;
    const labelPeak = peak.label_peak || 'Peak';
    const labelOff = peak.label_offpeak || 'Off-Peak';

    if (isPeak) {
      const t = fmtDur(minsLeft);
      const bg = minsLeft <= 30 ? BG_GREEN : minsLeft <= 120 ? BG_YELLOW : BG_RED;
      const range = `${DIM}${fmtHour(startLocal)}-${fmtHour(endLocal)}${RST}`;
      return `${bg} ${labelPeak} ${RST} ${WHITE}\u2192 ends in ${t}${RST} ${range}`;
    }
    if (minsUntil > 0) {
      return `${BG_GREEN} ${labelOff} ${RST} ${DIM}peak in ${fmtDur(minsUntil)}${RST}`;
    }
    return `${BG_GREEN} ${labelOff} ${RST}`;
  },
  model(ctx) {
    const n = (ctx.stdin.model || {}).display_name || '';
    if (!n) return '';
    return `${BLUE}${n.split('(')[0].trim()}${RST}`;
  },
  context(ctx) {
    const cw = ctx.stdin.context_window || {};
    const size = cw.context_window_size || 0;
    if (!size) return '';
    const u = cw.current_usage || {};
    const cur = (u.input_tokens||0) + (u.cache_creation_input_tokens||0) + (u.cache_read_input_tokens||0);
    const pct = Math.floor(cur * 100 / size);
    return `${colorPct(pct)}${pct}%${RST}`;
  },
  git_branch(ctx) { const b = git('branch','--show-current'); ctx.gitBranch=b; return b ? `${DIM}${b}${RST}` : ''; },
  git_dirty(ctx) {
    const p = git('status','--porcelain');
    const uncommitted = p ? p.split('\n').filter(Boolean).length : 0;
    let unpushed = 0;
    if (ctx.gitBranch) {
      const a = git('rev-list','--count','@{u}..HEAD');
      if (a && a !== '0') unpushed = parseInt(a);
    }
    if (!uncommitted && !unpushed) return `${GREEN}saved${RST}`;
    if (uncommitted && unpushed) return `${YELLOW}${uncommitted} changed, ${unpushed} unpushed${RST}`;
    if (uncommitted) return `${YELLOW}${uncommitted} unsaved${RST}`;
    return `${YELLOW}${unpushed} unpushed${RST}`;
  },
  cost(ctx) { const c = (ctx.stdin.cost || {}).total_cost_usd; return c != null ? `${MAGENTA}$${c.toFixed(2)}${RST}` : ''; },
  duration(ctx) { const ms = (ctx.stdin.cost || {}).total_duration_ms; if (!ms) return ''; return `${BLUE}${fmtSecs(Math.floor(ms/1000))}${RST}`; },
  lines(ctx) { const a = (ctx.stdin.cost||{}).total_lines_added||0, r = (ctx.stdin.cost||{}).total_lines_removed||0; return (a||r) ? `${GREEN}+${a}${RST}/${RED}-${r}${RST}` : ''; },
  effort(ctx) {
    try {
      const p = path.join(process.env.HOME || process.env.USERPROFILE, '.claude', 'settings.json');
      const s = JSON.parse(fs.readFileSync(p, 'utf8'));
      const level = s.effortLevel || '';
      if (!level) return '';
      const labels = { low: 'LO', medium: 'MED', high: 'HI' };
      const colors = { low: DIM, medium: YELLOW, high: GREEN };
      return `${colors[level] || DIM}${labels[level] || level.toUpperCase()}${RST}`;
    } catch { return ''; }
  },
  env(ctx) {
    if (process.env.SSH_CLIENT || process.env.SSH_TTY || process.env.SSH_CONNECTION) {
      return `${MAGENTA}REMOTE${RST}`;
    }
    return `${CYAN}LOCAL${RST}`;
  },
};

// Backward compat
SEGMENTS.promo_2x = SEGMENTS.peak_hours;

// ── Telemetry ──
const TELEMETRY_URL = 'https://statusline-telemetry.nadavf.workers.dev/ping';
const HEARTBEAT_PATH = path.join(process.env.HOME || process.env.USERPROFILE, '.claude', '.statusline-heartbeat');

function maybeHeartbeat(config) {
  if (config.telemetry === false) return;
  try {
    const today = new Date().toISOString().slice(0, 10);
    if (fs.existsSync(HEARTBEAT_PATH)) {
      const mtime = fs.statSync(HEARTBEAT_PATH).mtime.toISOString().slice(0, 10);
      if (mtime === today) return;
    }
    const uid = crypto.createHash('sha256').update(`${os.hostname()}:${os.userInfo().username}`).digest('hex').slice(0, 16);
    const payload = JSON.stringify({
      id: uid, v: '2.1', engine: 'node', tier: config.tier || 'standard',
      os: process.platform, event: 'heartbeat',
    });
    fs.writeFileSync(HEARTBEAT_PATH, today);
    const child = spawn('curl', ['-s', '-o', '/dev/null', '--max-time', '3',
      '-X', 'POST', '-H', 'Content-Type: application/json', '-d', payload, TELEMETRY_URL],
      { stdio: 'ignore', detached: true });
    child.unref();
  } catch {}
}

// ── Main ──
function main() {
  const config = loadConfig();
  maybeHeartbeat(config);
  let stdin = {};
  try {
    const raw = fs.readFileSync(0, 'utf8').trim();
    if (raw) stdin = JSON.parse(raw);
  } catch {}

  const { now, tzName, offsetHours } = getLocalTime();
  const schedule = loadSchedule(config);

  const ctx = { config, stdin, now, tzName, offsetHours, schedule, isPeak: false };
  const enabled = getEnabled(config);
  if (!enabled.includes('banner')) {
    enabled.unshift('banner');
  }

  const parts = [];
  const gitParts = [];
  for (const name of enabled) {
    const fn = SEGMENTS[name];
    if (!fn) continue;
    const r = fn(ctx);
    if (!r) continue;
    if (['git_branch','git_dirty'].includes(name)) gitParts.push(r);
    else parts.push(r);
  }
  if (gitParts.length) parts.push(gitParts.join(' '));

  const arrowColor = ctx.isPeak ? YELLOW : GREEN;
  const arrow = ` ${arrowColor}\u25b8${RST} `;
  process.stdout.write(parts.join(arrow));
}

main();
