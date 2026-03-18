#!/usr/bin/env node
/**
 * Claude Code statusline — Node.js fallback engine.
 * Used when Python is not available.
 * Supports: time, promo_2x, model, context, git, cost, duration, lines.
 * Does NOT support: rate_limits, ts_errors (use Python for those).
 */

const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');

// ── ANSI ──
const RST = '\x1b[0m', BOLD = '\x1b[1m', DIM = '\x1b[2m';
const RED = '\x1b[31m', GREEN = '\x1b[32m', YELLOW = '\x1b[33m';
const BLUE = '\x1b[34m', MAGENTA = '\x1b[35m', CYAN = '\x1b[36m';
const WHITE = '\x1b[38;2;220;220;220m';
const BG_GREEN = '\x1b[38;5;255;48;5;28m';
const BG_YELLOW = '\x1b[38;5;16;48;5;220m';
const BG_RED = '\x1b[38;5;255;48;5;124m';
const BG_GRAY = '\x1b[48;5;236m';

// ── Config ──
const TIER_PRESETS = {
  minimal: ['promo_2x', 'git_branch', 'git_dirty'],
  standard: ['promo_2x', 'model', 'context', 'git_branch', 'git_dirty', 'cost'],
  full: ['promo_2x', 'model', 'context', 'git_branch', 'git_dirty', 'cost'],
};

function loadConfig() {
  const p = path.join(process.env.HOME || process.env.USERPROFILE, '.claude', 'statusline-config.json');
  try { return JSON.parse(fs.readFileSync(p, 'utf8')); } catch { return { tier: 'standard' }; }
}

function getEnabled(config) {
  const tier = config.tier || 'standard';
  if (tier === 'custom') return Object.entries(config.segments || {}).filter(([,v]) => v).map(([k]) => k);
  return TIER_PRESETS[tier] || TIER_PRESETS.standard;
}

// ── Helpers ──
function fmtDur(mins) { const h = Math.floor(mins/60), m = mins%60; return h > 0 ? `${h}h ${String(m).padStart(2,'0')}m` : `${m}m`; }
function fmtSecs(s) { const h=Math.floor(s/3600), m=Math.floor((s%3600)/60), sec=s%60; return h>0?`${h}h${String(m).padStart(2,'0')}m`:m>0?`${m}m${String(sec).padStart(2,'0')}s`:`${sec}s`; }
function colorPct(p) { return p >= 80 ? RED : p >= 50 ? YELLOW : GREEN; }
function git(...args) { try { return execFileSync('git', args, { timeout: 2000, encoding: 'utf8' }).trim(); } catch { return ''; } }

function getIsraelTime() {
  const utc = new Date();
  const m = utc.getUTCMonth() + 1, d = utc.getUTCDate();
  const offset = ((m > 3 || (m === 3 && d >= 27)) && (m < 10 || (m === 10 && d < 25))) ? 3 : 2;
  const il = new Date(utc.getTime() + offset * 3600000);
  return { il, offset };
}

// ── Segments ──
const SEGMENTS = {
  time(ctx) {
    const h = String(ctx.il.getUTCHours()).padStart(2,'0');
    const m = String(ctx.il.getUTCMinutes()).padStart(2,'0');
    return `${WHITE}${BOLD}${h}:${m}${RST}`;
  },
  promo_2x(ctx) {
    const { il, offset, config } = ctx;
    const ilDate = parseInt(il.toISOString().slice(0,10).replace(/-/g,''));
    const ps = config.promo_start || 20260313, pe = config.promo_end || 20260327;
    if (ilDate < ps || ilDate > pe) return `${DIM}Promo ended${RST}`;

    const hour = il.getUTCHours(), minute = il.getUTCMinutes();
    const dow = il.getUTCDay(); // 0=Sun
    const nowMins = hour * 60 + minute;
    const peakS = 14, peakE = 20; // Israel local time

    let doubled = false, reason = '', minsLeft = 0, minsUntil = 0;
    // Weekend: Sat(6) 09:00 → Mon(1) 09:00
    if (dow === 6 && nowMins >= 540) { doubled=true; reason='weekend'; minsLeft=(1440-nowMins)+1440+540; }
    else if (dow === 0) { doubled=true; reason='weekend'; minsLeft=(1440-nowMins)+540; }
    else if (dow === 1 && nowMins < 540) { doubled=true; reason='weekend'; minsLeft=540-nowMins; }
    else if (nowMins >= peakE*60) { doubled=true; reason='off-peak'; minsLeft=(1440-nowMins)+peakS*60; }
    else if (nowMins < peakS*60) { doubled=true; reason='off-peak'; minsLeft=peakS*60-nowMins; }

    if (!doubled) minsUntil = peakE*60 - nowMins;
    ctx.is2x = doubled;

    if (doubled) {
      const t = fmtDur(minsLeft);
      const bg = minsLeft > 180 ? BG_GREEN : minsLeft > 60 ? BG_YELLOW : BG_RED;
      const wk = reason === 'weekend' ? ` ${DIM}weekend${RST}` : '';
      return `${bg} \u26a1 2x ${RST} ${DIM}${t} left${RST}${wk}`;
    }
    return `${BG_GRAY} PEAK ${RST} ${DIM}\u2192 2x in ${fmtDur(minsUntil)}${RST}`;
  },
  model(ctx) {
    const n = (ctx.stdin.model || {}).display_name || '';
    return n ? `${BLUE}${n}${RST}` : '';
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
    if (!uncommitted && !unpushed) return '';
    if (uncommitted && unpushed) return `${YELLOW}${uncommitted} changed, ${unpushed} unpushed${RST}`;
    if (uncommitted) return `${YELLOW}${uncommitted} unsaved${RST}`;
    return `${YELLOW}${unpushed} unpushed${RST}`;
  },
  cost(ctx) { const c = (ctx.stdin.cost || {}).total_cost_usd; return c != null ? `${MAGENTA}$${c.toFixed(2)}${RST}` : ''; },
  duration(ctx) { const ms = (ctx.stdin.cost || {}).total_duration_ms; if (!ms) return ''; return `${BLUE}${fmtSecs(Math.floor(ms/1000))}${RST}`; },
  lines(ctx) { const a = (ctx.stdin.cost||{}).total_lines_added||0, r = (ctx.stdin.cost||{}).total_lines_removed||0; return (a||r) ? `${GREEN}+${a}${RST}/${RED}-${r}${RST}` : ''; },
};

// ── Main ──
function main() {
  const config = loadConfig();
  let stdin = {};
  try {
    const raw = fs.readFileSync(0, 'utf8').trim();
    if (raw) stdin = JSON.parse(raw);
  } catch {}

  const { il, offset } = getIsraelTime();
  const ctx = { config, stdin, il, offset, is2x: false };
  const enabled = getEnabled(config);

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

  const arrowColor = ctx.is2x ? GREEN : YELLOW;
  const arrow = ` ${arrowColor}\u25b8${RST} `;
  process.stdout.write(parts.join(arrow));
}

main();
