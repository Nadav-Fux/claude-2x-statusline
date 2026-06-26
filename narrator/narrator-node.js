/**
 * narrator-node — Full narrator pipeline for Node.js runtime.
 *
 * Port of narrator/{engine,observations,scoring,memory,haiku}.py
 * into a single self-contained module so Node.js-only users get the
 * same rules-engine + optional Haiku layer as Python users.
 *
 * Entry point: run(mode) → string | null
 */

const fs = require('fs');
const os = require('os');
const path = require('path');
const https = require('https');
const rs = require(path.join(__dirname, '..', 'lib', 'rolling_state'));

const HOME = process.env.HOME || process.env.USERPROFILE;
const CLAUDE_DIR = path.join(HOME, '.claude');
const MEMORY_PATH = path.join(CLAUDE_DIR, 'narrator-memory.json');
const MEMORY_TMP = path.join(CLAUDE_DIR, 'narrator-memory.json.tmp');

const COST_MILESTONES = [5, 10, 25, 50, 100];

// ── Memory ──

function defaultCurrent(sessionId = '') {
  return { session_id: sessionId, started_at: Date.now() / 1000, last_emit_at: 0, last_haiku_at: 0, rolling_observations: [], delivered_narratives: [], cost_milestones_hit: [], prompt_count: 0 };
}

function loadMemory() {
  try { const d = JSON.parse(fs.readFileSync(MEMORY_PATH, 'utf8')); if (!d.current) d.current = defaultCurrent(); return d; }
  catch { return { current: defaultCurrent(), prior_sessions: [] }; }
}

function saveMemory(data) {
  try {
    fs.mkdirSync(CLAUDE_DIR, { recursive: true, mode: 0o700 });
    fs.writeFileSync(MEMORY_TMP, JSON.stringify(data), 'utf8');
    fs.renameSync(MEMORY_TMP, MEMORY_PATH);
  } catch {}
}

function rotateSession(data, newId) {
  const old = data.current || defaultCurrent();
  const prior = [{ session_id: old.session_id, ended_at: Date.now() / 1000, narratives: (old.delivered_narratives || []).slice(-5) }, ...(data.prior_sessions || [])].slice(0, 3);
  return { current: defaultCurrent(newId), prior_sessions: prior };
}

// ── Observations ──

