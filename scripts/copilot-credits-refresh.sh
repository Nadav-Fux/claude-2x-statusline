#!/usr/bin/env bash
# Optional cron wrapper for GitHub Copilot usage refresh.
#
# The first-class implementation lives in lib/usage_providers.py:
# refresh_copilot_cache(config). This script exists only for users who still
# want an explicit cron/background command; the statusline itself refreshes via
# Python stale-while-revalidate and no longer depends on this file.
#
# Env overrides are kept for compatibility:
#   COPILOT_MODE         individual | org
#   COPILOT_ORG          org slug for org mode
#   COPILOT_CREDIT_CAP   monthly cap for org mode, optional fallback for individual
#   COPILOT_CREDIT_POOL  optional display pool
#   COPILOT_SKUS         comma-separated SKU substrings
#   COPILOT_SKU          single SKU substring (legacy)
#   STATUSLINE_CONFIG    config path (default: ~/.claude/statusline-config.json)
#   STATUSLINE_LIB_DIR   lib path (default: repo ../lib, then installed lib)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_LIB_DIR="$(cd "$SCRIPT_DIR/../lib" 2>/dev/null && pwd || true)"
INSTALLED_LIB_DIR="$HOME/.claude/cc-2x-statusline/lib"
LIB_DIR="${STATUSLINE_LIB_DIR:-${REPO_LIB_DIR:-$INSTALLED_LIB_DIR}}"
CONFIG="${STATUSLINE_CONFIG:-$HOME/.claude/statusline-config.json}"

STATUSLINE_LIB_DIR="$LIB_DIR" STATUSLINE_CONFIG="$CONFIG" python3 - <<'PY'
import json
import os
import sys

sys.path.insert(0, os.environ["STATUSLINE_LIB_DIR"])
from usage_providers import refresh_copilot_cache  # noqa: E402

config_path = os.environ.get("STATUSLINE_CONFIG") or os.path.expanduser("~/.claude/statusline-config.json")
try:
    with open(os.path.expanduser(config_path), encoding="utf-8") as fh:
        config = json.load(fh)
except Exception:
    config = {}

external = config.get("external_providers") if isinstance(config, dict) else None
external = external if isinstance(external, dict) else {}
copilot = dict(external.get("copilot") or {})

overrides = {
    "mode": os.environ.get("COPILOT_MODE"),
    "org": os.environ.get("COPILOT_ORG"),
    "cap": os.environ.get("COPILOT_CREDIT_CAP"),
    "pool": os.environ.get("COPILOT_CREDIT_POOL"),
}
for key, value in overrides.items():
    if value not in (None, ""):
        copilot[key] = value

if os.environ.get("COPILOT_SKUS"):
    copilot["skus"] = [item.strip() for item in os.environ["COPILOT_SKUS"].split(",") if item.strip()]
elif os.environ.get("COPILOT_SKU"):
    copilot["skus"] = [os.environ["COPILOT_SKU"]]

ok = refresh_copilot_cache(copilot)
raise SystemExit(0 if ok else 1)
PY
