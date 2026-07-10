import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';
import * as https from 'https';
import * as os from 'os';
import { execFileSync } from 'child_process';

// ── Types ──

interface PeakConfig {
  enabled: boolean;
  tz: string;
  days: number[];
  start: number;
  end: number;
  label_peak: string;
  label_offpeak: string;
}

interface Schedule {
  v: number;
  mode: string;
  default_tier?: string;
  peak: PeakConfig;
  banner?: { text: string; expires: string; color: string };
  features?: { show_peak_segment?: boolean; show_rate_limits?: boolean };
}

interface StatuslineConfig {
  tier: string;
  mode?: string;
  segments?: Record<string, boolean>;
  schedule_url?: string;
  schedule_cache_hours?: number;
  providers?: { selected?: unknown };
  external_providers?: Record<string, unknown>;
}

interface UsageData {
  five_hour?: { utilization: number; reset_at?: string; resets_at?: string };
  seven_day?: { utilization: number; reset_at?: string; resets_at?: string };
}

interface ContextData {
  ts?: number;
  current_usage?: number;
  context_window_size?: number;
  pct?: number;
  model?: string;
  updated_at?: string;
  active_workflow_agents?: number;
  subagent_tokens_live?: number;
  subagent_runs_session?: number;
  five_hour_pct?: number;
  seven_day_pct?: number;
}

type ExternalProvider = 'codex' | 'glm' | 'droid' | 'antigravity' | 'copilot';

interface ExternalUsageWindow {
  label?: string;
  used_pct?: number;
  resets_at?: number | string | null;
}

interface ExternalUsageRecord {
  provider?: string;
  label?: string;
  available?: boolean;
  display?: 'bars' | 'compact' | string;
  plan?: string | null;
  level?: string | null;
  source?: string | null;
  stale_seconds?: number | null;
  five_hour?: ExternalUsageWindow | null;
  weekly?: ExternalUsageWindow | null;
  metrics?: ExternalUsageWindow[] | null;
  metrics_5h?: ExternalUsageWindow[] | null;
  metrics_weekly?: ExternalUsageWindow[] | null;
  all_plans?: ExternalUsageRecord[] | null;
  tokens?: Record<string, number> | null;
}

interface ExternalUsageCache {
  cached_at?: number | string;
  record?: ExternalUsageRecord;
  response?: unknown;
}

interface ProviderSnapshot {
  provider: ExternalProvider;
  record: ExternalUsageRecord;
  cachedAtMs: number;
  ageMs: number;
}

// ── Constants ──

const CLAUDE_DIR = path.join(os.homedir(), '.claude');
const CONFIG_PATH = path.join(CLAUDE_DIR, 'statusline-config.json');
const SCHEDULE_CACHE_PATH = path.join(CLAUDE_DIR, 'statusline-schedule.json');
const CREDENTIALS_PATH = path.join(CLAUDE_DIR, '.credentials.json');
const SETTINGS_PATH = path.join(CLAUDE_DIR, 'settings.json');
const USAGE_CACHE_PATH = path.join(CLAUDE_DIR, 'statusline-usage-cache.json');
const CONTEXT_PATH = path.join(os.tmpdir(), 'claude', 'statusline-context.json');

const DEFAULT_SCHEDULE_URL = 'https://raw.githubusercontent.com/Nadav-Fux/claude-2x-statusline/main/schedule.json';
const CONTEXT_TTL_MS = 10 * 60_000;
const PROVIDER_CACHE_STALE_MS = 15 * 60_000;
const EXTERNAL_PROVIDER_ORDER: ExternalProvider[] = ['codex', 'glm', 'droid', 'antigravity', 'copilot'];
const PROVIDER_FALLBACK_LABELS: Record<ExternalProvider, string> = {
  codex: 'Codex',
  glm: 'GLM',
  droid: 'Droid',
  antigravity: 'Antigravity',
  copilot: 'Copilot',
};

const DEFAULT_SCHEDULE: Schedule = {
  v: 2,
  mode: 'peak_hours',
  peak: {
    enabled: true, tz: 'America/Los_Angeles',
    days: [1, 2, 3, 4, 5], start: 5, end: 11,
    label_peak: 'Peak', label_offpeak: 'Off-Peak',
  },
};

// ── State ──

let peakItem: vscode.StatusBarItem;
let fhItem: vscode.StatusBarItem;
let wdItem: vscode.StatusBarItem;
let cockpitItem: vscode.StatusBarItem;
let ctxItem: vscode.StatusBarItem;
let infoItem: vscode.StatusBarItem;
let refreshTimer: NodeJS.Timeout | undefined;
let currentIntervalSec = 30;
let isRefreshing = false;
let cachedSchedule: Schedule | null = null;
const TELEMETRY_URL = 'https://statusline-telemetry.nadavf.workers.dev/ping';
const HEARTBEAT_PATH = path.join(CLAUDE_DIR, '.statusline-heartbeat');
const TELEMETRY_ID_PATH = path.join(CLAUDE_DIR, '.statusline-telemetry-id');
let lastHeartbeatDate = '';
let cachedUsage: UsageData | null = null;
let usageFetchedAt = 0;

// ── Activation ──

export function activate(context: vscode.ExtensionContext) {
  // Create status bar items (right side, high priority = further left)
  peakItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 201);
  fhItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 200);
  wdItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 199);
  cockpitItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 198.5);
  ctxItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 198);
  infoItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 197);

  context.subscriptions.push(peakItem, fhItem, wdItem, cockpitItem, ctxItem, infoItem);

  // Register refresh command
  context.subscriptions.push(
    vscode.commands.registerCommand('claudeStatusline.refresh', () => refresh()),
    vscode.commands.registerCommand('claudeStatusline.refreshProviderCockpit', () => refreshProviderCockpit())
  );

  // Initial update
  refresh();
  maybeHeartbeat();

  // Start periodic refresh
  currentIntervalSec = vscode.workspace.getConfiguration('claudeStatusline').get<number>('refreshInterval', 30);
  refreshTimer = setInterval(() => refresh(), currentIntervalSec * 1000);

  // H8: Re-read config on VS Code settings change (refreshInterval, etc.)
  context.subscriptions.push(
    vscode.workspace.onDidChangeConfiguration(e => {
      if (e.affectsConfiguration('claudeStatusline')) {
        const newInterval = vscode.workspace.getConfiguration('claudeStatusline').get<number>('refreshInterval', 30);
        if (newInterval !== currentIntervalSec && refreshTimer) {
          clearInterval(refreshTimer);
          currentIntervalSec = newInterval;
          refreshTimer = setInterval(() => refresh(), currentIntervalSec * 1000);
        }
        refresh();
      }
    })
  );

  // Re-read config on file change
  const configWatcher = vscode.workspace.createFileSystemWatcher(
    new vscode.RelativePattern(CLAUDE_DIR, 'statusline-config.json')
  );
  configWatcher.onDidChange(() => refresh());
  configWatcher.onDidCreate(() => refresh());
  context.subscriptions.push(configWatcher);
}

