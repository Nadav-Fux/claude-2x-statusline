import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const gateway = require(path.join(repoRoot, 'lib', 'gateway.js'));
const sessions = require(path.join(repoRoot, 'lib', 'session_cockpit.js'));

test('gateway host mapping and predicate', () => {
  assert.equal(gateway.providerLabelForHost('api.z.ai'), 'GLM');
  assert.equal(gateway.providerLabelForHost('bigmodel.cn'), 'GLM');
  assert.equal(gateway.providerLabelForHost('openrouter.ai'), 'OpenRouter');
  assert.equal(gateway.providerLabelForHost('api.moonshot.cn'), 'Kimi');
  assert.equal(gateway.providerLabelForHost('api.deepseek.com'), 'DeepSeek');
  assert.equal(gateway.providerLabelForHost('my-proxy.example.com'), 'my-proxy.example.com');

  assert.equal(gateway.isForeignGateway(undefined), false);
  assert.equal(gateway.isForeignGateway('https://api.anthropic.com'), false);
  assert.equal(gateway.isForeignGateway('https://api.z.ai/api/anthropic'), true);
});

test('gateway info uses settings env and escape hatch', () => {
  const info = gateway.gatewayInfo({
    env: {},
    settings: { env: { ANTHROPIC_BASE_URL: 'https://api.z.ai/api/anthropic' } },
    config: {},
  });

  assert.equal(info.foreign, true);
  assert.equal(info.label, 'GLM');
  assert.equal(info.displayHost, 'z.ai');
  assert.equal(gateway.gatewayBadgeText(info), 'via z.ai (GLM)');
  assert.equal(gateway.gatewayNoteLabel(info), 'GLM');

  const disabled = gateway.gatewayInfo({
    env: { ANTHROPIC_BASE_URL: 'https://api.z.ai/api/anthropic' },
    config: { gateway_awareness: false },
  });
  assert.equal(disabled.foreign, false);
});

function writeSession(filePath, status, updatedAt) {
  fs.writeFileSync(
    filePath,
    JSON.stringify({ sessionId: path.basename(filePath, '.json'), cwd: '/tmp/project', status, updatedAt }),
    'utf8',
  );
}

test('session counts include live busy and ignore stale', () => {
  const home = fs.mkdtempSync(path.join(os.tmpdir(), 'statusline-sessions-'));
  try {
    const dir = path.join(home, '.claude', 'sessions');
    fs.mkdirSync(dir, { recursive: true });
    const nowMs = 1_800_000_000_000;

    writeSession(path.join(dir, 'busy-1.json'), 'busy', nowMs);
    writeSession(path.join(dir, 'busy-2.json'), 'busy', nowMs - 5 * 60 * 1000);
    writeSession(path.join(dir, 'idle.json'), 'idle', nowMs - 14 * 60 * 1000);
    writeSession(path.join(dir, 'stale.json'), 'busy', nowMs - 16 * 60 * 1000);

    const counts = sessions.collectSessionCounts({ sessionsDir: dir, nowMs });

    assert.deepEqual(counts, { live: 3, busy: 2, error: false });
    assert.equal(sessions.renderSessionSummary(counts), '◉ 3 sess · 2 busy');
  } finally {
    fs.rmSync(home, { recursive: true, force: true });
  }
});

test('session summary hides single live session', () => {
  assert.equal(sessions.renderSessionSummary({ live: 1, busy: 1 }), '');
  assert.equal(sessions.renderSessionSummary({ live: 0, busy: 0 }), '');
});
