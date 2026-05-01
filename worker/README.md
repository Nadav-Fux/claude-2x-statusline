# statusline-telemetry worker

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
