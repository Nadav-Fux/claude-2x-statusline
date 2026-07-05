#!/usr/bin/env bash
# copilot-credits-refresh.sh — GitHub Copilot AI-credit usage refresher (template).
#
# Fetches Copilot AI-credit usage from the GitHub billing API and writes a
# statusline cache file (~/.claude/statusline-usage-copilot.json). Safe to run
# from cron or in the background: it NEVER clobbers the cache on API/network
# failure (stale-while-revalidate), so the statusline keeps showing the last
# good numbers.
#
# This is the ORG-POOL mode (a whole org's shared Copilot credit pool, with an
# optional per-user self-cap). It requires an org name and org-billing scope on
# the authenticated `gh` account. A proper INDIVIDUAL mode (per-user premium
# requests via /users/{login}/settings/billing/usage) plus onboarding-driven
# mode selection lands in Phase 3 — see docs/plans/2026-07-05-provider-selection-oss.md.
#
# Configuration (all via env, or the copilot block in ~/.claude/statusline-config.json):
#   COPILOT_ORG          (required) GitHub org whose Copilot billing to query.
#   COPILOT_CREDIT_CAP   (optional) self-imposed ceiling; "remaining" counts down from here.
#   COPILOT_CREDIT_POOL  (optional) org's full included credit pool (used as the cap when CAP is unset).
#   COPILOT_SKU          (optional) billing SKU to sum; defaults to "Copilot AI Credits".
#
#   used      = credits consumed this billing month (org pool, all users)
#   cap       = COPILOT_CREDIT_CAP, or COPILOT_CREDIT_POOL, or 0 (unknown)
#   remaining = cap - used   (only when a cap is known)
#
# Output: ~/.claude/statusline-usage-copilot.json
set -euo pipefail

CONFIG="$HOME/.claude/statusline-config.json"
CACHE="$HOME/.claude/statusline-usage-copilot.json"

# Resolve a copilot config value: env var wins, else read
# external_providers.copilot.<key> from the statusline config, else empty.
copilot_cfg() {
    local env_val="$1" cfg_key="$2"
    if [ -n "$env_val" ]; then
        printf '%s' "$env_val"
        return 0
    fi
    [ -f "$CONFIG" ] || return 0
    CFG="$CONFIG" KEY="$cfg_key" python3 - <<'PY' 2>/dev/null || true
import json, os
try:
    with open(os.environ["CFG"]) as f:
        cfg = json.load(f)
    val = ((cfg.get("external_providers") or {}).get("copilot") or {}).get(os.environ["KEY"])
    if val is not None:
        print(val)
except Exception:
    pass
PY
}

ORG="$(copilot_cfg "${COPILOT_ORG:-}" org)"
CAP="$(copilot_cfg "${COPILOT_CREDIT_CAP:-}" cap)"
POOL="$(copilot_cfg "${COPILOT_CREDIT_POOL:-}" pool)"
SKU="${COPILOT_SKU:-Copilot AI Credits}"

if [ -z "$ORG" ]; then
    cat >&2 <<'USAGE'
copilot-credits-refresh.sh: no org configured.
Set COPILOT_ORG (or external_providers.copilot.org in statusline-config.json)
to the GitHub org whose Copilot billing you want to track, e.g.:
    COPILOT_ORG=my-org bash scripts/copilot-credits-refresh.sh
Requires `gh auth login` with org-billing read scope.
USAGE
    exit 0   # graceful: never clobber an existing cache
fi

Y="$(date +%Y)"; M="$(date +%-m)"

raw="$(gh api "/organizations/$ORG/settings/billing/usage?year=$Y&month=$M" 2>/dev/null || true)"
[ -z "$raw" ] && exit 0   # API/network failure → keep last good cache

RAW="$raw" CAP="$CAP" POOL="$POOL" SKU="$SKU" CACHE="$CACHE" python3 - <<'PY'
import json, os, sys, time, datetime
try:
    d = json.loads(os.environ["RAW"])
except Exception:
    sys.exit(0)  # unparseable response → keep last good cache

def _int(name):
    try:
        return int(float(os.environ.get(name) or 0))
    except Exception:
        return 0

items = d.get("usageItems", [])
sku = os.environ["SKU"]
used = sum(i.get("quantity", 0) for i in items if i.get("sku") == sku)
cap = _int("CAP") or _int("POOL")   # CAP wins; else the full pool; else 0 (unknown)
pool = _int("POOL")
cache = os.environ["CACHE"]

now = datetime.datetime.now(datetime.timezone.utc)
nm = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
nm = nm.replace(year=now.year + 1, month=1) if now.month == 12 else nm.replace(month=now.month + 1)
reset_epoch = int(nm.timestamp())

if cap > 0:
    remaining = max(0.0, cap - used)
    pct_used = min(100, round(used / cap * 100))
    label = f"{remaining:.0f} left"
else:
    remaining = None
    pct_used = 0
    label = f"{used:.0f} used"

rec = {
    "provider": "copilot",
    "label": "Copilot",
    "available": True,
    "display": "bars",
    "five_hour": {"label": label, "used_pct": pct_used, "resets_at": reset_epoch},
    "plan": "business",
    "source": "gh-billing",
    "used": round(used, 2),
    "cap": cap,
    "pool": pool,
    "remaining": None if remaining is None else round(remaining, 2),
}
with open(cache, "w") as f:
    json.dump({"cached_at": time.time(), "record": rec}, f)
print(f"used={used:.2f} cap={cap} remaining={'-' if remaining is None else f'{remaining:.0f}'} pct_used={pct_used} (pool={pool})")
PY
