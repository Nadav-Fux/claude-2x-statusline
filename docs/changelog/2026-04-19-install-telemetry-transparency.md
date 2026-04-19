# Install telemetry — what we send, why, and how to opt out

**Date:** 2026-04-19

> This post exists because you deserve to know exactly what runs on your machine. No vague promises, no "we take your privacy seriously" boilerplate. Read this, then decide.

---

## English

### What we collect

One event fires per install (ever), plus a daily heartbeat. Here is the **complete** JSON payload — nothing is omitted:

```json
{
  "id": "a3f9c2b7e10d5a84",
  "engine": "python",
  "tier": "standard",
  "os": "linux",
  "version": "1.4.2",
  "event": "install"
}
```

| Field     | Value                                         | Notes                                     |
|-----------|-----------------------------------------------|-------------------------------------------|
| `id`      | 16 hex chars                                  | SHA-256 of `hostname:username`, truncated. Irreversible — cannot be reversed to identify you. |
| `engine`  | `python` / `node` / `bash` / `installer`      | Which engine ran the ping                 |
| `tier`    | `minimal` / `standard` / `full`               | Your configured statusline tier           |
| `os`      | `linux` / `macos` / `windows`                 | Detected OS                               |
| `version` | semver string                                 | Statusline version from `package.json`    |
| `event`   | `install` / `heartbeat`                       | Install fires once ever; heartbeat daily  |

That's it. Seven fields. No session IDs from Claude Code. No file contents. No conversation data. No real username or hostname. No IP addresses retained by us (Cloudflare's edge may log your IP transiently, like any HTTP server, but we don't access or store those logs).

### What we do NOT collect

To be explicit:

- File contents or paths
- Conversation history or prompts
- API keys (yours or ours)
- Claude Code session IDs
- Real identity (name, email, hostname, username)
- Error logs or stack traces
- Any user-generated content whatsoever

### Event details

#### `install` event

- Fired **once per machine, ever** — not once per install.
- Written by `install.sh` at install time.
- Also fired on **first engine run** if `install.sh` was skipped (e.g., manual clone). This is a retroactive backfill so machines that never ran the installer are still counted.
- The `id` is stored in `~/.claude/statusline-telemetry-id` after the first ping, so subsequent events reuse the same identifier.

#### `heartbeat` event

- Fired **once per day** from the engine.
- Gated by a timestamp in `~/.claude/statusline-state.json`. If the last heartbeat was < 23 hours ago, it's skipped.
- The heartbeat is what powers the DAU/WAU numbers on the public stats page.

### Storage

Endpoint: `https://statusline-telemetry.nadavf.workers.dev/ping`

Data lands in **Cloudflare KV**:

| Key pattern          | TTL      | Purpose                             |
|----------------------|----------|-------------------------------------|
| `install:<id>`       | No TTL   | Permanent install record            |
| `dau:<date>:<id>`    | 90 days  | Daily active user marker            |

Stats (DAU, WAU, total installs, engine breakdown) are computed at query time from these keys — they are **never exported raw**. No analytics platform. No third-party data sharing.

### Public stats page

Anyone can see the aggregate stats. No authentication:

```
GET https://statusline-telemetry.nadavf.workers.dev/stats
```

Example response:

```
claude-2x-statusline telemetry stats
─────────────────────────────────────
Total installs:     342
Today (DAU):         87
This week (WAU):    214

Engine breakdown:
  python:           201 (58.8%)
  node:              89 (26.0%)
  bash:              41 (12.0%)
  installer:         11  (3.2%)

Tier breakdown:
  standard:         198 (57.9%)
  full:              94 (27.5%)
  minimal:           50 (14.6%)

OS breakdown:
  linux:            189 (55.3%)
  macos:            104 (30.4%)
  windows:           49 (14.3%)
─────────────────────────────────────
```

### Why we collect it

Two reasons:

1. **Know if anyone uses this.** DAU/WAU tells us whether the project is alive or stale. Without it, we're guessing.
2. **Know which engines to support.** If bash usage drops to 2%, we stop spending time on the bash engine.

