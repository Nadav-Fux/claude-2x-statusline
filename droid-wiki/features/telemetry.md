# Telemetry

## Purpose

Anonymous usage tracking that tells the maintainer how many people use the plugin, which engines and tiers are popular, and whether installs or updates are failing. All data is sanitized client-side before transmission, and the system is fully transparent with a public stats endpoint.

## What gets sent

| Event | When | TTL |
|-------|------|-----|
| `install` | Once per machine (first install or first run) | Permanent |
| `heartbeat` | Once per day | 90 days |
| `doctor` | On every doctor run (if telemetry enabled) | 90 days |
| `doctor/submit` | When a check fails and privacy is `full` | 30 days |

## Payload

The basic ping payload:

```json
{
  "id": "a1b2c3d4e5f6a7b8",
  "v": "2.2.0",
  "engine": "python",
  "tier": "full",
  "os": "linux",
  "event": "install"
}
```

The `id` is a 16-character hex string generated once per machine via `secrets.token_hex(8)`. It is stored at `~/.claude/.statusline-telemetry-id`. No conversation data, file contents, API keys, or real identity is sent.

For `doctor/submit` events with `full` privacy, a sanitized diagnostic report is included. Sanitization replaces:

- Home directory paths with `~/`
- Usernames with `<user>`
- Hostnames with `<host>`

## Privacy levels

Configured in `~/.claude/statusline-config.json`:

| Level | Config | What is sent |
|-------|--------|-------------|
| Full (default) | `{ "tier": "full" }` | Summary + sanitized report on failure |
| Minimal | `{ "diagnostics": "minimal" }` | Summary only |
| Off | `{ "telemetry": false }` | Nothing, ever |

The environment variable `STATUSLINE_DISABLE_TELEMETRY=1` also disables all telemetry, including doctor reports.

## Endpoint

All pings go to `https://statusline-telemetry.nadavf.workers.dev/ping`. The Cloudflare Worker stores data in KV with automatic TTL expiration. See [telemetry worker](../apps/telemetry-worker.md) for the server-side implementation.

## Transparency

Live statistics are publicly viewable at `https://statusline-telemetry.nadavf.workers.dev/stats`. This endpoint shows aggregated counts (installs, DAU, engine/tier/OS breakdown) with no individual machine data.

## Telemetry ID generation

The ID generation cascade in `engines/bash-engine.sh` tries these sources in order:

1. `python3 -c "import secrets; print(secrets.token_hex(8))"`
2. `python -c "import secrets; print(secrets.token_hex(8))"`
3. `openssl rand -hex 8`
4. `od -An -N8 -tx1 /dev/urandom`

The ID is validated as a 16-character hex string, written to `~/.claude/.statusline-telemetry-id` with mode 600, and reused on subsequent runs.

## Key source files

| File | Purpose |
|------|---------|
| `engines/bash-engine.sh` | Telemetry ID generation and heartbeat ping |
| `engines/python-engine.py` | Telemetry ping in Python engine |
| `engines/node-engine.js` | Telemetry ping in Node.js engine |
| `doctor/doctor.sh` | Doctor telemetry submission |
| `install.sh` | Install event ping |
| `worker/worker.js` | Cloudflare Worker receiving pings |
| `tests/test_install_ping.py` | Install ping tests |
| `tests/test_doctor_telemetry.py` | Doctor telemetry tests |

## Related pages

- [Doctor diagnostics](doctor.md) — What triggers doctor telemetry
- [Telemetry worker](../apps/telemetry-worker.md) — Server-side endpoint implementation
- [Security](../security.md) — Data sanitization and privacy model
