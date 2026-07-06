# statusline-telemetry worker

## Self-hosting / forks

`wrangler.toml` ships with `account_id` and the `TELEMETRY` KV namespace `id`
set to `REPLACE_ME` placeholders — the values above are the maintainer's own
Cloudflare account and are not usable by forks. To self-host your own
telemetry backend:

1. `wrangler kv:namespace create TELEMETRY` and put the returned id into
   `id` under `[[kv_namespaces]]`.
2. Put your own Cloudflare account id (from `wrangler whoami`) into
   `account_id`.
3. Point your fork's client-side `TELEMETRY_URL` (installer + engines +
   VS Code extension) at your deployed worker URL.

Telemetry itself is opt-in on the client side by default — see the main
README's "Telemetry (opt-in)" section.

## Deploy
```bash
cd worker
wrangler deploy
```

## Set admin auth token
```bash
wrangler kv key put --binding=TELEMETRY _auth_token "your-secret-here"
```

## Endpoints

- `POST /ping` — anonymous telemetry (install/heartbeat/doctor summary)
- `GET /stats?token=...` — aggregated stats (auth required)
- `GET /failures?token=...&days=7` — install/update/doctor failure rollups
- `POST /doctor/submit` — rich doctor diagnostics (anonymous, 30-day TTL)
- `GET /doctor/<code>?token=...` — fetch reports for a machine code (auth required)
- `GET /doctor/<code>/latest?token=...` — fetch just the most recent report as plain text (auth required)

## Local dev
```bash
wrangler dev
```

## Privacy
All submissions are sanitized client-side before upload:
- Home paths → `~/`
- Hostnames → `<host>`
- Usernames → `<user>`

No conversation data, file contents, or API keys are accepted.
Reports auto-delete after 30 days.
