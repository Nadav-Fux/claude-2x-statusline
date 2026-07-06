"""Provider onboarding — pure selection logic (no interactive prompts).

Phase 1 scope: read-only auth detection + an atomic config writer that records a
provider selection. The interactive wizard (AskUserQuestion / install.sh
prompts) lives in the slash command + skill and calls into this module; the
per-provider guided auth flow lands in Phase 2.

Nothing here performs network I/O beyond what the existing usage readers already
do with their own caches, and every detection check is individually guarded so a
single failing probe can never raise out of ``detect_all_auth``.
"""
import json
import os
import shutil
import subprocess
import time
from pathlib import Path


# Canonical external-provider order (claude is the implicit rate-limit line, not
# an external row). Kept in sync with engines/python-engine.py
# _EXTERNAL_PROVIDER_ORDER.
_EXTERNAL_PROVIDER_ORDER = ("codex", "glm", "droid", "antigravity", "copilot")
_ALL_PROVIDERS = ("claude",) + _EXTERNAL_PROVIDER_ORDER


def _load_usage_providers():
    """Import the usage_providers module regardless of how onboarding.py was
    loaded (as ``lib.onboarding`` in tests, or with ``lib/`` directly on
    sys.path via the skill one-liner). Returns the module or None."""
    try:
        from . import usage_providers as up  # package-style import
        return up
    except Exception:
        pass
    try:
        import usage_providers as up  # lib/ on sys.path
        return up
    except Exception:
        return None


def _load_secrets():
    """Import the secret-store module (lib/secret_store.py) regardless of import
    style. Named secret_store (not secrets) so it can never shadow the stdlib: a module
    without ``secret_store`` is treated as absent. Returns the module or None."""
    try:
        from . import secret_store as _secrets  # package-style import
        if hasattr(_secrets, "secret_store"):
            return _secrets
    except Exception:
        pass
    try:
        import secret_store as _secrets  # lib/ on sys.path
        if hasattr(_secrets, "secret_store"):
            return _secrets
    except Exception:
        pass
    return None


# ── Detection (read-only, never raises) ──────────────────────────────────────

def _detect_claude():
    # Import-free heuristic; the engine owns the real token resolution. Claude is
    # always implicit, so "unknown" here is harmless.
    try:
        if os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
            return "ok"
        if (Path.home() / ".claude" / ".credentials.json").exists():
            return "ok"
    except Exception:
        return "unknown"
    return "unknown"


def _detect_codex(up):
    try:
        return "ok" if up is not None and up._newest_codex_rollout() is not None else "missing"
    except Exception:
        return "unknown"


def _detect_glm(up, glm_config):
    try:
        return "ok" if up is not None and up._glm_key(glm_config) else "missing"
    except Exception:
        return "unknown"


def _detect_droid(up):
    try:
        if up is None:
            return "unknown"
        for candidate in up._droid_settings_candidates():
            try:
                if candidate.exists():
                    return "ok"
            except Exception:
                continue
        return "missing"
    except Exception:
        return "unknown"


def _detect_antigravity():
    try:
        return "ok" if shutil.which("antigravity-usage") else "missing"
    except Exception:
        return "unknown"


def _detect_copilot():
    try:
        cache = Path.home() / ".claude" / "statusline-usage-copilot.json"
        if cache.exists():
            return "ok"
    except Exception:
        return "unknown"
    try:
        proc = subprocess.run(
            ["gh", "auth", "status"],
            capture_output=True,
            timeout=2,
        )
        return "ok" if proc.returncode == 0 else "missing"
    except Exception:
        return "unknown"


def detect_all_auth(config):
    """Return ``{provider: status}`` for every known provider.

    ``status`` is one of ``ok`` (detected), ``missing`` (reader found no
    credential/data), or ``unknown`` (the probe itself errored). Purely
    read-only — it reuses the existing usage-provider readers and their caches,
    and every check is individually try/excepted so the whole call never raises.
    """
    config = config if isinstance(config, dict) else {}
    external = config.get("external_providers")
    external = external if isinstance(external, dict) else {}
    glm_config = external.get("glm")
    glm_config = glm_config if isinstance(glm_config, dict) else {}

    up = _load_usage_providers()
    return {
        "claude": _detect_claude(),
        "codex": _detect_codex(up),
        "glm": _detect_glm(up, glm_config),
        "droid": _detect_droid(up),
        "antigravity": _detect_antigravity(),
        "copilot": _detect_copilot(),
    }


# ── Selection writer (atomic) ─────────────────────────────────────────────────

