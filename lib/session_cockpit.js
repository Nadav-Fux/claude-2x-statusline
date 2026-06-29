const fs = require('fs');
const os = require('os');
const path = require('path');

function homeDir() {
  return process.env.HOME || process.env.USERPROFILE || os.homedir();
}

function sessionRegistryDir(home = homeDir()) {
  return path.join(home, '.claude', 'sessions');
}

function parseUpdatedAt(value) {
  if (value == null || value === '') return null;
  if (typeof value === 'number' || /^[0-9]+(\.[0-9]+)?$/.test(String(value))) {
    const n = Number(value);
    if (!Number.isFinite(n) || n <= 0) return null;
    return n > 1e11 ? n : n * 1000;
  }
  const ms = Date.parse(String(value));
  return Number.isFinite(ms) ? ms : null;
}

function collectSessionCounts({ sessionsDir = sessionRegistryDir(), nowMs = Date.now(), maxAgeMs = 15 * 60 * 1000 } = {}) {
  let live = 0, busy = 0;
  try {
    for (const name of fs.readdirSync(sessionsDir)) {
      if (!name.endsWith('.json')) continue;
      try {
        const data = JSON.parse(fs.readFileSync(path.join(sessionsDir, name), 'utf8'));
        const updatedMs = parseUpdatedAt(data.updatedAt);
        if (updatedMs == null || nowMs - updatedMs > maxAgeMs) continue;
        live += 1;
        if (String(data.status || '').toLowerCase() === 'busy') busy += 1;
      } catch {}
    }
  } catch {
    return { live: 0, busy: 0, error: true };
  }
  return { live, busy, error: false };
}

function renderSessionSummary(counts) {
  const live = Number(counts && counts.live) || 0;
  if (live <= 1) return '';
  const busy = Number(counts && counts.busy) || 0;
  return `◉ ${live} sess · ${busy} busy`;
}

module.exports = {
  sessionRegistryDir,
  parseUpdatedAt,
  collectSessionCounts,
  renderSessionSummary,
};
