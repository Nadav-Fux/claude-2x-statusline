'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');

const FINISHED_STATES = new Set([
  'done',
  'finished',
  'complete',
  'completed',
  'failed',
  'error',
  'errored',
  'cancelled',
  'canceled',
  'stopped',
  'idle',
]);

const RUNNING_STATES = new Set([
  'running',
  'active',
  'busy',
  'working',
  'processing',
  'in_progress',
  'in-progress',
  'started',
  'starting',
  'pending',
  'queued',
]);

function homeDir() {
  return process.env.HOME || process.env.USERPROFILE || os.homedir();
}

function jobsRoot(home = homeDir()) {
  return path.join(home, '.claude', 'jobs');
}

function rosterFile(home = homeDir()) {
  return path.join(home, '.claude', 'daemon', 'roster.json');
}

function hasOwn(obj, key) {
  return Object.prototype.hasOwnProperty.call(obj, key);
}

function toCount(value) {
  const n = Number(value);
  return Number.isFinite(n) && n > 0 ? Math.floor(n) : 0;
}

function shortName(value) {
  const text = String(value || '').trim();
  return text && text.length <= 24 ? text : '';
}

function readRosterWorkers(rosterPath) {
  try {
    const data = JSON.parse(fs.readFileSync(rosterPath, 'utf8'));
    const workers = data && typeof data.workers === 'object' && !Array.isArray(data.workers) ? data.workers : null;
    return workers ? Object.keys(workers).length : 0;
  } catch {
    return 0;
  }
}

function isActiveJob(data, mtimeMs, nowMs, maxAgeMs) {
  if (!data || typeof data !== 'object' || Array.isArray(data)) return null;
  if (nowMs - mtimeMs > maxAgeMs) return null;

  const state = String(data.state || '').trim().toLowerCase();
  if (FINISHED_STATES.has(state)) return null;

  const tempo = String(data.tempo || '').trim().toLowerCase();
  const inFlight = data.inFlight && typeof data.inFlight === 'object' && !Array.isArray(data.inFlight)
    ? data.inFlight
    : {};
  const tasks = toCount(inFlight.tasks);
  const queued = toCount(inFlight.queued);
  const hasTempoOrInFlight = hasOwn(data, 'tempo') || hasOwn(data, 'inFlight');
  const showsLife = tempo === 'active' || tasks > 0 || queued > 0 || (!hasTempoOrInFlight && RUNNING_STATES.has(state));
  if (!showsLife) return null;

  return { tasks, name: shortName(data.name) };
}

function collectActiveJobs({
  jobsDir = jobsRoot(),
  rosterPath = rosterFile(),
  nowMs = Date.now(),
  maxAgeMs = 15 * 60 * 1000,
} = {}) {
  let activeJobs = 0;
  let inflight = 0;
  let onlyName = '';

  try {
    for (const entry of fs.readdirSync(jobsDir, { withFileTypes: true })) {
      if (!entry.isDirectory()) continue;
      const statePath = path.join(jobsDir, entry.name, 'state.json');
      try {
        const stat = fs.statSync(statePath);
        const active = isActiveJob(JSON.parse(fs.readFileSync(statePath, 'utf8')), stat.mtimeMs, nowMs, maxAgeMs);
        if (!active) continue;
        activeJobs += 1;
        inflight += active.tasks;
        onlyName = active.name;
      } catch {}
    }
  } catch {}

  const workers = readRosterWorkers(rosterPath);
  const count = activeJobs + workers;
  const name = activeJobs === 1 && workers === 0 ? onlyName : '';
  return { count, inflight, workers, name };
}

function renderJobsSummary(summary) {
  const count = toCount(summary && summary.count);
  if (count <= 0) return '';

  const inflight = toCount(summary && summary.inflight);
  const name = shortName(summary && summary.name);
  const base = name && count === 1 ? `↻ ${name}` : `↻ ${count} job${count === 1 ? '' : 's'}`;
  return inflight > 0 ? `${base} · ${inflight} inflight` : base;
}

module.exports = {
  jobsRoot,
  rosterFile,
  collectActiveJobs,
  renderJobsSummary,
};