export function deactivate() {
  if (refreshTimer) {
    clearInterval(refreshTimer);
  }
}

function maybeHeartbeat() {
  try {
    const config = loadConfig();
    // Telemetry is opt-in: requires telemetry: true in config (default is off).
    if ((config as any).telemetry !== true) { return; }
    const today = new Date().toISOString().slice(0, 10);
    if (lastHeartbeatDate === today) { return; }
    try {
      const mtime = fs.statSync(HEARTBEAT_PATH).mtime.toISOString().slice(0, 10);
      if (mtime === today) { lastHeartbeatDate = today; return; }
    } catch { /* no file */ }
    const uid = getTelemetryId();
    if (!uid) { return; }
    const payload = JSON.stringify({
      id: uid, v: '0.2.0', engine: 'vscode', tier: config.tier || 'standard',
      os: process.platform, event: 'heartbeat',
    });
    fs.writeFileSync(HEARTBEAT_PATH, today);
    lastHeartbeatDate = today;
    const req = https.request(TELEMETRY_URL, { method: 'POST', headers: { 'Content-Type': 'application/json' } });
    req.on('error', () => {});
    req.end(payload);
  } catch { /* telemetry is non-critical */ }
}

// ── Main refresh ──

async function refresh() {
  if (isRefreshing) return;
  isRefreshing = true;
  try {
    const config = loadConfig();
    const vsConfig = vscode.workspace.getConfiguration('claudeStatusline');
    const tier = vsConfig.get<string>('tier', 'auto') === 'auto' ? config.tier : vsConfig.get<string>('tier', 'standard');

    const schedule = await loadSchedule(config);
    cachedSchedule = schedule;

    updatePeakItem(schedule, vsConfig.get<boolean>('showPeakHours', true));
    await updateRateLimitItems(tier, vsConfig.get<boolean>('showRateLimits', true));
    updateProviderCockpit(config);
    updateContextItem(tier);
    updateInfoItem(tier);
  } catch {
    // Silently fail — statusline is non-critical
  } finally {
    isRefreshing = false;
  }
}

function refreshProviderCockpit() {
  try {
    updateProviderCockpit(loadConfig());
  } catch {
    cockpitItem.hide();
  }
}

function loadConfig(): StatuslineConfig {
  try {
    return JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf8'));
  } catch {
    return { tier: 'standard' };
  }
}

// ── Schedule ──

async function loadSchedule(config: StatuslineConfig): Promise<Schedule> {
  const cacheHours = config.schedule_cache_hours ?? 3;
  const scheduleUrl = config.schedule_url ?? DEFAULT_SCHEDULE_URL;

  // Check cache
  try {
    const stat = fs.statSync(SCHEDULE_CACHE_PATH);
    const ageHours = (Date.now() - stat.mtimeMs) / 3_600_000;
    if (ageHours < cacheHours) {
      return JSON.parse(fs.readFileSync(SCHEDULE_CACHE_PATH, 'utf8'));
    }
  } catch { /* no cache */ }

  // Fetch remote
  try {
    const data = await httpGet(scheduleUrl);
    const schedule = JSON.parse(data);
    fs.writeFileSync(SCHEDULE_CACHE_PATH, JSON.stringify(schedule, null, 2));
    return schedule;
  } catch { /* fetch failed */ }

  // Stale cache
  try {
    return JSON.parse(fs.readFileSync(SCHEDULE_CACHE_PATH, 'utf8'));
  } catch { /* no stale cache */ }

  return DEFAULT_SCHEDULE;
}

// ── Peak Hours ──

function updatePeakItem(schedule: Schedule, showPeak: boolean) {
  if (!showPeak || schedule.mode === 'normal') {
    peakItem.hide();
    return;
  }

  const peak = schedule.peak;
  if (!peak?.enabled) {
    peakItem.text = '$(check) Off-Peak';
    peakItem.backgroundColor = undefined;
    peakItem.color = new vscode.ThemeColor('statusBarItem.foreground');
    peakItem.tooltip = 'Claude Code: No peak hours restrictions';
    peakItem.show();
    return;
  }

  const now = new Date();
  const localOffset = -now.getTimezoneOffset() / 60;
  const hour = now.getHours() + now.getMinutes() / 60;
  const weekday = now.getDay() === 0 ? 7 : now.getDay(); // ISO weekday

  const peakDays = peak.days;
  const { startLocal, endLocal, peakDayOffset } = peakHoursToLocal(schedule, localOffset);
  const effectivePeakDays = peakDays.map(day => shiftWeekday(day, peakDayOffset));

  const isPeakDay = effectivePeakDays.includes(weekday);
  const prevWeekday = weekday === 1 ? 7 : weekday - 1;
  const prevWasPeak = effectivePeakDays.includes(prevWeekday);
  let isPeak = false;
  let minsLeft = 0;
  let minsUntil = 0;

  if (isPeakDay || prevWasPeak) {
    if (endLocal > startLocal) {
      if (isPeakDay) { isPeak = hour >= startLocal && hour < endLocal; }
      if (isPeak) { minsLeft = Math.floor((endLocal - hour) * 60); }
      else if (isPeakDay && hour < startLocal) { minsUntil = Math.floor((startLocal - hour) * 60); }
      else { minsUntil = minsUntilNextPeak(now, effectivePeakDays, startLocal); }
    } else {
      if (isPeakDay && hour >= startLocal) { isPeak = true; }
      else if (prevWasPeak && hour < endLocal) { isPeak = true; }
      if (isPeak) {
        minsLeft = hour >= startLocal
          ? Math.floor((24 - hour + endLocal) * 60)
          : Math.floor((endLocal - hour) * 60);
      } else {
        minsUntil = (isPeakDay && hour < startLocal)
          ? Math.floor((startLocal - hour) * 60)
          : minsUntilNextPeak(now, effectivePeakDays, startLocal);
      }
    }
  } else {
    minsUntil = minsUntilNextPeak(now, effectivePeakDays, startLocal);
  }

  const labelPeak = peak.label_peak || 'Peak';
  const labelOff = peak.label_offpeak || 'Off-Peak';
  const rangeStr = `${fmtHour(startLocal)}-${fmtHour(endLocal)}`;

  if (isPeak) {
    const t = fmtDuration(minsLeft);
    peakItem.text = `$(flame) ${labelPeak} — ${t} left (${rangeStr})`;
    if (minsLeft <= 30) {
      // Almost over — yellow
      peakItem.backgroundColor = new vscode.ThemeColor('statusBarItem.warningBackground');
    } else {
      // Deep in peak — red
      peakItem.backgroundColor = new vscode.ThemeColor('statusBarItem.errorBackground');
    }
    peakItem.tooltip = `Peak hours: ${rangeStr} (local time)\nEnds in ${t}`;
    peakItem.color = undefined;
  } else {
    if (minsUntil > 0) {
      peakItem.text = `$(check) ${labelOff} — peak in ${fmtDuration(minsUntil)} (${rangeStr})`;
      peakItem.tooltip = `Off-peak! Next peak in ${fmtDuration(minsUntil)}\nPeak hours: ${rangeStr} (local time)`;
    } else {
      peakItem.text = `$(check) ${labelOff}`;
      peakItem.tooltip = 'Off-peak — no restrictions';
    }
    peakItem.backgroundColor = undefined;
    peakItem.color = '#4ec9b0'; // teal/green for off-peak
  }
  peakItem.show();
}

