export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const cors = {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type, Authorization',
    };

    if (request.method === 'OPTIONS') {
      return new Response(null, { headers: cors });
    }

    if (url.pathname === '/ping' && request.method === 'POST') {
      return handlePing(request, env, cors);
    }

    if (url.pathname === '/stats' && request.method === 'GET') {
      return handleStats(request, env, cors);
    }

    if (url.pathname === '/failures' && request.method === 'GET') {
      return handleFailures(request, env, cors);
    }

    if (url.pathname === '/doctor/submit' && request.method === 'POST') {
      return handleDoctorSubmit(request, env, cors);
    }

    // GET /doctor/<code>/latest
    const latestMatch = url.pathname.match(/^\/doctor\/([0-9a-f]{6,16})\/latest$/);
    if (latestMatch && request.method === 'GET') {
      return handleDoctorLatest(request, env, cors, latestMatch[1]);
    }

    // GET /doctor/<code>
    const doctorMatch = url.pathname.match(/^\/doctor\/([0-9a-f]{6,16})$/);
    if (doctorMatch && request.method === 'GET') {
      return handleDoctorGet(request, env, cors, doctorMatch[1]);
    }

    return new Response('Not found', { status: 404, headers: cors });
  },
};

async function handlePing(request, env, cors) {
  try {
    const body = await request.json();
    const { id, v, engine, tier, os, event } = body;
    const failedIds = normalizeFailedIds(body.failed_ids);

    if (!id || !/^[0-9a-f]{8,32}$/.test(id)) {
      return new Response('Bad id', { status: 400, headers: cors });
    }

    const today = new Date().toISOString().slice(0, 10);
    const value = [engine, tier, os, v].join(':');

    // DAU — one key per user per day, 90-day TTL
    await env.TELEMETRY.put(`dau:${today}:${id}`, value, { expirationTtl: 7776000 });

    // Install — first-seen only
    if (event === 'install') {
      const existing = await env.TELEMETRY.get(`install:${id}`);
      if (!existing) {
        await env.TELEMETRY.put(`install:${id}`, `${today}:${value}`);
      }
    }

    if (event === 'doctor' || event === 'install_result' || event === 'update') {
      const eventRecord = {
        id,
        event,
        v,
        engine,
        tier,
        os,
        ok: toInt(body.ok),
        warn: toInt(body.warn),
        fail: toInt(body.fail),
        failed_ids: failedIds,
        ps1_only: Boolean(body.ps1_only),
        has_python: toNullableBool(body.has_python),
        has_node: toNullableBool(body.has_node),
        timestamp: new Date().toISOString(),
      };
      const eventKey = `event:${event}:${today}:${id}:${Date.now()}`;
      await env.TELEMETRY.put(eventKey, JSON.stringify(eventRecord), { expirationTtl: 7776000 });
    }

    // Total ping counter (simple increment via read-modify-write)
    const countKey = `count:${today}`;
    const current = parseInt(await env.TELEMETRY.get(countKey) || '0');
    await env.TELEMETRY.put(countKey, String(current + 1), { expirationTtl: 7776000 });

    return new Response('ok', { status: 202, headers: cors });
  } catch {
    return new Response('Bad request', { status: 400, headers: cors });
  }
}

async function handleStats(request, env, cors) {
  // Simple auth via query param or header
  const url = new URL(request.url);
  const token = url.searchParams.get('token') || request.headers.get('Authorization')?.replace('Bearer ', '');
  const expectedToken = await env.TELEMETRY.get('_auth_token');
  if (expectedToken && token !== expectedToken) {
    return new Response('Unauthorized', { status: 401, headers: cors });
  }

  const today = new Date().toISOString().slice(0, 10);
  const yesterday = new Date(Date.now() - 86400000).toISOString().slice(0, 10);

  // Count DAU today
  const dauToday = await listAllKeys(env.TELEMETRY, `dau:${today}:`);
  const dauYesterday = await listAllKeys(env.TELEMETRY, `dau:${yesterday}:`);

  // Count total installs
  const installs = await listAllKeys(env.TELEMETRY, 'install:');

  // 7-day active users (union of IDs across 7 days)
  const sevenDayIds = new Set();
  for (let i = 0; i < 7; i++) {
    const date = new Date(Date.now() - i * 86400000).toISOString().slice(0, 10);
    const keys = await listAllKeys(env.TELEMETRY, `dau:${date}:`);
    keys.forEach(k => sevenDayIds.add(k.name.split(':').pop()));
  }

  // Engine breakdown from today's DAU
  const engines = {};
  for (const key of dauToday) {
    const val = await env.TELEMETRY.get(key.name);
    if (val) {
      const engine = val.split(':')[0];
      engines[engine] = (engines[engine] || 0) + 1;
    }
  }

  const stats = {
    dau_today: dauToday.length,
    dau_yesterday: dauYesterday.length,
    wau_7day: sevenDayIds.size,
    total_installs: installs.length,
    engines_today: engines,
    pings_today: parseInt(await env.TELEMETRY.get(`count:${today}`) || '0'),
    as_of: new Date().toISOString(),
  };

  return new Response(JSON.stringify(stats, null, 2), {
    headers: { ...cors, 'Content-Type': 'application/json' },
  });
}