def _read_config(config_path):
    try:
        data = json.loads(Path(config_path).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _atomic_write_config(config_path, config):
    path = Path(config_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(str(tmp), str(path))
    try:
        os.chmod(path, 0o600)
    except Exception:
        pass


def _normalize_selected(selected):
    norm = []
    for provider in selected or []:
        if provider in _ALL_PROVIDERS and provider not in norm:
            norm.append(provider)
    # Claude is always implicit — it owns the rate-limit line — so keep it first.
    if "claude" not in norm:
        norm.insert(0, "claude")
    return norm


def apply_selection(config_path, selected):
    """Persist a provider selection, atomically, and return the new config dict.

    Writes the ``providers`` block (schema_version 1, ordered ``selected``) and:
      * mirrors the selection into ``external_providers.<p>.enabled`` for every
        known external provider, plus ``external_providers.enabled = any external
        selected``. This mirror is what keeps the Node and Bash engines working
        WITHOUT changes — they read ``external_providers`` today and have no
        knowledge of ``providers.selected``. (Teaching them to read the block
        directly is a later phase; until then, never drop the mirror.)
      * auto-sets ``tier``: ``multi-cli`` when 2+ providers are selected;
        otherwise the existing tier is kept, except a collapse to claude-only
        while the tier was ``multi-cli`` falls back to ``full``.

    All other config keys are preserved.
    """
    norm = _normalize_selected(selected)
    config = _read_config(config_path)

    config["providers"] = {"schema_version": 1, "selected": list(norm)}

    externals_selected = [p for p in norm if p != "claude"]
    external = config.get("external_providers")
    external = dict(external) if isinstance(external, dict) else {}
    for provider in _EXTERNAL_PROVIDER_ORDER:
        provider_config = external.get(provider)
        provider_config = dict(provider_config) if isinstance(provider_config, dict) else {}
        provider_config["enabled"] = provider in externals_selected
        external[provider] = provider_config
    external["enabled"] = bool(externals_selected)
    config["external_providers"] = external

    if len(norm) >= 2:
        config["tier"] = "multi-cli"
    elif config.get("tier") == "multi-cli":
        # Selection collapsed to claude-only; drop out of the cockpit tier.
        config["tier"] = "full"
    # else: keep the existing tier untouched.

    _atomic_write_config(config_path, config)
    return config


# ── GLM key: validate → keychain → blank plaintext (Phase 2) ──────────────────

_GLM_SERVICE = "claude-statusline-glm"
_GLM_ACCOUNT = "glm"


def _glm_config_from(config):
    external = config.get("external_providers") if isinstance(config, dict) else None
    external = external if isinstance(external, dict) else {}
    glm = external.get("glm")
    return glm if isinstance(glm, dict) else {}


def store_glm_key(config_path, key):
    """Validate a z.ai / GLM API key, persist it to the OS secret store, and
    blank any plaintext ``external_providers.glm.api_key`` left in the config.

    Returns "" on success, or a short human-readable error string on failure —
    in which case NOTHING is stored and the config file is left untouched.

    Security: the key is never echoed, logged, or written anywhere but the
    secret store; every error string is redaction-safe (never contains key
    material), and exception bodies never interpolate the key.
    """
    key = str(key or "").strip()
    if not key:
        return "No key provided."

    up = _load_usage_providers()
    if up is None:
        return "Internal error: GLM reader unavailable."

    config = _read_config(config_path)
    glm_config = _glm_config_from(config)

    # 1. Validate BEFORE persisting: the key must fetch a parseable quota record.
    try:
        response = up._fetch_glm_response(glm_config, key)
        record = up.parse_glm_quota_response(response)
    except Exception:
        return "Could not reach the GLM quota endpoint (check the key or your network)."
    if not (isinstance(record, dict) and record.get("available")):
        return "The GLM key was rejected (endpoint returned no quota)."

    # 2. Persist to the secret store (keychain / 0600 file fallback).
    secrets = _load_secrets()
    if secrets is None:
        return "Secret store unavailable; key not saved."
    if not secrets.secret_store(_GLM_SERVICE, _GLM_ACCOUNT, key):
        return "Could not write the key to the OS secret store."

    # 3. Blank any plaintext api_key in the config file (atomic rewrite). The key
    #    now lives only in the secret store; a lingering plaintext copy would be
    #    a downgrade. Failing to blank is non-fatal — the key is safely stored.
    try:
        external = config.get("external_providers")
        if isinstance(external, dict) and isinstance(external.get("glm"), dict):
            if external["glm"].get("api_key"):
                external = dict(external)
                glm = dict(external["glm"])
                glm["api_key"] = ""
                external["glm"] = glm
                config["external_providers"] = external
                _atomic_write_config(config_path, config)
    except Exception:
        return ""
    return ""


# ── validate_provider — bounded auth probes (onboarding / doctor only) ────────
#
# NEVER call these on the render path: they may spawn subprocesses and make
# network calls. Each is bounded (<=5s) and swallows every error into "unknown".
# Results: "ok" | "unauth" | "missing" | "unknown".

_CLAUDE_CACHE_FRESH_TTL = 3600
_COPILOT_CACHE_FRESH_TTL = 15 * 60
_CODEX_MAX_AGE = 7 * 24 * 3600


def _validate_claude():
    try:
        cache = Path.home() / ".claude" / "statusline-usage-cache.json"
        try:
            if time.time() - cache.stat().st_mtime < _CLAUDE_CACHE_FRESH_TTL:
                return "ok"
        except Exception:
            pass
        if os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
            return "ok"
        if (Path.home() / ".claude" / ".credentials.json").exists():
            return "ok"
        return "unauth"
    except Exception:
        return "unknown"


def _validate_codex(up):
    try:
        if up is None:
            return "unknown"
        rollout = up._newest_codex_rollout()
        if rollout is None:
            return "missing"
        try:
            if time.time() - rollout.stat().st_mtime > _CODEX_MAX_AGE:
                return "unauth"
        except Exception:
            pass
        try:
            with rollout.open(encoding="utf-8") as fh:
                for line in fh:
                    if '"token_count"' in line:
                        return "ok"
        except Exception:
            return "unknown"
        return "unauth"
    except Exception:
        return "unknown"


def _validate_glm(up, config):
    try:
        if up is None:
            return "unknown"
        glm_config = _glm_config_from(config)
        key = up._glm_key(glm_config)
        if not key:
            return "missing"
        try:
            record = up.parse_glm_quota_response(up._fetch_glm_response(glm_config, key))
        except Exception:
            return "unauth"
        return "ok" if isinstance(record, dict) and record.get("available") else "unauth"
    except Exception:
        return "unknown"


def _validate_antigravity(up, config):
    try:
        external = config.get("external_providers") if isinstance(config, dict) else {}
        external = external if isinstance(external, dict) else {}
        agy = external.get("antigravity") if isinstance(external.get("antigravity"), dict) else {}
        bin_path = str(agy.get("bin") or "antigravity-usage")
        if shutil.which(bin_path) is None and "/" not in bin_path and "\\" not in bin_path:
            return "missing"
        try:
            proc = subprocess.run(
                [bin_path, "quota", "--json", "--method", "auto"],
                capture_output=True, text=True, timeout=5,
            )
            snapshot = json.loads(proc.stdout or "")
        except Exception:
            return "unauth"
        metrics = up._map_antigravity_snapshot(snapshot) if up is not None else None
        return "ok" if metrics else "unauth"
    except Exception:
        return "unknown"


def _copilot_config_from(config):
    if not isinstance(config, dict):
        return {}
    external = config.get("external_providers")
    if isinstance(external, dict) and isinstance(external.get("copilot"), dict):
        return external.get("copilot") or {}
    return config


def _positive_number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return number == number and number not in (float("inf"), float("-inf")) and number > 0


def _validate_copilot(config):
    try:
        copilot = _copilot_config_from(config)
        mode = str(copilot.get("mode") or "individual").strip().lower()
        if mode == "org" and (not str(copilot.get("org") or "").strip() or not _positive_number(copilot.get("cap"))):
            return "missing"
        cache = Path.home() / ".claude" / "statusline-usage-copilot.json"
        try:
            if time.time() - cache.stat().st_mtime < _COPILOT_CACHE_FRESH_TTL:
                return "ok"
        except Exception:
            pass
        if shutil.which("gh") is None:
            return "missing"
        try:
            proc = subprocess.run(["gh", "auth", "status"], capture_output=True, timeout=5)
        except Exception:
            return "unknown"
        return "ok" if proc.returncode == 0 else "unauth"
    except Exception:
        return "unknown"


def _validate_droid(up):
    try:
        if up is None:
            return "unknown"
        record = up.get_droid_usage({})
        return "ok" if isinstance(record, dict) and record.get("available") else "missing"
    except Exception:
        return "unknown"


def validate_provider(provider, config):
    """Bounded (<=5s) auth probe for one provider. See module note above — this
    is for onboarding / doctor ONLY and must never run on the render path."""
    config = config if isinstance(config, dict) else {}
    try:
        if provider == "claude":
            return _validate_claude()
        up = _load_usage_providers()
        if provider == "codex":
            return _validate_codex(up)
        if provider == "glm":
            return _validate_glm(up, config)
        if provider == "antigravity":
            return _validate_antigravity(up, config)
        if provider == "copilot":
            return _validate_copilot(config)
        if provider == "droid":
            return _validate_droid(up)
    except Exception:
        return "unknown"
    return "unknown"