// ── Rate Limits ──

async function updateRateLimitItems(tier: string, showRateLimits: boolean) {
  if (!showRateLimits) {
    fhItem.hide();
    wdItem.hide();
    return;
  }

  const usage = await fetchUsage();
  if (!usage) {
    fhItem.hide();
    wdItem.hide();
    return;
  }

  const fh = usage.five_hour;
  const wd = usage.seven_day;
  const fhPct = Math.round(fh?.utilization ?? 0);
  const wdPct = Math.round(wd?.utilization ?? 0);

  // 5-hour item — $(clock) icon, cyan/teal family
  updateFhItem(fhItem, fhPct, fh?.resets_at ?? fh?.reset_at);

  // 7-day item — $(history) icon, purple/blue family
  if (tier === 'minimal') {
    wdItem.hide();
  } else {
    updateWdItem(wdItem, wdPct, wd?.resets_at ?? wd?.reset_at);
  }
}

function updateFhItem(item: vscode.StatusBarItem, pct: number, resetAt?: string) {
  const bar = batteryBar(pct);
  // 5h: cyan/teal color family
  if (pct >= 80) {
    item.text = `$(warning) 5h:${pct}% ${bar}`;
    item.color = '#f14c4c';           // red text
    item.backgroundColor = undefined;
  } else if (pct >= 50) {
    item.text = `$(clock) 5h:${pct}% ${bar}`;
    item.color = '#e8ab3a';           // warm amber
    item.backgroundColor = undefined;
  } else {
    item.text = `$(clock) 5h:${pct}% ${bar}`;
    item.color = '#3dc9b0';           // teal/cyan
    item.backgroundColor = undefined;
  }

  const lines = ['$(clock) 5-Hour Session Limit', ''];
  lines.push(`Usage:  ${pct}%  ${usageBar(pct)}`);
  if (resetAt) { lines.push(`Resets: ${fmtResetTime(resetAt)}`); }
  if (pct >= 80) { lines.push('', '$(warning) High usage — consider slowing down'); }
  item.tooltip = lines.join('\n');
  item.show();
}

function updateWdItem(item: vscode.StatusBarItem, pct: number, resetAt?: string) {
  const bar = batteryBar(pct);
  // 7d: purple/violet color family — distinct from 5h teal
  if (pct >= 80) {
    item.text = `$(warning) 7d:${pct}% ${bar}`;
    item.color = '#f14c4c';           // red text
    item.backgroundColor = undefined;
  } else if (pct >= 50) {
    item.text = `$(history) 7d:${pct}% ${bar}`;
    item.color = '#d4a0ff';           // light purple/lavender
    item.backgroundColor = undefined;
  } else {
    item.text = `$(history) 7d:${pct}% ${bar}`;
    item.color = '#b4a0ff';           // soft purple
    item.backgroundColor = undefined;
  }

  const lines = ['$(history) 7-Day Rolling Limit', ''];
  lines.push(`Usage:  ${pct}%  ${usageBar(pct)}`);
  if (resetAt) { lines.push(`Resets: ${fmtResetTime(resetAt)}`); }
  if (pct >= 80) { lines.push('', '$(warning) High usage — consider slowing down'); }
  item.tooltip = lines.join('\n');
  item.show();
}

// ── Provider cockpit ──

// Cockpit priority order (left→right). Claude is always attempted; the rest are
// gated by the selected external providers. GLM/Copilot/Droid are droppable —
// they are appended to the status-bar text only while it stays within budget.
type CockpitKey = 'claude' | ExternalProvider;

const COCKPIT_ORDER: CockpitKey[] = ['claude', 'codex', 'antigravity', 'glm', 'copilot', 'droid'];
const COCKPIT_DROPPABLE = new Set<CockpitKey>(['glm', 'copilot', 'droid']);
const COCKPIT_SHORT: Record<CockpitKey, string> = {
  claude: 'Cl', codex: 'Cdx', antigravity: 'AGY', glm: 'GLM', copilot: 'CoP', droid: 'Drd',
};
const COCKPIT_FULL: Record<CockpitKey, string> = {
  claude: 'Claude', codex: 'Codex', antigravity: 'Antigravity', glm: 'GLM', copilot: 'Copilot', droid: 'Droid',
};
const DEFAULT_COCKPIT_MAX_LENGTH = 80;
const COCKPIT_ICON = '⛁'; // ⛁
const STALE_MARKER = '°'; // °
const ANTIGRAVITY_CLI_CACHE_PATH = path.join(CLAUDE_DIR, 'statusline-usage-antigravity-cli.json');

interface CockpitWindow {
  label: string;
  pct: number;
  resetsAt?: number | string | null;
}

interface CockpitPool {
  plan?: string | null;
  windows: CockpitWindow[];
}