async function listAllKeys(kv, prefix) {
  const allKeys = [];
  let cursor = undefined;
  do {
    const result = await kv.list({ prefix, cursor });
    allKeys.push(...result.keys);
    cursor = result.list_complete ? undefined : result.cursor;
  } while (cursor);
  return allKeys;
}

async function checkAuth(request, env) {
  const url = new URL(request.url);
  const token = url.searchParams.get('token') || request.headers.get('Authorization')?.replace('Bearer ', '');
  const expectedToken = await env.TELEMETRY.get('_auth_token');
  // If no token is configured, deny by default (safe)
  if (!expectedToken || token !== expectedToken) {
    return false;
  }
  return true;
}

async function checkOptionalAuth(request, env) {
  const url = new URL(request.url);
  const token = url.searchParams.get('token') || request.headers.get('Authorization')?.replace('Bearer ', '');
  const expectedToken = await env.TELEMETRY.get('_auth_token');
  return !expectedToken || token === expectedToken;
}

async function handleFailures(request, env, cors) {
  if (!await checkOptionalAuth(request, env)) {
    return new Response('Unauthorized', { status: 401, headers: cors });
  }

  const url = new URL(request.url);
  const days = clampInt(url.searchParams.get('days'), 7, 1, 30);
  const aggregateFailIndex = {};
  const byOs = {};
  let totalInstalls = 0;
  let totalUpdates = 0;
  let totalFailures = 0;
  let doctorReports = 0;

  for (let i = 0; i < days; i++) {
    const date = new Date(Date.now() - i * 86400000).toISOString().slice(0, 10);
    totalInstalls += await accumulateEventStats(env.TELEMETRY, `event:install_result:${date}:`, byOs, aggregateFailIndex, stats => {
      if (stats.fail > 0) {
        totalFailures += 1;
      }
    });
    totalUpdates += await accumulateEventStats(env.TELEMETRY, `event:update:${date}:`, byOs, aggregateFailIndex, stats => {
      if (stats.fail > 0) {
        totalFailures += 1;
      }
    });
    doctorReports += await accumulateEventStats(env.TELEMETRY, `event:doctor:${date}:`, byOs, aggregateFailIndex, () => {});

    const failIndex = await env.TELEMETRY.get(`fail_index:${date}`);
    if (failIndex) {
      const parsed = safeJsonParse(failIndex, {});
      for (const [id, count] of Object.entries(parsed)) {
        aggregateFailIndex[id] = (aggregateFailIndex[id] || 0) + toInt(count);
      }
    }
  }

  const totalAttempts = totalInstalls + totalUpdates;
  const topFailedChecks = Object.entries(aggregateFailIndex)
    .map(([id, count]) => ({ id, count }))
    .sort((left, right) => right.count - left.count)
    .slice(0, 10);

  const failures = {
    total_installs: totalInstalls,
    total_updates: totalUpdates,
    total_attempts: totalAttempts,
    total_failures: totalFailures,
    failure_rate: totalAttempts > 0 ? Number((totalFailures / totalAttempts).toFixed(4)) : 0,
    doctor_reports: doctorReports,
    top_failed_checks: topFailedChecks,
    by_os: byOs,
    days,
    as_of: new Date().toISOString(),
  };

  return new Response(JSON.stringify(failures, null, 2), {
    headers: { ...cors, 'Content-Type': 'application/json' },
  });
}

async function accumulateEventStats(kv, prefix, byOs, aggregateFailIndex, onRecord) {
  const keys = await listAllKeys(kv, prefix);
  for (const key of keys) {
    const raw = await kv.get(key.name);
    const record = safeJsonParse(raw, null);
    if (!record) {
      continue;
    }
    const os = record.os || 'unknown';
    if (!byOs[os]) {
      byOs[os] = { attempts: 0, failures: 0 };
    }
    byOs[os].attempts += 1;
    if (toInt(record.fail) > 0) {
      byOs[os].failures += 1;
    }
    incrementFailureCounts(aggregateFailIndex, record.failed_ids);
    onRecord({ fail: toInt(record.fail) });
  }
  return keys.length;
}

function incrementFailureCounts(target, failedIds) {
  for (const failedId of normalizeFailedIds(failedIds)) {
    target[failedId] = (target[failedId] || 0) + 1;
  }
}

