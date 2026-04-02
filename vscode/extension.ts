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
}

interface UsageData {
  five_hour?: { utilization: number; reset_at?: string; resets_at?: string };
  seven_day?: { utilization: number; reset_at?: string; resets_at?: string };
}

interface ContextData {
  current_usage?: number;
  context_window_size?: number;
  pct?: number;
  model?: string;
  updated_at?: string;
}

// ── Constants ──

const CLAUDE_DIR = path.join(os.homedir(), '.claude');
const CONFIG_PATH = path.join(CLAUDE_DIR, 'statusline-config.json');
const SCHEDULE_CACHE_PATH = path.join(CLAUDE_DIR, 'statusline-schedule.json');
const CREDENTIALS_PATH = path.join(CLAUDE_DIR, '.credentials.json');
const SETTINGS_PATH = path.join(CLAUDE_DIR, 'settings.json');
const USAGE_CACHE_PATH = path.join(os.tmpdir(), 'claude', 'statusline-usage-cache.json');
const CONTEXT_PATH = path.join(os.tmpdir(), 'claude', 'statusline-context.json');

const DEFAULT_SCHEDULE_URL = 'https://raw.githubusercontent.com/Nadav-Fux/claude-2x-statusline/main/schedule.json';

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
let ctxItem: vscode.StatusBarItem;
let infoItem: vscode.StatusBarItem;
let refreshTimer: NodeJS.Timeout | undefined;
let cachedSchedule: Schedule | null = null;
let cachedUsage: UsageData | null = null;
let usageFetchedAt = 0;

// ── Activation ──

export function activate(context: vscode.ExtensionContext) {
  // Create status bar items (right side, high priority = further left)
  peakItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 201);
  fhItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 200);
  wdItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 199);
  ctxItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 198);
  infoItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 197);

  context.subscriptions.push(peakItem, fhItem, wdItem, ctxItem, infoItem);

  // Register refresh command
  context.subscriptions.push(
    vscode.commands.registerCommand('claudeStatusline.refresh', () => refresh())
  );

  // Initial update
  refresh();

  // Start periodic refresh
  const intervalSec = vscode.workspace.getConfiguration('claudeStatusline').get<number>('refreshInterval', 30);
  refreshTimer = setInterval(() => refresh(), intervalSec * 1000);

  // Re-read config on change
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

// ── Main refresh ──

async function refresh() {
  try {
    const config = loadConfig();
    const vsConfig = vscode.workspace.getConfiguration('claudeStatusline');
    const tier = vsConfig.get<string>('tier', 'auto') === 'auto' ? config.tier : vsConfig.get<string>('tier', 'standard');

    const schedule = await loadSchedule(config);
    cachedSchedule = schedule;

    updatePeakItem(schedule, vsConfig.get<boolean>('showPeakHours', true));
    await updateRateLimitItems(tier, vsConfig.get<boolean>('showRateLimits', true));
    updateContextItem(tier);
    updateInfoItem(tier);
  } catch {
    // Silently fail — statusline is non-critical
  }
}

// ── Config ──

function loadConfig(): StatuslineConfig {
  try {
    return JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf8'));
  } catch {
    return { tier: 'standard' };
  }
}

// ── Schedule ──

