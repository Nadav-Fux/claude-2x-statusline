import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const jobMonitor = require(path.join(repoRoot, 'lib', 'job_monitor.js'));

function withHome(fn) {
  const home = fs.mkdtempSync(path.join(os.tmpdir(), 'statusline-jobs-'));
  const oldHome = process.env.HOME;
  const oldUserProfile = process.env.USERPROFILE;
  process.env.HOME = home;
  process.env.USERPROFILE = home;
  try {
    return fn(home);
  } finally {
    if (oldHome === undefined) delete process.env.HOME;
    else process.env.HOME = oldHome;
    if (oldUserProfile === undefined) delete process.env.USERPROFILE;
    else process.env.USERPROFILE = oldUserProfile;
    fs.rmSync(home, { recursive: true, force: true });
  }
}

function writeJob(home, jobId, payload, ageSeconds = 0) {
  const statePath = path.join(home, '.claude', 'jobs', jobId, 'state.json');
  fs.mkdirSync(path.dirname(statePath), { recursive: true });
  fs.writeFileSync(statePath, JSON.stringify(payload), 'utf8');
  const ts = new Date(Date.now() - ageSeconds * 1000);
  fs.utimesSync(statePath, ts, ts);
}

test('collectActiveJobs ignores finished and stale jobs', () => withHome(home => {
  writeJob(home, 'finished', { state: 'done', tempo: 'idle', inFlight: { tasks: 0 } });
  writeJob(home, 'running', { state: 'running', tempo: 'active', inFlight: { tasks: 3 } });
  writeJob(home, 'stale', { state: 'running', tempo: 'active', inFlight: { tasks: 5 } }, 30 * 60);

  const summary = jobMonitor.collectActiveJobs();

  assert.deepEqual(summary, { count: 1, inflight: 3, workers: 0, name: '' });
  assert.equal(jobMonitor.renderJobsSummary(summary), '↻ 1 job · 3 inflight');
}));

test('renderJobsSummary hides when nothing is active', () => withHome(home => {
  writeJob(home, 'finished', { state: 'done', tempo: 'idle', inFlight: { tasks: 0 } });

  assert.deepEqual(jobMonitor.collectActiveJobs(), { count: 0, inflight: 0, workers: 0, name: '' });
  assert.equal(jobMonitor.renderJobsSummary(jobMonitor.collectActiveJobs()), '');
}));