interface CockpitSegment {
  key: CockpitKey;
  short: string;
  full: string;
  droppable: boolean;
  available: boolean;        // has usable pct → eligible for the bar
  cachedAtMs: number | null;
  ageMs: number | null;
  stale: boolean;
  plan?: string | null;
  source?: string | null;
  barBody: string | null;    // percent body without the short label
  pools: CockpitPool[];      // AGY carries one pool per plan; others carry one
  note?: string;             // e.g. 'no data', 'no usage', tokens summary
}

function updateProviderCockpit(config: StatuslineConfig) {
  const selected = new Set<ExternalProvider>(selectedExternalProviders(config));
  const maxLen = clampCockpitMaxLength(
    vscode.workspace.getConfiguration('claudeStatusline').get<number>('cockpitMaxLength', DEFAULT_COCKPIT_MAX_LENGTH)
  );

  const segments: CockpitSegment[] = [];
  for (const key of COCKPIT_ORDER) {
    if (key === 'claude') {
      segments.push(buildClaudeSegment());
    } else if (selected.has(key)) {
      segments.push(buildExternalSegment(key));
    }
  }

  const claudeSeg = segments.find(seg => seg.key === 'claude');
  const claudeAvailable = !!claudeSeg && claudeSeg.available;
  if (selected.size === 0 && !claudeAvailable) {
    cockpitItem.hide();
    return;
  }

  // Greedy append in priority order; stop at the first segment that would blow
  // the budget so lower-priority (droppable) segments never jump the queue.
  const rendered: CockpitSegment[] = [];
  let text = COCKPIT_ICON;
  for (const seg of segments) {
    if (!seg.available) { continue; }
    const piece = `${seg.short} ${seg.barBody}${seg.stale ? STALE_MARKER : ''}`;
    const candidate = rendered.length === 0 ? `${COCKPIT_ICON} ${piece}` : `${text} · ${piece}`;
    if (candidate.length <= maxLen) {
      text = candidate;
      rendered.push(seg);
    } else {
      break;
    }
  }

  cockpitItem.text = rendered.length === 0 ? `${COCKPIT_ICON} no data` : text;
  cockpitItem.tooltip = buildCockpitTooltip(segments, rendered, maxLen);
  cockpitItem.command = 'claudeStatusline.refreshProviderCockpit';
  cockpitItem.backgroundColor = undefined;
  const allStale = rendered.length > 0 && rendered.every(seg => seg.stale);
  cockpitItem.color = allStale ? new vscode.ThemeColor('descriptionForeground') : undefined;
  cockpitItem.show();
}

function clampCockpitMaxLength(value: number | undefined): number {
  const n = Number(value);
  if (!Number.isFinite(n)) { return DEFAULT_COCKPIT_MAX_LENGTH; }
  return Math.max(24, Math.min(400, Math.round(n)));
}

function emptyCockpitSegment(key: CockpitKey): CockpitSegment {
  return {
    key,
    short: COCKPIT_SHORT[key],
    full: COCKPIT_FULL[key],
    droppable: COCKPIT_DROPPABLE.has(key),
    available: false,
    cachedAtMs: null,
    ageMs: null,
    stale: false,
    plan: null,
    source: null,
    barBody: null,
    pools: [],
  };
}

function buildClaudeSegment(): CockpitSegment {
  const seg = emptyCockpitSegment('claude');
  try {
    const stat = fs.statSync(CONTEXT_PATH);
    const data: ContextData = JSON.parse(fs.readFileSync(CONTEXT_PATH, 'utf8'));
    const fh = numericPct(data.five_hour_pct);
    const wd = numericPct(data.seven_day_pct);
    if (fh === null && wd === null) {
      seg.note = 'no data';
      return seg;
    }
    const cachedAtMs = typeof data.ts === 'number' && data.ts > 0 ? data.ts * 1000 : stat.mtimeMs;
    seg.cachedAtMs = cachedAtMs;
    seg.ageMs = Math.max(0, Date.now() - cachedAtMs);
    seg.stale = seg.ageMs > PROVIDER_CACHE_STALE_MS;
    seg.plan = stringValue(data.model);
    seg.source = 'context';
    const windows: CockpitWindow[] = [];
    if (fh !== null) { windows.push({ label: '5h', pct: fh }); }
    if (wd !== null) { windows.push({ label: '7d', pct: wd }); }
    seg.pools = [{ windows }];
    seg.available = true;
    seg.barBody = windows.map(w => Math.round(w.pct)).join('/');
    return seg;
  } catch {
    seg.note = 'no data';
    return seg;
  }
}

function buildExternalSegment(key: ExternalProvider): CockpitSegment {
  const seg = emptyCockpitSegment(key);
  const snapshot = readProviderSnapshot(key);
  if (!snapshot) {
    seg.note = 'no data';
    return seg;
  }
  seg.cachedAtMs = snapshot.cachedAtMs;
  seg.ageMs = snapshot.ageMs;
  seg.stale = snapshot.ageMs > PROVIDER_CACHE_STALE_MS;
  seg.plan = stringValue(snapshot.record.plan) || stringValue(snapshot.record.level);
  seg.source = stringValue(snapshot.record.source);

  if (key === 'antigravity') {
    fillAntigravitySegment(seg, snapshot.record);
  } else if (key === 'droid') {
    fillDroidSegment(seg, snapshot.record);
  } else {
    fillStandardSegment(seg, snapshot.record);
  }

  if (!seg.available && !seg.note) {
    seg.note = snapshot.record.available === false ? 'unavailable' : 'no usage';
  }
  return seg;
}

function fillStandardSegment(seg: CockpitSegment, record: ExternalUsageRecord) {
  const windows: CockpitWindow[] = [];
  pushCockpitWindow(windows, record.five_hour, '5h');
  pushCockpitWindow(windows, record.weekly, '7d');
  if (windows.length === 0) {
    for (const metric of collectMetricWindows(record)) { pushCockpitWindow(windows, metric, 'm'); }
  }
  seg.pools = [{ windows }];
  if (windows.length > 0) {
    seg.available = true;
    seg.barBody = windows.map(w => Math.round(w.pct)).join('/');
  }
}

