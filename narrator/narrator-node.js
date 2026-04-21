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
    fs.mkdirSync(CLAUDE_DIR, { recursive: true });
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

function buildObservation(memory) {
  const obs = {
    cost_usd: 0, burn_10m: null, burn_session: null,
    ctx_pct: 0, ctx_mins_left: null,
    cache_pct: 0, cache_delta_5m: null,
    is_peak: false, schedule_mode: 'normal',
    session_duration_min: 0, prompt_count: 0,
    rate_limit_5h_pct: 0, rate_limit_7d_pct: 0,
    cost_delta_5m: 0, cost_delta_20m: 0, ctx_delta_5m: 0,
    total_input_tokens: 0, total_output_tokens: 0,
    cache_read_tokens: 0, cache_creation_tokens: 0,
    ctx_window_size: 200000, cost_milestones_hit: [],
  };

  // Stdin (piped from hook)
  let stdinData = null;
  try { const raw = fs.readFileSync(0, 'utf8').trim(); if (raw) stdinData = JSON.parse(raw); } catch {}

  if (stdinData) {
    const c = stdinData.cost || {};
    obs.cost_usd = Number(c.total_cost_usd || 0);
    if (c.total_duration_ms) obs.session_duration_min = c.total_duration_ms / 60000;
    const cw = stdinData.context_window || {};
    obs.ctx_window_size = Number(cw.context_window_size || 200000);
    const u = cw.current_usage || {};
    obs.total_input_tokens = Number(u.input_tokens || 0);
    obs.total_output_tokens = Number(u.output_tokens || 0);
    obs.cache_read_tokens = Number(u.cache_read_input_tokens || 0);
    obs.cache_creation_tokens = Number(u.cache_creation_input_tokens || 0);
  }

  // Rolling state
  try {
    obs.burn_10m = rs.rollingRate(10);
    obs.cache_delta_5m = rs.cacheDelta(5);
  } catch {}

  // Session burn
  if (obs.session_duration_min >= 1 && obs.cost_usd > 0) {
    const candidate = obs.cost_usd / (obs.session_duration_min / 60);
    if (candidate <= 200) obs.burn_session = candidate;
  }

  // Context %
  if (obs.ctx_window_size > 0 && obs.total_input_tokens > 0) {
    const used = obs.total_input_tokens + obs.total_output_tokens;
    obs.ctx_pct = Math.min(100, used / obs.ctx_window_size * 100);
    if (obs.session_duration_min > 1 && obs.ctx_pct > 0) {
      const rate = obs.ctx_pct / obs.session_duration_min;
      if (rate > 0) obs.ctx_mins_left = (100 - obs.ctx_pct) / rate;
    }
  }

  // Cache %
  if (obs.total_input_tokens > 0 && obs.cache_read_tokens > 0) {
    obs.cache_pct = obs.cache_read_tokens / obs.total_input_tokens * 100;
  }

  // Memory-derived fields
  const cur = memory.current || {};
  if (cur.started_at) obs.session_duration_min = Math.max(obs.session_duration_min, (Date.now() / 1000 - cur.started_at) / 60);
  obs.prompt_count = cur.prompt_count || 0;
  obs.cost_milestones_hit = cur.cost_milestones_hit || [];

  return obs;
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
    const rate = obs.burn_10m ?? obs.burn_session;
    if (rate == null && obs.session_duration_min >= 1 && obs.cost_usd > 0) { const raw = obs.cost_usd / (obs.session_duration_min / 60); if (raw <= 200) rate = raw; }
    if (rate != null && rate > 0) {
      const projected = rate * 5, k = `milestone_${milestone}`;
      results.push({ text: `You've crossed $${milestone} — at current rate, extrapolates to ~$${projected.toFixed(0)} by 5h mark. Worth it?`, text_he: `חצית את ה-$${milestone} — בקצב הנוכחי זה מתורגם ל-~$${projected.toFixed(0)} עד סוף 5 שעות. שווה את זה?`, urgency: 7, novelty: novelty(k, memory), actionability: 5, uniqueness: 10, template_key: k });
    }
  }

  const maxRl = Math.max(obs.rate_limit_5h_pct, obs.rate_limit_7d_pct);
  if (maxRl > 80) {
    const k = 'rate_limit_high';
    results.push({ text: `Rate limit at ${maxRl.toFixed(0)}% — close to cap. Plan break before compact.`, text_he: `ה-rate limit הגיע ל-${maxRl.toFixed(0)}% — קרוב לתקרה. תכנן הפסקה לפני /compact.`, urgency: 10, novelty: novelty(k, memory), actionability: 10, uniqueness: 10, template_key: k });
  } else if (obs.is_peak && maxRl < 80) {
    const k = 'peak_rate_ok';
    results.push({ text: `Peak hours — rate limits drain faster. Budget: ${maxRl.toFixed(0)}% used. Keep this pass focused; save broad exploration for off-peak.`, text_he: `שעות שיא — ה-rate limits נצרכים מהר יותר. Budget: ${maxRl.toFixed(0)}% בשימוש. עדיף לשמור את הסבב הזה ממוקד, ואת החקירה הרחבה לדחות ל-off-peak.`, urgency: 7, novelty: novelty(k, memory), actionability: 5, uniqueness: 5, template_key: k });
  } else if (!obs.is_peak && maxRl < 50) {
    const k = 'off_peak_wide_open';
    results.push({ text: `Off-peak with wide-open limits — good moment for heavy refactors, broad repo scans, or subagents that generate lots of output.`, text_he: 'מחוץ לשעות השיא עם מכסות פתוחות — רגע טוב לרפקטורים כבדים, סריקות רחבות בריפו, או subagents שמייצרים הרבה פלט.', urgency: 4, novelty: novelty(k, memory), actionability: 7, uniqueness: 10, template_key: k });
  }

  if (obs.session_duration_min > 120) {
    const dh = Math.floor(obs.session_duration_min / 60), dm = Math.floor(obs.session_duration_min % 60), k = 'long_session';
    results.push({ text: `Long session (${dh}h ${dm}m) — older context is starting to crowd out what matters now. Consider /clear for a clean restart if you've moved past the original task.`, text_he: `סשן ארוך (${dh} שעות ${dm} דקות) — מצטבר יותר מדי הקשר ישן. כדאי /clear לפתיחה נקייה אם כבר עברת מהמשימה המקורית.`, urgency: 4, novelty: novelty(k, memory), actionability: 8, uniqueness: 10, template_key: k });
  }

  if (obs.ctx_pct > 70 && obs.session_duration_min > 60) {
    const k = 'ctx_high_long_session';
    results.push({ text: `Context ${obs.ctx_pct.toFixed(0)}% full + ${obs.session_duration_min.toFixed(0)} min of session — noise accumulating. Try /compact with a directive, not plain auto-compact.`, text_he: `Context ב-${obs.ctx_pct.toFixed(0)}% ו-${obs.session_duration_min.toFixed(0)} דקות של סשן — רעש מצטבר. עדיף /compact עם הנחיה במקום auto-compact.`, urgency: 6, novelty: novelty(k, memory), actionability: 10, uniqueness: 10, template_key: k });
  }

  if (obs.ctx_pct > 90) {
    const k = 'ctx_very_high';
    results.push({ text: `Context nearly full (${obs.ctx_pct.toFixed(0)}%). Auto-compact will probably drop what's currently relevant. Manual /compact with 'focus on current task' is safer.`, text_he: `Context כמעט מלא (${obs.ctx_pct.toFixed(0)}%). Auto-compact יכול לאבד את מה שחשוב עכשיו. עדיף /compact ידני עם 'תתמקד במשימה הנוכחית'.`, urgency: 9, novelty: novelty(k, memory), actionability: 10, uniqueness: 10, template_key: k });
  }

  if (obs.prompt_count > 30) {
    const k = 'many_prompts';
    results.push({ text: `${obs.prompt_count} prompts in this session. If you're shifting to a new task, a fresh session is usually faster than compacting.`, text_he: `${obs.prompt_count} פרומפטים בסשן הזה. אם אתה עובר למשימה חדשה, סשן חדש בדרך כלל מהיר יותר מcompact.`, urgency: 3, novelty: novelty(k, memory), actionability: 8, uniqueness: 8, template_key: k });
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
  const payload = {
    current_state: { cost_usd: obs.cost_usd, burn_10m: obs.burn_10m, burn_session: obs.burn_session, ctx_pct: Math.round(obs.ctx_pct), ctx_mins_left: obs.ctx_mins_left, cache_pct: Math.round(obs.cache_pct), session_duration_min: Math.round(obs.session_duration_min), prompt_count: obs.prompt_count, is_peak: obs.is_peak },
    recent_narratives: recent,
    rules_engine_pick: rulesText,
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

module.exports = { run };
