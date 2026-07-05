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