function fillAntigravitySegment(seg: CockpitSegment, record: ExternalUsageRecord) {
  const allPlans = Array.isArray(record.all_plans) ? record.all_plans : null;
  if (allPlans && allPlans.length > 0) {
    const pools: CockpitPool[] = [];
    for (const plan of allPlans) {
      if (!plan || typeof plan !== 'object') { continue; }
      const windows: CockpitWindow[] = [];
      pushCockpitWindow(windows, plan.five_hour, '5h');
      pushCockpitWindow(windows, plan.weekly, 'wk');
      pools.push({ plan: stringValue(plan.plan), windows });
    }
    seg.pools = pools;
    const parts = pools
      .filter(pool => pool.windows.length > 0)
      .map(pool => `${antigravityPoolAbbrev(pool.plan)}:${pool.windows.map(w => Math.round(w.pct)).join('/')}`);
    if (parts.length > 0) {
      seg.available = true;
      seg.barBody = parts.join(' ');
    }
    return;
  }

  // Fallbacks: top-level 5h/wk (selected plan) → compact metrics → antigravity-cli file.
  const windows: CockpitWindow[] = [];
  pushCockpitWindow(windows, record.five_hour, '5h');
  pushCockpitWindow(windows, record.weekly, 'wk');
  if (windows.length === 0) {
    for (const metric of collectMetricWindows(record)) { pushCockpitWindow(windows, metric, 'm'); }
  }
  if (windows.length === 0) {
    for (const metric of readAntigravityCliFallback()) { pushCockpitWindow(windows, metric, 'm'); }
  }
  seg.pools = [{ plan: stringValue(record.plan), windows }];
  if (windows.length > 0) {
    seg.available = true;
    seg.barBody = windows.map(w => Math.round(w.pct)).join('/');
  }
}

function fillDroidSegment(seg: CockpitSegment, record: ExternalUsageRecord) {
  // Droid caches carry token totals but no percentage windows → tooltip only.
  const total = record.tokens && typeof record.tokens === 'object' ? Number(record.tokens.total) : NaN;
  seg.note = Number.isFinite(total) ? `${fmtTokens(total)} tok` : 'no usage';
}

function pushCockpitWindow(windows: CockpitWindow[], window: ExternalUsageWindow | null | undefined, fallbackLabel: string) {
  if (!window || typeof window !== 'object') { return; }
  const pct = numericPct(window.used_pct);
  if (pct === null) { return; }
  windows.push({ label: stringValue(window.label) || fallbackLabel, pct, resetsAt: window.resets_at });
}

function collectMetricWindows(record: ExternalUsageRecord): ExternalUsageWindow[] {
  const out: ExternalUsageWindow[] = [];
  for (const arr of [record.metrics, record.metrics_5h, record.metrics_weekly]) {
    if (!Array.isArray(arr)) { continue; }
    for (const metric of arr) {
      if (metric && typeof metric === 'object') { out.push(metric); }
    }
  }
  return out;
}

function readAntigravityCliFallback(): ExternalUsageWindow[] {
  try {
    const cache: ExternalUsageCache = JSON.parse(fs.readFileSync(ANTIGRAVITY_CLI_CACHE_PATH, 'utf8'));
    const record = cache.record;
    if (!record || typeof record !== 'object') { return []; }
    const metrics = collectMetricWindows(record);
    if (metrics.length > 0) { return metrics; }
    const windows: ExternalUsageWindow[] = [];
    if (record.five_hour) { windows.push(record.five_hour); }
    if (record.weekly) { windows.push(record.weekly); }
    return windows;
  } catch {
    return [];
  }
}

function antigravityPoolAbbrev(plan: string | null | undefined): string {
  const p = (plan || '').toLowerCase();
  if (p.includes('gemini')) { return 'g'; }
  if (p.includes('claude')) { return 'c'; }
  if (p.includes('gpt')) { return 'x'; }
  const match = p.match(/[a-z0-9]/);
  return match ? match[0] : '?';
}

function buildCockpitTooltip(segments: CockpitSegment[], rendered: CockpitSegment[], maxLen: number): vscode.MarkdownString {
  const renderedKeys = new Set(rendered.map(seg => seg.key));
  const lines: string[] = ['### Multi-CLI cockpit', ''];
  lines.push('| Provider | Plan | Window | Used | Resets | Status |');
  lines.push('|:--|:--|:--|--:|:--|:--|');

  for (const seg of segments) {
    if (!seg.available) {
      lines.push(`| **${mdCell(seg.full)}** | ${mdCell(seg.plan)} | — | ${mdCell(seg.note || 'no data')} | — | — |`);
      continue;
    }
    const status = seg.stale ? `stale ${fmtAge(seg.ageMs ?? 0)}` : 'fresh';
    let firstRow = true;
    for (const pool of seg.pools) {
      let firstInPool = true;
      for (const window of pool.windows) {
        const providerCell = firstRow ? `**${mdCell(seg.full)}**` : '';
        const planCell = firstInPool ? mdCell(pool.plan ?? seg.plan) : '';
        const resets = mdCell(formatResetLocal(window.resetsAt));
        const statusCell = firstRow ? status : '';
        lines.push(`| ${providerCell} | ${planCell} | ${mdCell(window.label)} | ${Math.round(window.pct)}% | ${resets} | ${statusCell} |`);
        firstRow = false;
        firstInPool = false;
      }
    }
  }

  lines.push('');
  const dropped = segments.filter(seg => seg.available && !renderedKeys.has(seg.key)).map(seg => seg.short);
  if (dropped.length > 0) {
    lines.push(`Bar budget ${maxLen} chars — not shown: ${dropped.join(', ')}.`, '');
  }
  lines.push('Click to re-read provider caches.');
  const md = new vscode.MarkdownString(lines.join('\n'), true);
  md.supportThemeIcons = true;
  return md;
}

function mdCell(value: unknown): string {
  const s = value === null || value === undefined || value === '' ? '—' : String(value);
  return s.replace(/\|/g, '\\|').replace(/\r?\n/g, ' ');
}

function selectedExternalProviders(config: StatuslineConfig): ExternalProvider[] {
  const providers = config.providers;
  if (providers && Array.isArray(providers.selected)) {
    return providers.selected
      .filter((provider): provider is ExternalProvider => isExternalProvider(provider));
  }

  const external = config.external_providers;
  if (!external || typeof external !== 'object') { return []; }
  return EXTERNAL_PROVIDER_ORDER.filter(provider => {
    const value = external[provider];
    return !!value && typeof value === 'object' && (value as { enabled?: unknown }).enabled === true;
  });
}

function isExternalProvider(value: unknown): value is ExternalProvider {
  return typeof value === 'string' && value !== 'claude' && (EXTERNAL_PROVIDER_ORDER as string[]).includes(value);
}

function providerCachePath(provider: ExternalProvider): string {
  return path.join(CLAUDE_DIR, `statusline-usage-${provider}.json`);
}