// Resolve the TRUE context window size (1M-aware). Mirrors the Python
// _resolve_ctx_window_size: env override > stdin size > bar's context file
// (size, else 1M from model name) > stdin model 1m detection > 200k default.
// Without this, ~160k tokens reads as 80% of 200k and fires pressure templates
// when it is really 16% of a 1,000,000 window.
function windowFromName(name) {
  // Extract a window size encoded in a model name: '[1m]'->1e6, '(500k context)'->5e5.
  // Only matches number+unit in brackets/parens or next to a context/token/window word,
  // so version numbers ('4-8') and param counts ('31b') never false-match.
  if (!name) return null;
  const res = [
    /[[(]\s*(\d+(?:\.\d+)?)\s*([mk])\b/i,
    /(\d+(?:\.\d+)?)\s*([mk])\s*(?:context|tokens?|ctx|window)/i,
  ];
  for (const rx of res) {
    const m = name.match(rx);
    if (m) return Math.round(parseFloat(m[1]) * (m[2].toLowerCase() === 'm' ? 1000000 : 1000));
  }
  return null;
}

// parseResetAt: parse a usage-cache window block's `resets_at` ISO string into a
// Date (or null when missing/malformed). Mirrors the Python _parse_reset_at /
// the engine's _format_reset parsing; never throws.
function parseResetAt(block) {
  if (!block || typeof block !== 'object') return null;
  const iso = block.resets_at;
  if (!iso || typeof iso !== 'string' || iso === 'null') return null;
  const dt = new Date(iso);
  if (Number.isNaN(dt.getTime())) return null;
  return dt;
}

function resolveCtxWindowSize(stdinData) {
  const env = (process.env.STATUSLINE_CTX_WINDOW || '').trim();
  if (/^\d+$/.test(env) && Number(env) > 0) return Number(env);

  const cfile = loadStatuslineContext(stdinData);

  // 1M-context models FIRST. Claude Code can still report context_window_size=200000
  // on stdin for a [1m] session; trusting it mis-scales the % ~5x and fires false
  // "context full" pressure at ~16% real usage. Detect the 1M model and override.
  const model = (stdinData && stdinData.model) || {};
  const name = `${model.display_name || ''} ${model.id || ''}`;
  const cfileModel = String((cfile && cfile.model) || '');
  const win = windowFromName(name) || windowFromName(cfileModel);
  if (win) return win;

  const cw = (stdinData && stdinData.context_window) || {};
  const size = Number(cw.context_window_size || 0);
  if (size > 0) return size;

  if (cfile && Object.keys(cfile).length) {
    const csize = Number(cfile.context_window_size || 0);
    if (csize > 0) return csize;
  }

  return 200000;
}

// loadStatuslineContext: the bar's global context file (authoritative window +
// current_usage + session_id), or {} when absent/stale (>5 min). Mirrors the
// Python _load_statusline_context freshness guard.
function loadStatuslineContext(stdinData) {
  try {
    const p = path.join(os.tmpdir(), 'claude', 'statusline-context.json');
    const data = JSON.parse(fs.readFileSync(p, 'utf8'));
    // Our own session's file is authoritative at any age; the 5-min guard only
    // applies to a different/unknown session (avoids the stale-file fallback to
    // the over-counting rolling sum that reported 100%).
    const ourSid = (stdinData || {}).session_id, fileSid = data.session_id;
    if (ourSid && fileSid && ourSid === fileSid) return data;
    if (Date.now() / 1000 - fs.statSync(p).mtimeMs / 1000 > 300) return {};
    return data;
  } catch { return {}; }
}

// Line count of the project CLAUDE.md (cwd/CLAUDE.md), 0 if none. Boris Cherny /
// Anthropic guidance: ~60 optimal, 200 ceiling — rules past it get deprioritized.
function countClaudeMdLines(stdinData) {
  try {
    const cwd = (stdinData && stdinData.cwd) || process.cwd();
    const p = path.join(cwd, 'CLAUDE.md');
    const txt = fs.readFileSync(p, 'utf8');
    if (!txt) return 0;
    return txt.split('\n').length - (txt.endsWith('\n') ? 1 : 0);
  } catch {
    return 0;
  }
}

function buildObservation(memory) {
  const obs = {
    cost_usd: 0, burn_10m: null, burn_session: null,
    ctx_pct: 0, ctx_mins_left: null,
    cache_pct: 0, cache_delta_5m: null,
    is_peak: false, schedule_mode: 'normal',
    session_duration_min: 0, prompt_count: 0,
    rate_limit_5h_pct: 0, rate_limit_7d_pct: 0,
    // Rate-limit reset times (Date|null) + derived hours-until-weekly-reset; let
    // the rate-limit insight reason about WHERE we are in the 7-day reset cycle.
    rate_limit_5h_resets_at: null, rate_limit_7d_resets_at: null,
    rate_limit_7d_hours_left: null,
    cost_delta_5m: 0, cost_delta_20m: 0, ctx_delta_5m: 0,
    total_input_tokens: 0, total_output_tokens: 0,
    cache_read_tokens: 0, cache_creation_tokens: 0,
    ctx_window_size: 200000, cost_milestones_hit: [],
    subagent_tokens_live: 0, subagent_runs_session: 0, active_workflow_agents: 0,
    claude_md_lines: 0,
  };

  // Stdin (piped from hook)
  let stdinData = null;
  try { if (!process.stdin.isTTY) { const raw = fs.readFileSync(0, 'utf8').trim(); if (raw) stdinData = JSON.parse(raw); } } catch {}

  if (stdinData) {
    const c = stdinData.cost || {};
    obs.cost_usd = Number(c.total_cost_usd || 0);
    if (c.total_duration_ms) obs.session_duration_min = c.total_duration_ms / 60000;
    const cw = stdinData.context_window || {};
    // Raw stdin value only (0 if absent); resolveCtxWindowSize() finalizes below.
    obs.ctx_window_size = Number(cw.context_window_size || 0);
    const u = cw.current_usage || {};
    obs.total_input_tokens = Number(u.input_tokens || 0);
    obs.total_output_tokens = Number(u.output_tokens || 0);
    obs.cache_read_tokens = Number(u.cache_read_input_tokens || 0);
    obs.cache_creation_tokens = Number(u.cache_creation_input_tokens || 0);
  }

  try {
    const usagePath = path.join(CLAUDE_DIR, 'statusline-usage-cache.json');
    const st = fs.statSync(usagePath);
    if (Date.now() / 1000 - st.mtimeMs / 1000 <= 300) {
      const usage = JSON.parse(fs.readFileSync(usagePath, 'utf8'));
      const fiveHour = usage.five_hour || {};
      const sevenDay = usage.seven_day || {};
      obs.rate_limit_5h_pct = Number(fiveHour.utilization || 0);
      obs.rate_limit_7d_pct = Number(sevenDay.utilization || 0);
      // Reset times → cycle-awareness. Use the same now source (Date.now()) the
      // rest of buildObservation uses, so the hours-left math stays consistent.
      obs.rate_limit_5h_resets_at = parseResetAt(usage.five_hour);
      obs.rate_limit_7d_resets_at = parseResetAt(usage.seven_day);
      if (obs.rate_limit_7d_resets_at) {
        const secsLeft = obs.rate_limit_7d_resets_at.getTime() / 1000 - Date.now() / 1000;
        obs.rate_limit_7d_hours_left = Math.max(0, secsLeft / 3600);
      }
    }
  } catch {}

  // Rolling state
  try {
    if (stdinData?.session_id) rs.setSessionId(stdinData.session_id);
    obs.burn_10m = rs.rollingRate(10);
    obs.cache_delta_5m = rs.cacheDelta(5);
  } catch {}

  // If stdin didn't carry token data (the hook case), fall back to the latest
  // session-scoped rolling sample — mirrors the Python path so the ctx_pct-gated
  // advice below actually works in Node-only installs.
  if (obs.total_input_tokens === 0) {
    try {
      const s = rs.latestSample();
      if (s) {
        obs.total_input_tokens = Number(s.tokens_in || 0);
        obs.total_output_tokens = Number(s.tokens_out || 0);
        obs.cache_read_tokens = Number(s.cache_read || 0);
        obs.cache_creation_tokens = Number(s.cache_creation || 0);
      }
    } catch {}
  }

  // Session burn
  if (obs.session_duration_min >= 1 && obs.cost_usd > 0) {
    const candidate = obs.cost_usd / (obs.session_duration_min / 60);
    if (candidate <= 200) obs.burn_session = candidate;
  }

  // True context window size (1M-aware; not the bare 200k default)
  obs.ctx_window_size = resolveCtxWindowSize(stdinData);

  // Project CLAUDE.md size (best-practice hygiene hint)
  obs.claude_md_lines = countClaudeMdLines(stdinData);

  // Context %. Prefer the bar's authoritative current_usage from the context
  // file (the live occupancy Claude Code reports); the rolling token sum
  // (input+cache_read+cache_creation) over-counts and clamps to 100% in long
  // sessions. The file is global (last render wins) and current_usage is
  // session-specific, so only trust it when its session_id matches ours
  // (lenient when either is absent). A legit 0 (fresh empty window) IS
  // authoritative — don't fall back to the rolling sum for it.
  const barCtx = loadStatuslineContext(stdinData);
  const barUsage = barCtx.current_usage;
  const barSid = barCtx.session_id;
  const ourSid = (stdinData || {}).session_id;
  const usageTrusted = !barSid || !ourSid || barSid === ourSid;
  if (obs.ctx_window_size > 0 && usageTrusted && typeof barUsage === 'number' && barUsage >= 0) {
    obs.ctx_pct = Math.min(100, barUsage / obs.ctx_window_size * 100);
  } else if (obs.ctx_window_size > 0 && obs.total_input_tokens > 0) {
    const used = obs.total_input_tokens + obs.cache_creation_tokens + obs.cache_read_tokens;
    obs.ctx_pct = Math.min(100, used / obs.ctx_window_size * 100);
  }
  if (obs.ctx_pct > 0 && obs.session_duration_min > 1) {
    const rate = obs.ctx_pct / obs.session_duration_min;
    if (rate > 0) obs.ctx_mins_left = (100 - obs.ctx_pct) / rate;
  }

  // Cache %
  if (obs.total_input_tokens > 0 && obs.cache_read_tokens > 0) {
    obs.cache_pct = obs.cache_read_tokens / obs.total_input_tokens * 100;
  }

  try { populateWorkflowObservation(obs, stdinData || {}); } catch {}

  // Memory-derived fields
  const cur = memory.current || {};
  if (cur.started_at) obs.session_duration_min = Math.max(obs.session_duration_min, (Date.now() / 1000 - cur.started_at) / 60);
  obs.prompt_count = cur.prompt_count || 0;
  obs.cost_milestones_hit = cur.cost_milestones_hit || [];

  // Peak hours detection (parallel to Python's _is_peak_hours)
  try { obs.is_peak = detectIsPeak(); } catch {}

  // Trend fields from rolling_observations
  const rollingObs = cur.rolling_observations || [];
  const trends = computeTrendFields(rollingObs, Date.now() / 1000);
  if (trends.cost_5m_ago != null) obs.cost_delta_5m = obs.cost_usd - trends.cost_5m_ago;
  if (trends.cost_20m_ago != null) obs.cost_delta_20m = obs.cost_usd - trends.cost_20m_ago;
  if (trends.ctx_5m_ago != null) obs.ctx_delta_5m = obs.ctx_pct - trends.ctx_5m_ago;

  return obs;
}

// ── Peak hours ──

function detectIsPeak() {
  let schedule;
  try { schedule = JSON.parse(fs.readFileSync(path.join(CLAUDE_DIR, 'statusline-schedule.json'), 'utf8')); }
  catch { return false; }
  if (!schedule || schedule.mode === 'normal') return false;
  const peak = schedule.peak;
  if (!peak || !peak.enabled) return false;

  const now = new Date();
  const localOffset = -now.getTimezoneOffset() / 60;
  const hour = now.getHours() + now.getMinutes() / 60;
  const weekday = now.getDay() === 0 ? 7 : now.getDay();
  const peakDays = peak.days || [1,2,3,4,5];
  const srcOffset = getSourceOffsetForPeak(peak.tz || 'America/Los_Angeles');
  const rawStart = (peak.start || 5) - srcOffset + localOffset;
  const peakDayOffset = Math.floor(rawStart / 24);
  const startLocal = ((rawStart % 24) + 24) % 24;
  const endLocal = (((peak.end || 11) - srcOffset + localOffset) % 24 + 24) % 24;
  const effectiveDays = peakDays.map(d => shiftWd(d, peakDayOffset));
  const isPeakDay = effectiveDays.includes(weekday);
  const prevWd = weekday === 1 ? 7 : weekday - 1;
  const prevWasPeak = effectiveDays.includes(prevWd);

  if (endLocal > startLocal) {
    if (isPeakDay && hour >= startLocal && hour < endLocal) return true;
  } else {
    if (isPeakDay && hour >= startLocal) return true;
    if (prevWasPeak && hour < endLocal) return true;
  }
  return false;
}

function shiftWd(d, delta) { return ((d - 1 + delta) % 7 + 7) % 7 + 1; }

function getSourceOffsetForPeak(tz) {
  if (!tz || tz === 'UTC' || tz === 'Etc/UTC') return 0;
  if (tz === 'America/Los_Angeles') return getPacOffset();
  const pac = getPacOffset();
  const offsets = { 'America/New_York': pac + 3, 'America/Chicago': pac + 2, 'America/Denver': pac + 1 };
  return offsets[tz] ?? pac;
}

function getPacOffset() {
  const now = new Date(), year = now.getUTCFullYear();
  const mar1 = new Date(Date.UTC(year, 2, 1));
  const dstStart = new Date(Date.UTC(year, 2, 1 + ((7 - mar1.getUTCDay()) % 7) + 7, 10));
  const nov1 = new Date(Date.UTC(year, 10, 1));
  const dstEnd = new Date(Date.UTC(year, 10, 1 + ((7 - nov1.getUTCDay()) % 7), 9));
  return (now >= dstStart && now < dstEnd) ? -7 : -8;
}

// ── Trend fields ──

function computeTrendFields(rollingObs, now) {
  const result = { cost_5m_ago: null, cost_20m_ago: null, ctx_5m_ago: null };
  if (!rollingObs || !rollingObs.length) return result;

  const target5m = now - 5 * 60;
  const target20m = now - 20 * 60;

  const closest = (target) => {
    const candidates = rollingObs.filter(o => typeof o.ts === 'number');
    if (!candidates.length) return null;
    let best = candidates[0], bestDist = Math.abs(candidates[0].ts - target);
    for (let i = 1; i < candidates.length; i++) {
      const dist = Math.abs(candidates[i].ts - target);
      if (dist < bestDist) { best = candidates[i]; bestDist = dist; }
    }
    return best;
  };

  const obs5m = closest(target5m);
  const obs20m = closest(target20m);

  if (obs5m && Math.abs(obs5m.ts - target5m) < 180) {
    result.cost_5m_ago = obs5m.cost_usd ?? null;
    result.ctx_5m_ago = obs5m.ctx_pct ?? null;
  }
  if (obs20m && Math.abs(obs20m.ts - target20m) < 300) {
    result.cost_20m_ago = obs20m.cost_usd ?? null;
  }
  return result;
}

const USAGE_RE = /"usage"\s*:\s*\{\s*"input_tokens"\s*:\s*(\d+)\s*,\s*"cache_creation_input_tokens"\s*:\s*(\d+)\s*,\s*"cache_read_input_tokens"\s*:\s*(\d+)\s*,\s*"output_tokens"\s*:\s*(\d+)/g;

function readLastUsage(filePath) {
  try {
    const fd = fs.openSync(filePath, 'r');
    try {
      const stat = fs.fstatSync(fd);
      const chunkSize = Math.min(65536, stat.size);
      const buffer = Buffer.alloc(chunkSize);
      fs.readSync(fd, buffer, 0, chunkSize, Math.max(0, stat.size - chunkSize));
      const tail = buffer.toString('utf8');
      const matches = [...tail.matchAll(USAGE_RE)];
      if (!matches.length) return 0;
      const last = matches[matches.length - 1];
      return Number(last[1]) + Number(last[2]) + Number(last[3]);
    } finally {
      fs.closeSync(fd);
    }
  } catch { return 0; }
}

function populateWorkflowObservation(obs, stdinData) {
  const tp = stdinData.transcript_path || '';
  if (!tp) return;
  const sessionDir = tp.endsWith('.jsonl') ? tp.slice(0, -6) : tp;
  const liveBase = path.join(sessionDir, 'subagents', 'workflows');
  const completedDir = path.join(sessionDir, 'workflows');
  let liveAgents = 0, liveTokens = 0;
  try {
    for (const wfName of fs.readdirSync(liveBase)) {
      if (!wfName.startsWith('wf_')) continue;
      if (fs.existsSync(path.join(completedDir, `${wfName}.json`))) continue;
      const wfDir = path.join(liveBase, wfName);
      for (const fileName of fs.readdirSync(wfDir)) {
        if (!/^agent-.*\.jsonl$/.test(fileName)) continue;
        liveAgents += 1;
        liveTokens += readLastUsage(path.join(wfDir, fileName));
      }
    }
  } catch {}
  obs.active_workflow_agents = liveAgents;
  obs.subagent_tokens_live = liveTokens;
  if (liveAgents > 0) return;
  try {
    let runs = 0;
    for (const name of fs.readdirSync(completedDir)) {
      if (!/^wf_.*\.json$/.test(name)) continue;
      try {
        const manifest = JSON.parse(fs.readFileSync(path.join(completedDir, name), 'utf8'));
        if (manifest.status === 'completed') runs += 1;
      } catch {}
    }
    obs.subagent_runs_session = runs;
  } catch {}
}

// ── Scoring ──

function novelty(key, memory) {
  const recent = (memory.current?.delivered_narratives || []).slice(-3);
  for (const entry of recent) {
    if ((entry.template_key === key) || (typeof entry === 'string' && entry.includes(key))) return 0;
  }
  return 10;
}

function nextMilestone(cost) {
  const crossed = COST_MILESTONES.filter(m => cost >= m);
  return crossed.length ? crossed[crossed.length - 1] : null;
}

function buildInsights(obs, memory) {
  const results = [];
  const ctx = obs.ctx_pct, ctxLeft = obs.ctx_mins_left;
  const burn10 = obs.burn_10m, burnSess = obs.burn_session;
  const effectiveBurn = burn10 ?? burnSess;

  if (ctxLeft != null && ctxLeft < 30) {
    const n = Math.ceil(ctxLeft), k = 'ctx_critical';
    results.push({ text: `Context fills in ~${n}m — compact now or history gets truncated.`, text_he: `ה-context מתמלא תוך ~${n} דקות — /compact עכשיו, אחרת ההיסטוריה תיחתך.`, urgency: 10, novelty: novelty(k, memory), actionability: 10, uniqueness: 10, template_key: k });
  } else if (ctxLeft != null && ctxLeft < 60) {
    const n = Math.ceil(ctxLeft), k = 'ctx_warning';
    results.push({ text: `Context at ~${ctx.toFixed(0)}% with ${n}m until full. Finish current thread before starting new work.`, text_he: `Context ב-~${ctx.toFixed(0)}% — ${n} דקות עד שהוא מתמלא. סיים את הנושא הנוכחי לפני שמתחילים משהו חדש.`, urgency: 7, novelty: novelty(k, memory), actionability: 7, uniqueness: 5, template_key: k });
  } else if (ctx >= 80 && (ctxLeft == null || ctxLeft > 30)) {
    const k = 'ctx_80_headroom';
    results.push({ text: `Context at ${ctx.toFixed(0)}% — headroom shrinking, plan a natural break soon.`, text_he: `Context ב-${ctx.toFixed(0)}% — המרווח מצטמצם, תתכנן עצירה טבעית בקרוב.`, urgency: 7, novelty: novelty(k, memory), actionability: 7, uniqueness: 5, template_key: k });
  }

  if (effectiveBurn != null && ((burn10 != null && burn10 >= 10) || (burnSess != null && burnSess >= 15))) {
    const rate = burn10 ?? burnSess, minsLeft = rate > 0 ? Math.max(0, Math.floor((50 - obs.cost_usd) / rate * 60)) : 0, k = 'burn_high';
    results.push({ text: `Burning $${rate.toFixed(1)}/hr — at this rate your 5-hour budget ends in ~${minsLeft}m. Consider Sonnet for simple steps.`, text_he: `שורף $${rate.toFixed(1)}/hr — בקצב הזה תגמור את budget 5 השעות בעוד ~${minsLeft} דקות. שקול Sonnet לצעדים פשוטים.`, urgency: 10, novelty: novelty(k, memory), actionability: 10, uniqueness: 10, template_key: k });
  } else if (effectiveBurn != null && effectiveBurn >= 5) {
    const k = 'burn_moderate', label = burn10 != null ? '(10m)' : '(session)';
    results.push({ text: `Spending $${effectiveBurn.toFixed(1)}/hr ${label} — steady pace for complex work. Budget OK.`, text_he: `מוציא $${effectiveBurn.toFixed(1)}/hr ${label} — קצב יציב לעבודה מורכבת. Budget בסדר.`, urgency: 4, novelty: novelty(k, memory), actionability: 5, uniqueness: 5, template_key: k });
  } else if (effectiveBurn != null && effectiveBurn < 5 && obs.session_duration_min > 5) {
    const k = 'burn_low';
    results.push({ text: `Spending $${effectiveBurn.toFixed(1)}/hr — cheap session, cache doing its job. Good time to batch cleanup, tests, and mechanical follow-through.`, text_he: `מוציא $${effectiveBurn.toFixed(1)}/hr — סשן זול, ה-cache עושה את שלו. זה זמן טוב לסגור cleanup, בדיקות ומשימות מכניות של follow-through.`, urgency: 4, novelty: novelty(k, memory), actionability: 2, uniqueness: 5, template_key: k });
  }

  if (obs.cache_pct < 50 && obs.session_duration_min > 2 && obs.total_input_tokens > 0) {
    const k = 'cache_low';
    results.push({ text: `Cache hit ratio is ${obs.cache_pct.toFixed(0)}% — most tokens are being created fresh. If looping on same files they should warm up shortly.`, text_he: `אחוז ה-cache hit הוא ${obs.cache_pct.toFixed(0)}% — רוב הטוקנים נוצרים מחדש. אם חוזרים על אותם קבצים, ה-cache יתחמם בקרוב.`, urgency: 4, novelty: novelty(k, memory), actionability: 5, uniqueness: 10, template_key: k });
  }

  if (obs.cache_delta_5m != null && obs.cache_delta_5m > 500) {
    const dk = obs.cache_delta_5m / 1000, sp = Math.max(0, Math.min(90, obs.cache_pct * 0.9)), k = 'cache_active';
    results.push({ text: `Cache saving ~${dk.toFixed(0)}k tokens / 5 min — keeping effective cost ~${sp.toFixed(0)}% below raw.`, text_he: `Cache חוסך ~${dk.toFixed(0)}k טוקנים ב-5 דקות — העלות האפקטיבית נמוכה ב-~${sp.toFixed(0)}% ממה שהייתה בלי cache.`, urgency: 4, novelty: novelty(k, memory), actionability: 5, uniqueness: 10, template_key: k });
  }

  const milestone = nextMilestone(obs.cost_usd);
  if (milestone != null && !obs.cost_milestones_hit.includes(milestone)) {
    let rate = obs.burn_10m ?? obs.burn_session;
    if (rate == null && obs.session_duration_min >= 1 && obs.cost_usd > 0) { const raw = obs.cost_usd / (obs.session_duration_min / 60); if (raw <= 200) rate = raw; }
    if (rate != null && rate > 0) {
      const projected = rate * 5, k = `milestone_${milestone}`;
      results.push({ text: `You've crossed $${milestone} — at current rate, extrapolates to ~$${projected.toFixed(0)} by 5h mark. Worth it?`, text_he: `חצית את ה-$${milestone} — בקצב הנוכחי זה מתורגם ל-~$${projected.toFixed(0)} עד סוף 5 שעות. שווה את זה?`, urgency: 7, novelty: novelty(k, memory), actionability: 5, uniqueness: 10, template_key: k });
    }
  }

  // Rate limit (cycle-aware tiers). The 7-day weekly window has a "day in the
  // cycle" concept — 30% on day 1 differs from 30% on day 6 — so we position the
  // utilisation against the even pace expected by now. The 5-hour window is a
  // rolling window (no day concept) and only gets the blunt near-cap tier.
  // Tiers are mutually exclusive, evaluated in precedence. Mirrors scoring.py.
  const pct5 = obs.rate_limit_5h_pct;
  const pct7 = obs.rate_limit_7d_pct;
  const maxRl = Math.max(pct5, pct7);
  const hoursLeft = obs.rate_limit_7d_hours_left; // null when no reset data
  let daysLeft = null, pace = null;
  if (hoursLeft != null) {
    daysLeft = hoursLeft / 24;
    const elapsedFrac = Math.max(0, Math.min(1, 1 - daysLeft / 7));
    pace = elapsedFrac * 100;
  }
  let rateLimitFired = false;

  // Tier 1 — NEAR CAP: safety net regardless of cycle position. >=90% either
  // window, OR (no reset data to reason about the cycle) the old >80% behaviour.
  if (maxRl >= 90 || (hoursLeft == null && maxRl > 80)) {
    const k = 'rate_limit_high';
    results.push({ text: `Rate limit at ${maxRl.toFixed(0)}% — close to cap. Plan break before compact.`, text_he: `ה-rate limit הגיע ל-${maxRl.toFixed(0)}% — קרוב לתקרה. תכנן הפסקה לפני /compact.`, urgency: 10, novelty: novelty(k, memory), actionability: 10, uniqueness: 10, template_key: k });
    rateLimitFired = true;
  } else if (hoursLeft != null && pct7 >= 40 && daysLeft >= 1.0 && (pct7 - pace) >= 15) {
    // Tier 2 — AHEAD OF PACE (firm, not alarmist): hot weekly usage, still >=1d
    // out, running notably hotter than the even pace line. Generalised to ANY day.
    const k = 'rate_limit_ahead_of_pace';
    results.push({ text: `Weekly cap ${pct7.toFixed(0)}% used with ~${daysLeft.toFixed(0)}d to reset — ahead of an even ${pace.toFixed(0)}% pace. Ease off or you'll cap out before reset.`, text_he: `מכסת השבוע ב-${pct7.toFixed(0)}% ונשארו ~${daysLeft.toFixed(0)} ימים לאיפוס — אתה לפני הקצב (${pace.toFixed(0)}%). תוריד הילוך, אחרת תיגמר לפני האיפוס.`, urgency: 7, novelty: novelty(k, memory), actionability: 8, uniqueness: 10, template_key: k });
    rateLimitFired = true;
  } else if (hoursLeft != null && Math.abs(pct7 - pace) < 12 && pct7 >= 20) {
    // ON-PACE (neutral, lowest urgency): tracking along the even line. Rare cue
    // (low urgency + novelty cooldown) so it never nags. Between AHEAD and BEHIND.
    const headroom = 100 - pct7;
    const k = 'rate_limit_on_pace';
    results.push({ text: `Tracking right on an even weekly pace — ~${daysLeft.toFixed(0)}d and ~${headroom.toFixed(0)}% left.`, text_he: `אתה בדיוק על הקצב השבועי האחיד — נשארו ~${daysLeft.toFixed(0)} ימים ו-~${headroom.toFixed(0)}% מהמכסה.`, urgency: 2, novelty: novelty(k, memory), actionability: 2, uniqueness: 5, template_key: k });
    rateLimitFired = true;
  } else if (hoursLeft != null && (pace - pct7) >= 12 && (100 - pct7) >= 12) {
    // BEHIND / HEADROOM (gentle, encouraging): under the even pace on ANY day.
    // Low urgency + novelty cooldown so it speaks occasionally, never nags. Two
    // phrasings: a calm general one, and a punchier last-day "use it" variant.
    const headroom = 100 - pct7;
    const k = 'rate_limit_headroom_near_reset';
    let text, textHe;
    if (daysLeft <= 1.0) {
      text = `Weekly cap resets in ~${hoursLeft.toFixed(0)}h and you're only at ${pct7.toFixed(0)}% — ~${headroom.toFixed(0)}% headroom left; put it to use before it resets.`;
      textHe = `מכסת השבוע מתאפסת בעוד ~${hoursLeft.toFixed(0)} שעות ואתה רק ב-${pct7.toFixed(0)}% — נשאר ~${headroom.toFixed(0)}% מרווח, נצל אותו עד הסוף לפני האיפוס. :)`;
    } else {
      text = `You're under an even weekly pace — ~${pace.toFixed(0)}% expected by now, you're at ${pct7.toFixed(0)}%. ~${daysLeft.toFixed(0)}d to reset, plenty of headroom.`;
      textHe = `אתה מתחת לקצב השבועי האחיד — היו אמורים ~${pace.toFixed(0)}% עד עכשיו ואתה ב-${pct7.toFixed(0)}%. נשארו ~${daysLeft.toFixed(0)} ימים לאיפוס, יש לך מרווח בנוח.`;
    }
    results.push({ text, text_he: textHe, urgency: 3, novelty: novelty(k, memory), actionability: 2, uniqueness: 5, template_key: k });
    rateLimitFired = true;
  } else if (pct5 > 85) {
    // Tier 4 — 5-HOUR ROLLING NEAR CAP: short rolling window hot, no weekly tier spoke.
    const k = 'rate_limit_5h_rolling';
    results.push({ text: `5-hour rolling window at ${pct5.toFixed(0)}% — close to the short-window cap; a short pause refills it.`, text_he: `חלון 5 השעות המתגלגל ב-${pct5.toFixed(0)}% — קרוב לתקרת החלון הקצר; הפסקה קצרה ממלאת אותו מחדש.`, urgency: 9, novelty: novelty(k, memory), actionability: 8, uniqueness: 10, template_key: k });
    rateLimitFired = true;
  }

  if (!rateLimitFired && obs.is_peak && maxRl < 80) {
    const k = 'peak_rate_ok';
    results.push({ text: `Historical peak schedule is active in your custom tier. Budget: ${maxRl.toFixed(0)}% used. Use this as a local schedule cue, not a faster-drain warning.`, text_he: `לוח שעות שיא היסטורי פעיל ב-custom tier שלך. Budget: ${maxRl.toFixed(0)}% בשימוש. תתייחס לזה כסימון לוח זמנים מקומי, לא כאזהרת צריכה מהירה יותר.`, urgency: 7, novelty: novelty(k, memory), actionability: 5, uniqueness: 5, template_key: k });
  }

  // Duration alone is a poor proxy — gate on real context fill (1M-aware).
  if (obs.session_duration_min > 120 && obs.ctx_pct > 60) {
    const dh = Math.floor(obs.session_duration_min / 60), dm = Math.floor(obs.session_duration_min % 60), k = 'long_session';
    results.push({ text: `Long session (${dh}h ${dm}m) and context ${obs.ctx_pct.toFixed(0)}% full — older context is starting to crowd out what matters now. Consider /clear for a clean restart if you've moved past the original task.`, text_he: `סשן ארוך (${dh} שעות ${dm} דקות) וה-context ב-${obs.ctx_pct.toFixed(0)}% — מצטבר יותר מדי הקשר ישן. כדאי /clear לפתיחה נקייה אם כבר עברת מהמשימה המקורית.`, urgency: 4, novelty: novelty(k, memory), actionability: 8, uniqueness: 10, template_key: k });
  }

  if (obs.ctx_pct > 70 && obs.session_duration_min > 60) {
    const k = 'ctx_high_long_session';
    results.push({ text: `Context ${obs.ctx_pct.toFixed(0)}% full + ${obs.session_duration_min.toFixed(0)} min of session — noise accumulating. Try /compact with a directive, not plain auto-compact.`, text_he: `Context ב-${obs.ctx_pct.toFixed(0)}% ו-${obs.session_duration_min.toFixed(0)} דקות של סשן — רעש מצטבר. עדיף /compact עם הנחיה במקום auto-compact.`, urgency: 6, novelty: novelty(k, memory), actionability: 10, uniqueness: 10, template_key: k });
  }

  if (obs.ctx_pct > 90) {
    const k = 'ctx_very_high';
    results.push({ text: `Context nearly full (${obs.ctx_pct.toFixed(0)}%). Enable auto-compact as a safety net so you never hit the limit mid-task — or run /compact now with 'focus on current task' to keep more control over what survives.`, text_he: `Context כמעט מלא (${obs.ctx_pct.toFixed(0)}%). הפעל auto-compact כרשת ביטחון כדי לא להיתקע באמצע משימה — או הרץ /compact עכשיו עם 'תתמקד במשימה הנוכחית' לשליטה טובה יותר על מה שנשמר.`, urgency: 9, novelty: novelty(k, memory), actionability: 10, uniqueness: 10, template_key: k });
  }

  // Prompt count alone is a poor proxy — gate on real context fill.
  if (obs.prompt_count > 30 && obs.ctx_pct > 60) {
    const k = 'many_prompts';
    results.push({ text: `${obs.prompt_count} prompts in this session. If you're shifting to a new task, a fresh session is usually faster than compacting.`, text_he: `${obs.prompt_count} פרומפטים בסשן הזה. אם אתה עובר למשימה חדשה, סשן חדש בדרך כלל מהיר יותר מcompact.`, urgency: 3, novelty: novelty(k, memory), actionability: 8, uniqueness: 8, template_key: k });
  }

  if (obs.ctx_pct > 50 && obs.prompt_count > 20) {
    const m = nextMilestone(obs.cost_usd);
    const recentMilestone = m != null && !obs.cost_milestones_hit.includes(m);
    if (!recentMilestone) {
      const k = 'pivot_suggestion';
      results.push({ text: `Deep in this session (${obs.ctx_pct.toFixed(0)}% context, ${obs.prompt_count} prompts). If this is turning into a new direction, consider rewind + fresh prompt rather than pushing forward with all the prior dead-ends in context.`, text_he: `עמוק בתוך הסשן (${obs.ctx_pct.toFixed(0)}% context, ${obs.prompt_count} פרומפטים). אם זה נהיה כיוון חדש — עדיף rewind והמשך נקי, במקום לגרור אחריך את כל הניסיונות שכבר לא רלוונטיים.`, urgency: 5, novelty: novelty(k, memory), actionability: 7, uniqueness: 9, template_key: k });
    }
  }

  if (obs.session_duration_min > 15 && obs.burn_10m != null && obs.burn_10m > 8) {
    const k = 'subagent_suggestion';
    results.push({ text: `Heavy work? Subagents keep the main session clean — spawn one for anything that generates lots of intermediate output you won't need back.`, text_he: `עבודה כבדה? Subagents שומרים את הסשן הראשי נקי — שלח סוכן נפרד לכל משימה שמייצרת הרבה פלט ביניים שלא תצטרך בחזרה.`, urgency: 2, novelty: novelty(k, memory), actionability: 6, uniqueness: 7, template_key: k });
  }

  // CLAUDE.md hygiene (Boris Cherny: ~60 optimal, 200 ceiling)
  if (obs.claude_md_lines > 200) {
    const k = 'claude_md_oversized';
    results.push({ text: `CLAUDE.md is ${obs.claude_md_lines} lines — past the ~200 ceiling, so rules near the bottom get quietly deprioritized. Trim toward ~60 lines and move the rest into .claude/rules/ with paths: scoping (Boris Cherny / Anthropic guidance).`, text_he: `CLAUDE.md הוא ${obs.claude_md_lines} שורות — מעבר לתקרת ~200, וחוקים בתחתית מודחקים בשקט. כדאי לקצר ל~60 שורות ולהעביר את השאר ל-.claude/rules/ עם paths: (לפי Boris Cherny / Anthropic).`, urgency: 2, novelty: novelty(k, memory), actionability: 7, uniqueness: 9, template_key: k });
  }

  if (obs.active_workflow_agents > 0 && obs.subagent_tokens_live > 100000) {
    const tok = obs.subagent_tokens_live >= 1000000 ? `${(obs.subagent_tokens_live / 1000000).toFixed(1)}M` : `${Math.floor(obs.subagent_tokens_live / 1000)}K`;
    const k = 'workflow_background_drain';
    results.push({ text: `Workflows running ${obs.active_workflow_agents} agents (${tok} ctx) in the background — your main context looks clean but account quota is draining. Rate-limit bars reflect this, not the cost line.`, text_he: `Workflows מריצים ${obs.active_workflow_agents} סוכנים (${tok} ctx) ברקע — ה-context הראשי נראה נקי אבל המכסה נצרכת. בר rate-limit משקף את זה, לא שורת העלות.`, urgency: 7, novelty: novelty(k, memory), actionability: 5, uniqueness: 10, template_key: k });
  }

  return results;
}

function pick(obs, memory) {
  try {
    const insights = buildInsights(obs, memory);
    insights.sort((a, b) => (b.urgency * 3 + b.novelty * 2 + b.actionability * 2 + b.uniqueness) - (a.urgency * 3 + a.novelty * 2 + a.actionability * 2 + a.uniqueness));
    return insights.slice(0, 2);
  } catch { return []; }
}

// ── Haiku ──

function callHaiku(obs, memory, rulesText) {
  const apiKey = process.env.ANTHROPIC_API_KEY || '';
  if (!apiKey) return null;

  const recent = (memory.current?.delivered_narratives || []).slice(-5).map(n => n.text || n);
  const priorSessions = (memory.prior_sessions || []).slice(0, 3).map(ps => ({
    session_id: ps.session_id || '',
    ended_at: ps.ended_at || 0,
    summary: (ps.narratives || []).length ? ps.narratives[ps.narratives.length - 1].text || '' : '',
  }));
  const payload = {
    current_state: {
      cost_usd: obs.cost_usd, burn_10m: obs.burn_10m, burn_session: obs.burn_session,
      ctx_pct: Math.round(obs.ctx_pct * 10) / 10, ctx_mins_left: obs.ctx_mins_left,
      cache_pct: Math.round(obs.cache_pct * 10) / 10, cache_delta_5m_tokens: obs.cache_delta_5m,
      session_duration_min: Math.round(obs.session_duration_min * 10) / 10,
      prompt_count: obs.prompt_count, is_peak: obs.is_peak,
      rate_limit_5h_pct: obs.rate_limit_5h_pct, rate_limit_7d_pct: obs.rate_limit_7d_pct,
    },
    recent_trends: {
      cost_delta_5m: obs.cost_delta_5m, cost_delta_20m: obs.cost_delta_20m, ctx_delta_5m: obs.ctx_delta_5m,
    },
    recent_narratives: recent,
    rules_engine_pick: rulesText,
    prior_sessions_summary: priorSessions,
  };

  return new Promise(resolve => {
    const body = JSON.stringify({
      model: 'claude-haiku-4-5-20251001',
      max_tokens: 80,
      system: "You are a brief narrator for a developer's coding session. Write 25-35 words of insight. Be specific and actionable. Do not restate numbers the user already sees.",
      messages: [{ role: 'user', content: JSON.stringify(payload, null, 2) }],
    });
    const req = https.request('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'x-api-key': apiKey, 'anthropic-version': '2023-06-01', 'User-Agent': 'claude-statusline/2.2' },
      timeout: 5000,
    }, res => {
      let data = '';
      res.on('data', c => data += c);
      res.on('end', () => {
        try { const r = JSON.parse(data); resolve(r.content?.[0]?.text?.trim() || null); }
        catch { resolve(null); }
      });
    });
    req.on('error', () => resolve(null));
    req.on('timeout', () => { req.destroy(); resolve(null); });
    req.end(body);
  });
}

// ── Engine ──

function languages() {
  const raw = process.env.STATUSLINE_NARRATOR_LANGS;
  if (raw) { const langs = raw.split(',').map(s => s.trim()).filter(s => s === 'en' || s === 'he'); return langs.length ? langs : ['en']; }
  for (const v of ['LC_ALL', 'LC_MESSAGES', 'LANG']) { if ((process.env[v] || '').toLowerCase().startsWith('he')) return ['he']; }
  return ['en'];
}

function directiveLabel(langs) {
  return langs[0] === 'he' ? 'הערת סטטוס' : 'Statusline note';
}

function frameLine(text) {
  return `//// ${text} ////`;
}

async function run(mode) {
  try {
    if ((process.env.STATUSLINE_NARRATOR_ENABLED || '1') === '0') return null;

    const data = loadMemory();
    const sessionId = process.env.CLAUDE_SESSION_ID || '';
    const curSid = data.current?.session_id || '';
    if (sessionId && curSid && sessionId !== curSid) { Object.assign(data, rotateSession(data, sessionId)); }
    else if (sessionId && !curSid) { data.current.session_id = sessionId; if (!data.current.started_at) data.current.started_at = Date.now() / 1000; }

    const now = Date.now() / 1000;
    if (mode === 'prompt_submit') {
      const throttle = Number(process.env.STATUSLINE_NARRATOR_THROTTLE_MIN || 5);
      if (data.current.last_emit_at && (now - data.current.last_emit_at) < throttle * 60) return null;
    }

    const obs = buildObservation(data);
    data.current.prompt_count = (data.current.prompt_count || 0) + 1;
    obs.prompt_count = data.current.prompt_count;
    obs.cost_milestones_hit = data.current.cost_milestones_hit || [];

    const insights = pick(obs, data);
    if (!insights.length) { saveMemory(data); return null; }

    const langs = languages();
    const rulesText = insights.map(i => i.text);
    const heParts = insights.map(i => i.text_he).filter(Boolean);

    // Haiku (async)
    let haikuText = null;
    const haikuEnv = (process.env.STATUSLINE_NARRATOR_HAIKU || '').trim();
    const shouldHaiku = haikuEnv !== '0' && (haikuEnv === '1' || process.env.ANTHROPIC_API_KEY);
    if (shouldHaiku) {
      const pc = data.current.prompt_count || 0;
      const lastH = data.current.last_haiku_at || 0;
      const interval = Number(process.env.STATUSLINE_NARRATOR_HAIKU_INTERVAL_MIN || 15);
      if (pc % 5 === 0 || (lastH && (now - lastH) > interval * 60)) {
        try { haikuText = await callHaiku(obs, data, rulesText); } catch { haikuText = null; }
      }
    }

    // Build output
    const lines = [];
    if (langs.includes('en')) lines.push(...rulesText.map(t => frameLine(`-> ${t}`)));
    if (langs.includes('he') && heParts.length) lines.push(...heParts.map(t => frameLine(`-> ${t}`)));
    if (!lines.length) lines.push(...rulesText.map(t => frameLine(`-> ${t}`)));
    if (haikuText) lines.push(frameLine(`-> ${haikuText}`));

    const directive = `${frameLine(directiveLabel(langs))}\n${lines.join('\n')}`;

    // Update memory
    data.current.last_emit_at = now;
    if (haikuText) data.current.last_haiku_at = now;
    for (const insight of insights) {
      data.current.delivered_narratives = data.current.delivered_narratives || [];
      data.current.delivered_narratives.push({ text: insight.text, template_key: insight.template_key, ts: now });
      data.current.delivered_narratives = data.current.delivered_narratives.slice(-8);
    }
    const hit = new Set(data.current.cost_milestones_hit || []);
    for (const m of COST_MILESTONES) { if (obs.cost_usd >= m) hit.add(m); }
    data.current.cost_milestones_hit = [...hit].sort((a, b) => a - b);

    // Rolling observations
    data.current.rolling_observations = data.current.rolling_observations || [];
    data.current.rolling_observations.push({ ts: now, cost_usd: obs.cost_usd, ctx_pct: obs.ctx_pct, burn_10m: obs.burn_10m });
    const cutoff = now - 7200;
    data.current.rolling_observations = data.current.rolling_observations.filter(o => o.ts >= cutoff);

    saveMemory(data);
    return directive;
  } catch { return null; }
}

module.exports = { run, buildObservation, buildInsights, pick, nextMilestone, novelty, computeTrendFields, detectIsPeak, parseResetAt };
