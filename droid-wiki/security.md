# Security

## Trust boundaries

The plugin operates entirely locally. It reads session metadata from Claude Code's stdin, writes state files to `~/.claude/`, and sends anonymous telemetry to a Cloudflare Worker. No sensitive data leaves the machine.

## Data sanitization

Before any telemetry submission, data is sanitized client-side:

| Input | Sanitized to |
|-------|-------------|
| Home directory paths | `~/` |
| Usernames | `<user>` |
| Hostnames | `<host>` |

No conversation content, file contents, source code, API keys, or session IDs are transmitted. The telemetry payload is limited to: anonymous ID (hex hash), version, engine, tier, OS, and event type.

## Telemetry ID

The telemetry ID is a 16-character hex string generated from `secrets.token_hex(8)` (or `openssl rand -hex 8` as fallback). It is a random identifier, not a hash of identifying information. It is stored at `~/.claude/.statusline-telemetry-id` with mode 600 (owner read/write only).

## API key handling

The narrator's optional Haiku layer uses `ANTHROPIC_API_KEY` from the environment. The key is:

- Never stored to disk by the plugin
- Never included in telemetry
- Only passed to the Anthropic SDK's client constructor

The VS Code extension reads OAuth credentials from `~/.claude/.credentials.json` (written by Claude Code itself, not by this plugin) to fetch rate limit data from Anthropic's API.

## Opt-out

Telemetry can be disabled completely:

```json
// ~/.claude/statusline-config.json
{ "telemetry": false }
```

Or via environment variable:

```bash
export STATUSLINE_DISABLE_TELEMETRY=1
```

When disabled, no pings are sent, ever. See [telemetry](../features/telemetry.md) for the full privacy model.

## Doctor report privacy

Doctor diagnostic reports (sent only on check failure with `full` privacy) are sanitized before upload and auto-delete after 30 days. The diagnostic code is a one-way hash of hostname + username, stable across runs but not reversible to identify the user.

## External network calls

| Call | When | Destination |
|------|------|-------------|
| Schedule fetch | Every 3 hours | `raw.githubusercontent.com` (GitHub raw) |
| Telemetry ping | Daily / on events | `statusline-telemetry.nadavf.workers.dev` |
| Haiku API | Every 5 prompts or 15 min | `api.anthropic.com` (only if API key set) |
| Rate limit API (VS Code) | Every 30 seconds | Anthropic OAuth API (only if credentials available) |

All network calls fail silently. No call blocks the statusline or narrator.