function readProviderSnapshot(provider: ExternalProvider): ProviderSnapshot | null {
  const cachePath = providerCachePath(provider);
  try {
    const stat = fs.statSync(cachePath);
    const cache: ExternalUsageCache = JSON.parse(fs.readFileSync(cachePath, 'utf8'));
    const record = normalizeProviderRecord(provider, cache);
    if (!record) { return null; }

    const cachedAt = Number(cache.cached_at);
    const cachedAtMs = Number.isFinite(cachedAt) && cachedAt > 0 ? cachedAt * 1000 : stat.mtimeMs;
    const ageMs = Math.max(0, Date.now() - cachedAtMs);
    return { provider, record, cachedAtMs, ageMs };
  } catch {
    return null;
  }
}

function normalizeProviderRecord(provider: ExternalProvider, cache: ExternalUsageCache): ExternalUsageRecord | null {
  if (cache.record && typeof cache.record === 'object') {
    // Keep unavailable records too — the tooltip lists them explicitly.
    return {
      provider,
      label: PROVIDER_FALLBACK_LABELS[provider],
      ...cache.record,
    };
  }
  if (provider === 'glm' && cache.response && typeof cache.response === 'object') {
    return parseGlmCacheResponse(cache.response as Record<string, unknown>);
  }
  return null;
}

function parseGlmCacheResponse(body: Record<string, unknown>): ExternalUsageRecord | null {
  const data = body.data && typeof body.data === 'object' ? body.data as Record<string, unknown> : {};
  const limits = Array.isArray(data.limits) ? data.limits : [];
  let fiveHour: ExternalUsageWindow | null = null;
  let weekly: ExternalUsageWindow | null = null;

  for (const item of limits) {
    if (!item || typeof item !== 'object') { continue; }
    const row = item as Record<string, unknown>;
    const reset = millisToEpochSeconds(row.nextResetTime);
    if (row.type === 'TIME_LIMIT') {
      fiveHour = usageWindow(row.percentage, reset, '5h');
    } else if (row.type === 'TOKENS_LIMIT') {
      weekly = usageWindow(row.percentage, reset, 'tok');
    }
  }

  if (!fiveHour && !weekly) { return null; }
  const metrics = [fiveHour, weekly].filter((metric): metric is ExternalUsageWindow => metric !== null);
  return {
    provider: 'glm',
    label: 'GLM',
    available: true,
    display: 'compact',
    plan: stringValue(data.level) ?? stringValue(body.level),
    five_hour: fiveHour,
    weekly,
    metrics,
  };
}

function millisToEpochSeconds(value: unknown): number | null {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) { return null; }
  return Math.round(numeric / 1000);
}

function usageWindow(usedPct: unknown, resetsAt: number | null, label: string): ExternalUsageWindow | null {
  const pct = numericPct(usedPct);
  if (pct === null) { return null; }
  return { label, used_pct: pct, resets_at: resetsAt };
}

function numericPct(value: unknown): number | null {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) { return null; }
  return Math.max(0, Math.min(100, numeric));
}

function stringValue(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}

function formatResetLocal(value: number | string | null | undefined): string {
  if (value === null || value === undefined || value === '') { return ''; }
  let date: Date;
  if (typeof value === 'number') {
    date = new Date(value * 1000);
  } else {
    const numeric = Number(value);
    date = Number.isFinite(numeric) ? new Date(numeric * 1000) : new Date(value);
  }
  if (Number.isNaN(date.getTime())) { return String(value); }
  return formatLocalDateTime(date.getTime());
}

function formatLocalDateTime(epochMs: number): string {
  return new Intl.DateTimeFormat(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  }).format(new Date(epochMs));
}

function fmtAge(ageMs: number): string {
  const mins = Math.max(1, Math.floor(ageMs / 60_000));
  if (mins < 60) { return `${mins}m`; }
  const hours = Math.floor(mins / 60);
  if (hours < 48) { return `${hours}h`; }
  return `${Math.floor(hours / 24)}d`;
}

function batteryBar(pct: number): string {
  const width = 8;
  const filled = Math.round(pct * width / 100);
  return '\u2588'.repeat(filled) + '\u2591'.repeat(width - filled);
}

async function fetchUsage(): Promise<UsageData | null> {
  // Use memory cache if fresh (60s)
  if (cachedUsage && Date.now() - usageFetchedAt < 60_000) {
    return cachedUsage;
  }

  const contextUsage = loadUsageFromFreshContext();
  if (contextUsage) {
    cachedUsage = contextUsage;
    usageFetchedAt = Date.now();
    return cachedUsage;
  }

  const token = getOAuthToken();
  if (!token) { return cachedUsage ?? loadUsageFromDisk(); }

  try {
    const data = await httpGetWithHeaders('https://api.anthropic.com/api/oauth/usage', {
      'Authorization': `Bearer ${token}`,
      'Accept': 'application/json',
      'Content-Type': 'application/json',
      'anthropic-beta': 'oauth-2025-04-20',
      'User-Agent': 'claude-statusline-vscode/0.2.0',
    });
    const parsed = JSON.parse(data);
    // Validate response has expected fields (reject error responses like 429)
    if (!parsed.five_hour && !parsed.seven_day) {
      return cachedUsage ?? loadUsageFromDisk();
    }
    cachedUsage = parsed;
    usageFetchedAt = Date.now();
    saveUsageToDisk(parsed);
    return cachedUsage;
  } catch {
    return cachedUsage ?? loadUsageFromDisk();
  }
}

function loadUsageFromDisk(): UsageData | null {
  try {
    const data = JSON.parse(fs.readFileSync(USAGE_CACHE_PATH, 'utf8'));
    if (data.five_hour || data.seven_day) {
      cachedUsage = data;
      usageFetchedAt = Date.now() - 55_000; // treat as almost-stale so we retry soon
      return data;
    }
  } catch { /* no disk cache */ }
  return null;
}

function loadUsageFromFreshContext(): UsageData | null {
  try {
    const stat = fs.statSync(CONTEXT_PATH);
    if (Date.now() - stat.mtimeMs > CONTEXT_TTL_MS) { return null; }
    const data: ContextData = JSON.parse(fs.readFileSync(CONTEXT_PATH, 'utf8'));
    if (typeof data.five_hour_pct !== 'number' || typeof data.seven_day_pct !== 'number') {
      return null;
    }
    return {
      five_hour: { utilization: data.five_hour_pct },
      seven_day: { utilization: data.seven_day_pct },
    };
  } catch {
    return null;
  }
}

