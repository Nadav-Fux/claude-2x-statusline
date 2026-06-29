const { URL } = require('url');

function parseGatewayHost(baseUrl) {
  const raw = String(baseUrl || '').trim();
  if (!raw) return '';
  try {
    const url = new URL(raw.includes('://') ? raw : `https://${raw}`);
    return String(url.hostname || '').trim().toLowerCase();
  } catch {
    try {
      return raw.split('/')[0].split('@').pop().split(':')[0].trim().toLowerCase();
    } catch {
      return '';
    }
  }
}

function providerLabelForHost(host) {
  const h = String(host || '').toLowerCase();
  if (!h) return '';
  if (h.includes('z.ai') || h.includes('bigmodel.cn')) return 'GLM';
  if (h.includes('openrouter')) return 'OpenRouter';
  if (h.includes('moonshot') || h.includes('kimi')) return 'Kimi';
  if (h.includes('deepseek')) return 'DeepSeek';
  return h;
}

function displayHostForHost(host) {
  const h = String(host || '').toLowerCase();
  if (!h) return '';
  if (h.includes('z.ai')) return 'z.ai';
  if (h.includes('bigmodel.cn')) return 'bigmodel.cn';
  return h.replace(/^api\./, '');
}

function gatewayInfo({ env = process.env, settings = {}, config = {} } = {}) {
  const settingsEnv = settings && typeof settings.env === 'object' && !Array.isArray(settings.env) ? settings.env : {};
  const baseUrl = String(env.ANTHROPIC_BASE_URL || settingsEnv.ANTHROPIC_BASE_URL || '').trim();
  const authToken = String(env.ANTHROPIC_AUTH_TOKEN || settingsEnv.ANTHROPIC_AUTH_TOKEN || '').trim();
  const host = parseGatewayHost(baseUrl);
  const awareness = !config || config.gateway_awareness !== false;
  const foreign = Boolean(awareness && host && host !== 'api.anthropic.com');
  const label = providerLabelForHost(host);
  const displayHost = displayHostForHost(host);
  return { baseUrl, authTokenPresent: Boolean(authToken), host, displayHost, label, foreign };
}

function isForeignGateway(baseUrl) {
  return gatewayInfo({ env: { ANTHROPIC_BASE_URL: baseUrl } }).foreign;
}

function gatewayBadgeText(info) {
  if (!info || !info.foreign) return '';
  const host = info.displayHost || info.host || '';
  const label = info.label || host;
  if (!host) return '';
  return label && label !== host ? `via ${host} (${label})` : `via ${host}`;
}

function gatewayNoteLabel(info) {
  if (!info || !info.foreign) return '';
  return info.label || info.displayHost || info.host || '';
}

module.exports = {
  parseGatewayHost,
  providerLabelForHost,
  displayHostForHost,
  gatewayInfo,
  isForeignGateway,
  gatewayBadgeText,
  gatewayNoteLabel,
};