That's it. No advertising. No resale. No "insights." No venture-backed analytics platform sitting between you and us.

### How to opt out

Add `"telemetry": false` to your config:

```json
// ~/.claude/statusline-config.json
{
  "telemetry": false
}
```

After this, **no ping is ever sent**. The check is:

```python
config = load_config()
if not config.get("telemetry", True):
    return  # exit before any network call
```

This is checked before the HTTP call is constructed. There is no "phone home to say you opted out" — the flag is purely local.

This has been tested: with `telemetry: false`, Wireshark shows zero outbound connections to the telemetry endpoint.

### Fallback chain

The install ping tries three tools in order:

```bash
curl -s -X POST "$ENDPOINT" -d "$PAYLOAD" -H "Content-Type: application/json"
# or if curl missing:
wget -q --post-data="$PAYLOAD" --header="Content-Type: application/json" "$ENDPOINT"
# or if wget missing:
python -c "import urllib.request, json; ..."
```

If all three are missing (unusual but possible on minimal Linux containers), the ping is silently skipped. The retroactive `install` event from the engine's first run will cover these machines when the engine does run.

### Tradeoffs acknowledged

- The hash `hostname:username` is deterministic — the same machine always produces the same ID. This is intentional (deduplication), but it means the ID is stable across time. If you share your config with someone, they'll have your ID. Don't share your `statusline-telemetry-id` file.
- Daily heartbeats mean we can infer rough usage patterns per ID (e.g., "this machine used it 5 days this week"). We don't act on this, but the data is technically there for 90 days.

---

<div dir="rtl">

## עברית

### מה אנחנו אוספים — ללא קישוטים

פוסט זה קיים כי מגיע לך לדעת בדיוק מה רץ על המכונה שלך.

**הפאיילוד המלא** (שום דבר לא הושמט):

```json
{
  "id": "a3f9c2b7e10d5a84",
  "engine": "python",
  "tier": "standard",
  "os": "linux",
  "version": "1.4.2",
  "event": "install"
}
```

שבעה שדות. ה-`id` הוא SHA-256 של `hostname:username` — 16 תווים הקסדצימלים, לא הפיך. אי-אפשר לחלץ ממנו שם משתמש או hostname.

**מה לא נאסף**: תוכן קבצים, היסטוריית שיחות, מפתחות API, session IDs מ-Claude Code, זהות אמיתית, לוגי שגיאות — כלום.

### אירועים

- **`install`**: פעם אחת לכל מכונה, לנצח. אם דילגת על `install.sh` — נשלח בריצה הראשונה של ה-engine (retroactive backfill).
- **`heartbeat`**: פעם ביום. זה מה שמאכיל את מספרי ה-DAU/WAU בעמוד הסטטיסטיקות הציבורי.

### אחסון

**Cloudflare KV**: `install:<id>` = ללא TTL. `dau:<date>:<id>` = 90 יום TTL. סטטיסטיקות מחושבות בזמן שאילתה — לא מיוצאות raw. אין פלטפורמת analytics, אין שיתוף עם צד שלישי.

### למה זה קיים

1. לדעת אם מישהו משתמש בפרויקט.
2. לדעת איזה engines לתמוך בהם.

זהו. אין פרסום, אין מכירה, אין "insights".

### איך לצאת

```json
{ "telemetry": false }
```

בתוך `~/.claude/statusline-config.json`. הנקודה הזו נבדקת לפני כל קריאת רשת — אין "ping של opt-out". נבדק עם Wireshark: אפס חיבורים יוצאים לאחר הגדרת הדגל.

### tradeoffs שצריך לדעת

ה-hash יציב לאורך זמן ובין סשנים — אותה מכונה תמיד מייצרת אותו ID. אל תשתף את קובץ `statusline-telemetry-id`. ה-heartbeat מאפשר לאמוד בגסות כמה ימים בשבוע המכונה פעילה — זה קיים ב-KV למשך 90 יום, אפילו שאנחנו לא פועלים על פיו.

</div>