function saveUsageToDisk(data: UsageData) {
  try {
    const dir = path.dirname(USAGE_CACHE_PATH);
    if (!fs.existsSync(dir)) { fs.mkdirSync(dir, { recursive: true, mode: 0o700 }); }
    fs.writeFileSync(USAGE_CACHE_PATH, JSON.stringify(data, null, 2), { mode: 0o600 });
  } catch { /* write failed */ }
}

function getOAuthToken(): string {
  // Env var
  const envToken = process.env.CLAUDE_CODE_OAUTH_TOKEN;
  if (envToken) { return envToken; }

  // Credentials file
  try {
    const creds = JSON.parse(fs.readFileSync(CREDENTIALS_PATH, 'utf8'));
    const token = creds?.claudeAiOauth?.accessToken;
    if (token) { return token; }
  } catch { /* no creds file */ }

  // Windows Credential Manager — H9: Get-StoredCredential needs external module;
  // use cmdkey + Win32 CredRead via PowerShell P/Invoke instead
  if (process.platform === 'win32') {
    try {
      const psScript = [
        'Add-Type @"',
        'using System;',
        'using System.Runtime.InteropServices;',
        'public class WinCred {',
        '  [DllImport("advapi32.dll", SetLastError = true)]',
        '  public static extern bool CredRead(string target, uint type, uint flags, out IntPtr cred);',
        '  [DllImport("advapi32.dll")] public static extern void CredFree(IntPtr cred);',
        '  [StructLayout(LayoutKind.Sequential)]',
        '  public struct CRED { public uint Flags; public uint Type; public string TargetName;',
        '    public string Comment; public long LastWritten; public uint BlobSize;',
        '    public IntPtr Blob; public uint Persist; public uint AttrCount;',
        '    public IntPtr Attrs; public string Alias; public string UserName; }',
        '}',
        '"@',
        '$p = [IntPtr]::Zero',
        'if ([WinCred]::CredRead("Claude Code-credentials", 1, 0, [ref]$p)) {',
        '  $c = [System.Runtime.InteropServices.Marshal]::PtrToStructure($p, [WinCred+CRED])',
        '  $b = New-Object byte[] $c.BlobSize',
        '  [System.Runtime.InteropServices.Marshal]::Copy($c.Blob, $b, 0, $c.BlobSize)',
        '  $s = [System.Text.Encoding]::Unicode.GetString($b)',
        '  [WinCred]::CredFree($p)',
        '  Write-Output $s -NoEnumerate',
        '}'
      ].join('\n');
      const result = execFileSync('powershell.exe', [
        '-NoProfile', '-NoLogo', '-Command', psScript
      ], { timeout: 5000, encoding: 'utf8' });
      if (result.trim()) {
        const data = JSON.parse(result.trim());
        const token = data?.claudeAiOauth?.accessToken;
        if (token) { return token; }
      }
    } catch { /* no credential or CredRead failed */ }
  }

  // macOS Keychain
  if (process.platform === 'darwin') {
    try {
      const result = execFileSync('security', [
        'find-generic-password', '-s', 'Claude Code-credentials', '-w'
      ], { timeout: 3000, encoding: 'utf8' });
      if (result.trim()) {
        const data = JSON.parse(result.trim());
        const token = data?.claudeAiOauth?.accessToken;
        if (token) { return token; }
      }
    } catch { /* no keychain entry */ }
  }

  return '';
}

// ── Context Window ──

function updateContextItem(tier: string) {
  if (tier === 'minimal') {
    ctxItem.hide();
    return;
  }

  try {
    const stat = fs.statSync(CONTEXT_PATH);
    // Ignore if older than 10 minutes (session probably ended)
    if (Date.now() - stat.mtimeMs > CONTEXT_TTL_MS) {
      ctxItem.hide();
      return;
    }
    const data: ContextData = JSON.parse(fs.readFileSync(CONTEXT_PATH, 'utf8'));
    const size = data.context_window_size;
    const current = data.current_usage;
    if (!size || current === undefined) {
      ctxItem.hide();
      return;
    }

    const pct = data.pct ?? Math.round(current * 100 / size);
    const curStr = fmtTokens(current);
    const sizeStr = fmtTokens(size);
    const bar = batteryBar(pct);

    const activeAgents = data.active_workflow_agents || 0;
    const workflowTokens = data.subagent_tokens_live || 0;
    const workflowSuffix = activeAgents > 0 ? ` $(hubot) ${activeAgents}/${fmtTokens(workflowTokens)}` : '';
    ctxItem.text = `$(symbol-ruler) ${curStr}/${sizeStr} ${bar} ${pct}%${workflowSuffix}`;

    if (pct >= 80) {
      ctxItem.backgroundColor = new vscode.ThemeColor('statusBarItem.errorBackground');
      ctxItem.color = undefined;
    } else if (pct >= 60) {
      ctxItem.backgroundColor = new vscode.ThemeColor('statusBarItem.warningBackground');
      ctxItem.color = undefined;
    } else {
      ctxItem.backgroundColor = undefined;
      ctxItem.color = '#4ec9b0';
    }

    const lines = ['Claude Code — Context Window', ''];
    lines.push(`Usage:  ${curStr} / ${sizeStr}  (${pct}%)`);
    lines.push(`Bar:    ${usageBar(pct)}`);
    if (activeAgents > 0) {
      lines.push(`Workflows: ${activeAgents} agents, ${fmtTokens(workflowTokens)} ctx`);
    } else if ((data.subagent_runs_session || 0) > 0) {
      lines.push(`Workflows: ${data.subagent_runs_session} completed runs this session`);
    }
    if (data.model) { lines.push(`Model:  ${data.model}`); }
    if (pct >= 80) { lines.push('', '$(warning) Context almost full — consider starting a new session'); }
    ctxItem.tooltip = lines.join('\n');
    ctxItem.show();
  } catch {
    ctxItem.hide();
  }
}

function fmtTokens(n: number): string {
  if (n >= 1_000_000) { return `${(n / 1_000_000).toFixed(1)}M`; }
  if (n >= 1_000) { return `${Math.round(n / 1_000)}K`; }
  return String(n);
}

// ── Info item (model + effort) ──

