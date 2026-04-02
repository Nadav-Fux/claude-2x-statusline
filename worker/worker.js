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

    return new Response('Not found', { status: 404, headers: cors });
  },
};

async function handlePing(request, env, cors) {
  try {
    const body = await request.json();
    const { id, v, engine, tier, os, event } = body;

    if (!id || !/^[0-9a-f]{12,32}$/.test(id)) {
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