async function loadSchedule(config: StatuslineConfig): Promise<Schedule> {
  const cacheHours = config.schedule_cache_hours ?? 6;
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
  const { startLocal, endLocal } = peakHoursToLocal(schedule, localOffset);

  const isPeakDay = peakDays.includes(weekday);
  let isPeak = false;
  let minsLeft = 0;
  let minsUntil = 0;

  if (isPeakDay) {
    if (endLocal > startLocal) {
      isPeak = hour >= startLocal && hour < endLocal;
      if (isPeak) { minsLeft = Math.floor((endLocal - hour) * 60); }
      else if (hour < startLocal) { minsUntil = Math.floor((startLocal - hour) * 60); }
      else { minsUntil = minsUntilNextPeak(now, peakDays, startLocal); }
    } else {
      isPeak = hour >= startLocal || hour < endLocal;
      if (isPeak) {
        minsLeft = hour >= startLocal
          ? Math.floor((24 - hour + endLocal) * 60)
          : Math.floor((endLocal - hour) * 60);
      } else {
        minsUntil = hour < startLocal
          ? Math.floor((startLocal - hour) * 60)
          : minsUntilNextPeak(now, peakDays, startLocal);
      }
    }
  } else {
    minsUntil = minsUntilNextPeak(now, peakDays, startLocal);
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

  // 5-hour item
  updateBatteryItem(fhItem, '5h', fhPct, fh?.resets_at ?? fh?.reset_at);

  // 7-day item (hide in minimal tier)
  if (tier === 'minimal') {
    wdItem.hide();
  } else {
    updateBatteryItem(wdItem, '7d', wdPct, wd?.resets_at ?? wd?.reset_at);
  }
}

function updateBatteryItem(item: vscode.StatusBarItem, label: string, pct: number, resetAt?: string) {
  const bar = batteryBar(pct);
  const icon = pct >= 80 ? '$(warning)' : pct >= 50 ? '$(dashboard)' : '$(pulse)';
  item.text = `${icon} ${label} ${bar} ${pct}%`;

  // Color coding — matches terminal: green <50%, yellow 50-79%, red ≥80%
  if (pct >= 80) {
    item.backgroundColor = new vscode.ThemeColor('statusBarItem.errorBackground');
    item.color = undefined;
  } else if (pct >= 50) {
    item.backgroundColor = new vscode.ThemeColor('statusBarItem.warningBackground');
    item.color = undefined;
  } else {
    item.backgroundColor = undefined;
    item.color = '#4ec9b0'; // green/teal for healthy
  }

  // Tooltip
  const lines = [`Claude Code — ${label} Rate Limit`, ''];
  lines.push(`Usage:  ${pct}%  ${usageBar(pct)}`);
  if (resetAt) {
    lines.push(`Resets: ${fmtResetTime(resetAt)}`);
  }
  if (pct >= 80) {
    lines.push('', '$(warning) High usage — consider slowing down');
  }
  item.tooltip = lines.join('\n');
  item.show();
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

  const token = getOAuthToken();
  if (!token) { return cachedUsage ?? loadUsageFromDisk(); }

  try {
    const data = await httpGetWithHeaders('https://api.anthropic.com/api/oauth/usage', {
      'Authorization': `Bearer ${token}`,
      'Accept': 'application/json',
      'Content-Type': 'application/json',
      'anthropic-beta': 'oauth-2025-04-20',
      'User-Agent': 'claude-statusline-vscode/0.1.0',
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

function saveUsageToDisk(data: UsageData) {
  try {
    const dir = path.dirname(USAGE_CACHE_PATH);
    if (!fs.existsSync(dir)) { fs.mkdirSync(dir, { recursive: true }); }
    fs.writeFileSync(USAGE_CACHE_PATH, JSON.stringify(data, null, 2));
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

  // Windows Credential Manager
  if (process.platform === 'win32') {
    try {
      const result = execFileSync('powershell.exe', [
        '-NoProfile', '-Command',
        `$c = Get-StoredCredential -Target 'Claude Code-credentials' -ErrorAction SilentlyContinue; if ($c) { [System.Runtime.InteropServices.Marshal]::PtrToStringAuto([System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($c.Password)) }`
      ], { timeout: 3000, encoding: 'utf8' });
      if (result.trim()) {
        const data = JSON.parse(result.trim());
        const token = data?.claudeAiOauth?.accessToken;
        if (token) { return token; }
      }
    } catch { /* no credential */ }
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
    if (Date.now() - stat.mtimeMs > 600_000) {
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

    ctxItem.text = `$(symbol-ruler) ${curStr}/${sizeStr} ${bar} ${pct}%`;

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

function getPacificOffset(): number {
  const now = new Date();
  const year = now.getUTCFullYear();
  // Second Sunday of March
  const mar1 = new Date(Date.UTC(year, 2, 1));
  const dstStart = new Date(Date.UTC(year, 2, 1 + ((7 - mar1.getUTCDay()) % 7) + 7, 10));
  // First Sunday of November
  const nov1 = new Date(Date.UTC(year, 10, 1));
  const dstEnd = new Date(Date.UTC(year, 10, 1 + ((7 - nov1.getUTCDay()) % 7), 9));
  return (now >= dstStart && now < dstEnd) ? -7 : -8;
}

function getSourceOffset(tz: string): number {
  if (!tz || tz === 'America/Los_Angeles') { return getPacificOffset(); }
  if (tz === 'UTC' || tz === 'Etc/UTC') { return 0; }
  // For other US timezones, apply known offsets (DST-aware via Pacific)
  const pacificOff = getPacificOffset(); // -7 PDT or -8 PST
  const tzOffsets: Record<string, number> = {
    'America/New_York': pacificOff + 3,
    'America/Chicago': pacificOff + 2,
    'America/Denver': pacificOff + 1,
  };
  return tzOffsets[tz] ?? getPacificOffset();
}

function peakHoursToLocal(schedule: Schedule, localOffset: number): { startLocal: number; endLocal: number } {
  const peak = schedule.peak;
  const startH = peak.start;
  const endH = peak.end;
  const srcOffset = getSourceOffset(peak.tz);

  const startLocal = ((startH - srcOffset + localOffset) % 24 + 24) % 24;
  const endLocal = ((endH - srcOffset + localOffset) % 24 + 24) % 24;
  return { startLocal, endLocal };
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