function updateInfoItem(tier: string) {
  if (tier === 'minimal') {
    infoItem.hide();
    return;
  }

  const parts: string[] = [];

  // Effort level from settings
  try {
    const settings = JSON.parse(fs.readFileSync(SETTINGS_PATH, 'utf8'));
    const effort = settings.effortLevel;
    if (effort) {
      const labels: Record<string, string> = { low: 'LO', medium: 'MED', high: 'HI' };
      parts.push(labels[effort] || effort.toUpperCase());
    }
  } catch { /* no settings */ }

  if (parts.length === 0) {
    infoItem.hide();
    return;
  }

  const label = parts.join(' | ');
  infoItem.text = `$(gear) ${label}`;
  // Color effort level
  const effort = parts[0];
  if (effort === 'HI') {
    infoItem.color = '#dcdcaa'; // warm yellow for high effort
  } else if (effort === 'LO') {
    infoItem.color = '#9cdcfe'; // cool blue for low effort
  } else {
    infoItem.color = undefined;
  }
  infoItem.tooltip = 'Claude Code Settings';
  infoItem.show();
}

// ── Time helpers ──

function fmtDuration(mins: number): string {
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return h > 0 ? `${h}h ${String(m).padStart(2, '0')}m` : `${m}m`;
}

function fmtHour(h: number): string {
  h = ((h % 24) + 24) % 24;
  const hInt = Math.floor(h);
  const mInt = Math.round((h - hInt) * 60);
  const ampm = hInt < 12 ? 'am' : 'pm';
  const display = hInt % 12 || 12;
  return mInt ? `${display}:${String(mInt).padStart(2, '0')}${ampm}` : `${display}${ampm}`;
}

function fmtResetTime(iso: string): string {
  try {
    const d = new Date(iso);
    const now = new Date();
    const diffMin = Math.floor((d.getTime() - now.getTime()) / 60_000);
    if (diffMin <= 0) { return 'now'; }
    return `in ${fmtDuration(diffMin)}`;
  } catch {
    return iso;
  }
}

function usageBar(pct: number): string {
  const width = 15;
  const filled = Math.floor(pct * width / 100);
  return '\u2588'.repeat(filled) + '\u2591'.repeat(width - filled);
}

// ── Timezone helpers ──

function getSourceOffset(tz: string): number {
  const now = new Date();
  return timeZoneOffsetHours(tz || 'America/Los_Angeles', now)
    ?? timeZoneOffsetHours('America/Los_Angeles', now)
    ?? 0;
}

function timeZoneOffsetHours(timeZone: string, date: Date): number | null {
  try {
    const formatter = new Intl.DateTimeFormat('en-US', {
      timeZone,
      hourCycle: 'h23',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
    const parts = formatter.formatToParts(date);
    const values: Record<string, number> = {};
    for (const part of parts) {
      if (part.type !== 'literal') {
        values[part.type] = Number(part.value);
      }
    }
    const zonedAsUtc = Date.UTC(
      values.year,
      values.month - 1,
      values.day,
      values.hour,
      values.minute,
      values.second
    );
    const utc = Date.UTC(
      date.getUTCFullYear(),
      date.getUTCMonth(),
      date.getUTCDate(),
      date.getUTCHours(),
      date.getUTCMinutes(),
      date.getUTCSeconds()
    );
    const offset = (zonedAsUtc - utc) / 3_600_000;
    return Number.isFinite(offset) ? offset : null;
  } catch {
    return null;
  }
}

function peakHoursToLocal(schedule: Schedule, localOffset: number): { startLocal: number; endLocal: number; peakDayOffset: number } {
  const peak = schedule.peak;
  const startH = peak.start;
  const endH = peak.end;
  const srcOffset = getSourceOffset(peak.tz);

  const rawStartLocal = startH - srcOffset + localOffset;
  const peakDayOffset = Math.floor(rawStartLocal / 24);
  const startLocal = ((rawStartLocal % 24) + 24) % 24;
  const endLocal = ((endH - srcOffset + localOffset) % 24 + 24) % 24;
  return { startLocal, endLocal, peakDayOffset };
}

function shiftWeekday(day: number, delta: number): number {
  return ((day - 1 + delta) % 7 + 7) % 7 + 1;
}

function minsUntilNextPeak(now: Date, peakDays: number[], startLocalHour: number): number {
  const hour = now.getHours() + now.getMinutes() / 60;
  const weekday = now.getDay() === 0 ? 7 : now.getDay();
  for (let offset = 1; offset <= 7; offset++) {
    const nextDay = ((weekday - 1 + offset) % 7) + 1;
    if (peakDays.includes(nextDay)) {
      return Math.floor((24 - hour) * 60) + (offset - 1) * 1440 + Math.floor(startLocalHour * 60);
    }
  }
  return 0;
}

// ── HTTP helpers ──

function httpGet(url: string): Promise<string> {
  return new Promise((resolve, reject) => {
    const req = https.get(url, { timeout: 5000, headers: { 'User-Agent': 'claude-statusline-vscode/0.1.0' } }, (res) => {
      let data = '';
      res.on('data', (chunk: Buffer) => { data += chunk; });
      res.on('end', () => resolve(data));
    });
    req.on('error', reject);
    req.on('timeout', () => { req.destroy(); reject(new Error('timeout')); });
  });
}

function httpGetWithHeaders(url: string, headers: Record<string, string>): Promise<string> {
  return new Promise((resolve, reject) => {
    const parsed = new URL(url);
    const req = https.request({
      hostname: parsed.hostname,
      path: parsed.pathname,
      method: 'GET',
      timeout: 5000,
      headers,
    }, (res) => {
      let data = '';
      res.on('data', (chunk: Buffer) => { data += chunk; });
      res.on('end', () => {
        if (res.statusCode && res.statusCode >= 200 && res.statusCode < 300) {
          resolve(data);
        } else {
          reject(new Error(`HTTP ${res.statusCode}`));
        }
      });
    });
    req.on('error', reject);
    req.on('timeout', () => { req.destroy(); reject(new Error('timeout')); });
    req.end();
  });
}

function getTelemetryId(): string {
  try {
    if (!fs.existsSync(CLAUDE_DIR)) {
      fs.mkdirSync(CLAUDE_DIR, { recursive: true, mode: 0o700 });
    }
    if (fs.existsSync(TELEMETRY_ID_PATH)) {
      const existing = fs.readFileSync(TELEMETRY_ID_PATH, 'utf8').trim().toLowerCase();
      if (/^[0-9a-f]{16}$/.test(existing)) {
        return existing;
      }
    }
    const crypto = require('crypto');
    const id = crypto.randomBytes(8).toString('hex');
    fs.writeFileSync(TELEMETRY_ID_PATH, id, { mode: 0o600 });
    return id;
  } catch {
    return '';
  }
}
