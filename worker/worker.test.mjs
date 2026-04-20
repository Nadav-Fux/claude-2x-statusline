import test from 'node:test';
import assert from 'node:assert/strict';

import worker from './worker.js';

class MemoryKv {
  constructor() {
    this.store = new Map();
  }

  async get(key) {
    return this.store.has(key) ? this.store.get(key) : null;
  }

  async put(key, value) {
    this.store.set(key, value);
  }

  async list({ prefix = '' } = {}) {
    const keys = [...this.store.keys()]
      .filter(key => key.startsWith(prefix))
      .sort()
      .map(name => ({ name }));
    return { keys, list_complete: true };
  }
}

function makeEnv() {
  return {
    TELEMETRY: new MemoryKv(),
  };
}

async function readJson(response) {
  return JSON.parse(await response.text());
}

async function postPing(env, body) {
  return worker.fetch(
    new Request('https://statusline.test/ping', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
    env,
  );
}

test('GET /stats counts unique ping records for today', async () => {
  const env = makeEnv();

  await postPing(env, {
    id: 'aaaaaaaaaaaa',
    v: '2.2',
    engine: 'python',
    tier: 'full',
    os: 'windows',
    event: 'heartbeat',
  });
  await postPing(env, {
    id: 'bbbbbbbbbbbb',
    v: '2.2',
    engine: 'node',
    tier: 'standard',
    os: 'linux',
    event: 'heartbeat',
  });

  const response = await worker.fetch(new Request('https://statusline.test/stats'), env);
  const data = await readJson(response);

  assert.equal(response.status, 200);
  assert.equal(data.dau_today, 2);
  assert.equal(data.pings_today, 2);
  assert.deepEqual(data.engines_today, { node: 1, python: 1 });
});

test('GET /failures stays open when auth token is not configured', async () => {
  const env = makeEnv();

  const response = await worker.fetch(new Request('https://statusline.test/failures'), env);
  const data = await readJson(response);

  assert.equal(response.status, 200);
  assert.equal(data.total_installs, 0);
  assert.equal(data.total_updates, 0);
  assert.equal(data.total_attempts, 0);
  assert.equal(data.total_failures, 0);
  assert.equal(data.failure_rate, 0);
  assert.equal(data.doctor_reports, 0);
  assert.deepEqual(data.top_failed_checks, []);
  assert.deepEqual(data.by_os, {});
  assert.equal(data.days, 7);
  assert.match(data.as_of, /^\d{4}-\d{2}-\d{2}T/);
});

test('GET /failures rejects unauthorized requests when auth token exists', async () => {
  const env = makeEnv();
  await env.TELEMETRY.put('_auth_token', 'secret-token');

  const response = await worker.fetch(new Request('https://statusline.test/failures'), env);

  assert.equal(response.status, 401);
  assert.equal(await response.text(), 'Unauthorized');
});

test('GET /failures aggregates install, update, doctor and fail-index rollups', async () => {
  const env = makeEnv();
  await env.TELEMETRY.put('_auth_token', 'secret-token');

  const basePayload = {
    v: '2.2',
    engine: 'installer',
    tier: 'full',
  };

  await postPing(env, {
    ...basePayload,
    id: 'aaaaaaaaaaaa',
    event: 'install_result',
    os: 'windows',
    ok: 4,
    warn: 1,
    fail: 2,
    failed_ids: 'python_missing hook_invalid hook_invalid',
  });
  await postPing(env, {
    ...basePayload,
    id: 'bbbbbbbbbbbb',
    event: 'install_result',
    os: 'macos',
    ok: 5,
    warn: 0,
    fail: 0,
    failed_ids: '',
  });
  await postPing(env, {
    ...basePayload,
    id: 'cccccccccccc',
    event: 'update',
    os: 'windows',
    ok: 6,
    warn: 0,
    fail: 1,
    failed_ids: ['hook_invalid', 'hook_invalid', 'schedule_missing'],
  });
  await postPing(env, {
    ...basePayload,
    id: 'dddddddddddd',
    event: 'doctor',
    os: 'linux',
    ok: 3,
    warn: 0,
    fail: 2,
    failed_ids: ['doctor_unavailable', 'hook_invalid'],
  });

  const yesterday = new Date(Date.now() - 86400000).toISOString().slice(0, 10);
  await env.TELEMETRY.put(
    `event:update:${yesterday}:eeeeeeeeeeee:1`,
    JSON.stringify({
      ...basePayload,
      id: 'eeeeeeeeeeee',
      event: 'update',
      os: 'windows',
      ok: 2,
      warn: 0,
      fail: 1,
      failed_ids: ['python_missing'],
    }),
  );
  await env.TELEMETRY.put(
    `fail_index:${yesterday}`,
    JSON.stringify({ python_missing: 2, legacy_hook: 1 }),
  );

  const response = await worker.fetch(
    new Request('https://statusline.test/failures?days=2', {
      headers: { Authorization: 'Bearer secret-token' },
    }),
    env,
  );
  const data = await readJson(response);

  assert.equal(response.status, 200);
  assert.equal(data.total_installs, 2);
  assert.equal(data.total_updates, 2);
  assert.equal(data.total_attempts, 4);
  assert.equal(data.total_failures, 3);
  assert.equal(data.failure_rate, 0.75);
  assert.equal(data.doctor_reports, 1);
  assert.deepEqual(data.by_os, {
    windows: { attempts: 3, failures: 3 },
    macos: { attempts: 1, failures: 0 },
    linux: { attempts: 1, failures: 1 },
  });

  const topChecks = Object.fromEntries(data.top_failed_checks.map(entry => [entry.id, entry.count]));
  assert.equal(topChecks.hook_invalid, 3);
  assert.equal(topChecks.python_missing, 4);
  assert.equal(topChecks.schedule_missing, 1);
  assert.equal(topChecks.doctor_unavailable, 1);
  assert.equal(topChecks.legacy_hook, 1);
});