function normalizeFailedIds(value) {
  if (!value) {
    return [];
  }
  if (Array.isArray(value)) {
    return [...new Set(value.map(entry => String(entry).trim()).filter(Boolean))];
  }
  return [...new Set(String(value).split(/[\s,]+/).map(entry => entry.trim()).filter(Boolean))];
}

function safeJsonParse(value, fallback) {
  if (!value) {
    return fallback;
  }
  try {
    return JSON.parse(value);
  } catch {
    return fallback;
  }
}

function toInt(value) {
  const parsed = parseInt(value, 10);
  return Number.isNaN(parsed) ? 0 : parsed;
}

function toNullableBool(value) {
  if (value === null || value === undefined || value === '') {
    return null;
  }
  return Boolean(value);
}

function clampInt(value, fallback, min, max) {
  const parsed = parseInt(value, 10);
  if (Number.isNaN(parsed)) {
    return fallback;
  }
  return Math.min(Math.max(parsed, min), max);
}

async function handleDoctorSubmit(request, env, cors) {
  try {
    const body = await request.json();
    const { code, v, os, report, checks, meta } = body;

    // Validate code
    if (!code || !/^[0-9a-f]{6,16}$/.test(code)) {
      return new Response(JSON.stringify({ error: 'Invalid code' }), {
        status: 400,
        headers: { ...cors, 'Content-Type': 'application/json' },
      });
    }

    // Validate report
    if (!report || typeof report !== 'string' || report.trim().length === 0) {
      return new Response(JSON.stringify({ error: 'report is required' }), {
        status: 400,
        headers: { ...cors, 'Content-Type': 'application/json' },
      });
    }
    if (new TextEncoder().encode(report).length > 50 * 1024) {
      return new Response(JSON.stringify({ error: 'report too large' }), {
        status: 413,
        headers: { ...cors, 'Content-Type': 'application/json' },
      });
    }

    const timestamp = Date.now();
    const key = `doctor:${code}:${timestamp}`;
    const payload = { code, v, os, report, checks, meta, submitted_at: new Date(timestamp).toISOString() };

    await env.TELEMETRY.put(key, JSON.stringify(payload), { expirationTtl: 2592000 });

    return new Response(JSON.stringify({ code, ok: true }), {
      status: 202,
      headers: { ...cors, 'Content-Type': 'application/json' },
    });
  } catch {
    return new Response(JSON.stringify({ error: 'Bad request' }), {
      status: 400,
      headers: { ...cors, 'Content-Type': 'application/json' },
    });
  }
}

async function handleDoctorGet(request, env, cors, code) {
  if (!await checkAuth(request, env)) {
    return new Response('Unauthorized', { status: 401, headers: cors });
  }

  const keys = await listAllKeys(env.TELEMETRY, `doctor:${code}:`);

  // Sort by timestamp descending (timestamp is the numeric suffix of the key)
  keys.sort((a, b) => {
    const tsA = parseInt(a.name.split(':')[2]) || 0;
    const tsB = parseInt(b.name.split(':')[2]) || 0;
    return tsB - tsA;
  });

  const recent = keys.slice(0, 20);
  const reports = [];
  for (const key of recent) {
    const raw = await env.TELEMETRY.get(key.name);
    if (raw) {
      try {
        reports.push(JSON.parse(raw));
      } catch {
        // skip malformed entries
      }
    }
  }

  return new Response(JSON.stringify({ code, reports, count: reports.length }, null, 2), {
    headers: { ...cors, 'Content-Type': 'application/json' },
  });
}

async function handleDoctorLatest(request, env, cors, code) {
  if (!await checkAuth(request, env)) {
    return new Response('Unauthorized', { status: 401, headers: cors });
  }

  const keys = await listAllKeys(env.TELEMETRY, `doctor:${code}:`);

  if (keys.length === 0) {
    return new Response('', {
      status: 200,
      headers: { ...cors, 'Content-Type': 'text/plain' },
    });
  }

  // Find the most recent key by timestamp
  keys.sort((a, b) => {
    const tsA = parseInt(a.name.split(':')[2]) || 0;
    const tsB = parseInt(b.name.split(':')[2]) || 0;
    return tsB - tsA;
  });

  const raw = await env.TELEMETRY.get(keys[0].name);
  if (!raw) {
    return new Response('', {
      status: 200,
      headers: { ...cors, 'Content-Type': 'text/plain' },
    });
  }

  let reportText = '';
  try {
    const payload = JSON.parse(raw);
    reportText = payload.report || '';
  } catch {
    reportText = '';
  }

  return new Response(reportText, {
    status: 200,
    headers: { ...cors, 'Content-Type': 'text/plain; charset=utf-8' },
  });
}
