from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest

from lib import onboarding
from lib import usage_providers as providers

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _strip(s):
    return _ANSI.sub("", s)


_ROOT = Path(__file__).resolve().parent.parent
_ENGINE_PATH = _ROOT / "engines" / "python-engine.py"
_spec = importlib.util.spec_from_file_location("engine_onboarding", _ENGINE_PATH)
engine = importlib.util.module_from_spec(_spec)
try:
    _spec.loader.exec_module(engine)
    _IMPORT_OK = True
except Exception as _exc:  # pragma: no cover
    _IMPORT_OK = False
    _IMPORT_ERR = str(_exc)


def _require_engine():
    if not _IMPORT_OK:  # pragma: no cover
        pytest.skip(f"engine import failed: {_IMPORT_ERR}")


# ── migrate_providers ─────────────────────────────────────────────────────────

def test_migrate_absent_block_defaults_to_claude_only():
    _require_engine()
    config = {"tier": "standard"}
    engine.migrate_providers(config)
    assert config["providers"] == {"schema_version": 1, "selected": ["claude"]}


def test_migrate_respects_enabled_true_externals_in_canonical_order():
    _require_engine()
    config = {
        "external_providers": {
            "enabled": True,
            "codex": {"enabled": True},
            "glm": {"enabled": True},
            "droid": {"enabled": False},
            "antigravity": {"enabled": True},
            "copilot": {"enabled": False},
        }
    }
    engine.migrate_providers(config)
    assert config["providers"]["selected"] == ["claude", "codex", "glm", "antigravity"]


def test_migrate_ignores_top_level_enabled_and_uses_per_provider_flag():
    _require_engine()
    # external_providers.enabled is False, but codex is per-provider enabled.
    config = {"external_providers": {"enabled": False, "codex": {"enabled": True}}}
    engine.migrate_providers(config)
    assert config["providers"]["selected"] == ["claude", "codex"]


def test_migrate_is_idempotent_and_leaves_existing_block_untouched():
    _require_engine()
    config = {"providers": {"schema_version": 1, "selected": ["claude", "glm"]}}
    engine.migrate_providers(config)
    engine.migrate_providers(config)
    assert config["providers"] == {"schema_version": 1, "selected": ["claude", "glm"]}


def test_migrate_via_load_config_never_rewrites_the_file(tmp_path, monkeypatch):
    _require_engine()
    home = tmp_path / "home"
    claude = home / ".claude"
    claude.mkdir(parents=True, exist_ok=True)
    config_path = claude / "statusline-config.json"
    original = {"tier": "multi-cli", "external_providers": {"enabled": True, "codex": {"enabled": True}}}
    config_path.write_text(json.dumps(original), encoding="utf-8")
    before_bytes = config_path.read_bytes()

    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))

    loaded = engine.load_config()
    # In-memory config gained the derived selection ...
    assert loaded["providers"]["selected"] == ["claude", "codex"]
    # ... but the on-disk file is byte-for-byte unchanged (render path is read-only).
    assert config_path.read_bytes() == before_bytes
    assert "providers" not in json.loads(config_path.read_text(encoding="utf-8"))


# ── _selected_external_providers ──────────────────────────────────────────────

def test_selected_external_providers_respects_explicit_order():
    _require_engine()
    config = {"providers": {"schema_version": 1, "selected": ["claude", "glm", "codex"]}}
    assert engine._selected_external_providers(config) == ["glm", "codex"]


def test_selected_external_providers_strips_claude_and_unknown_names():
    _require_engine()
    config = {"providers": {"schema_version": 1, "selected": ["claude", "bogus", "antigravity"]}}
    assert engine._selected_external_providers(config) == ["antigravity"]


def test_selected_external_providers_legacy_fallback_when_block_absent():
    _require_engine()
    config = {
        "external_providers": {
            "enabled": True,
            "codex": {"enabled": True},
            "glm": {"enabled": False},
            "droid": {"enabled": True},
        }
    }
    assert engine._selected_external_providers(config) == ["codex", "droid"]


def test_selection_does_not_force_codex_glm_under_multi_cli(monkeypatch):
    _require_engine()
    captured = {}

    def fake_collect(config, only=None):
        captured["only"] = only
        return []

    monkeypatch.setattr(engine._usage_providers, "collect_external_usage", fake_collect)
    engine.build_external_usage_lines(
        {
            "config": {
                "tier": "multi-cli",
                "providers": {"schema_version": 1, "selected": ["claude", "antigravity"]},
                "external_providers": {"enabled": True},
            },
            "is_full": True,
            "is_multi_cli": True,
            "render_width": 0,
        }
    )
    # Selection is authoritative: codex/glm are NOT force-enabled.
    assert captured["only"] == ["antigravity"]


# ── collect_external_usage only= ──────────────────────────────────────────────

def test_collect_external_usage_only_fetches_exact_order(monkeypatch):
    calls = []

    def fake_get(provider, provider_config=None):
        calls.append(provider)
        return {"provider": provider, "available": True}

    monkeypatch.setattr(providers, "get_provider_usage", fake_get)
    config = {"external_providers": {"enabled": False}}  # enabled=False must be ignored
    records = providers.collect_external_usage(config, only=["glm", "codex", "antigravity"])
    assert [r["provider"] for r in records] == ["glm", "codex", "antigravity"]
    assert calls == ["glm", "codex", "antigravity"]


def test_collect_external_usage_only_drops_unknown_providers(monkeypatch):
    monkeypatch.setattr(providers, "get_provider_usage", lambda p, c=None: {"provider": p, "available": True})
    records = providers.collect_external_usage({}, only=["codex", "nope", "glm"])
    assert [r["provider"] for r in records] == ["codex", "glm"]


def test_collect_external_usage_default_is_backward_compatible(monkeypatch):
    monkeypatch.setattr(providers, "get_provider_usage", lambda p, c=None: {"provider": p, "available": True})
    config = {
        "external_providers": {
            "enabled": True,
            "codex": {"enabled": True},
            "glm": {"enabled": False},
            "antigravity": {"enabled": True},
        }
    }
    records = providers.collect_external_usage(config)
    assert [r["provider"] for r in records] == ["codex", "antigravity"]


def test_read_cached_external_usage_only_reads_exact_order(tmp_path, monkeypatch):
    import time as _time

    home = tmp_path / "home"
    claude = home / ".claude"
    claude.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    now = _time.time()
    (claude / "statusline-usage-codex.json").write_text(
        json.dumps({"cached_at": now, "record": {"provider": "codex", "available": True}}),
        encoding="utf-8",
    )
    (claude / "statusline-usage-antigravity.json").write_text(
        json.dumps({"cached_at": now, "record": {"provider": "antigravity", "available": True}}),
        encoding="utf-8",
    )
    records = providers.read_cached_external_usage({}, only=["antigravity", "codex"])
    assert [r["provider"] for r in records] == ["antigravity", "codex"]


# ── apply_selection ───────────────────────────────────────────────────────────

def test_apply_selection_writes_providers_block_and_mirror(tmp_path):
    config_path = tmp_path / "statusline-config.json"
    config_path.write_text(json.dumps({"tier": "standard", "mode": "full", "schedule_cache_hours": 3}), encoding="utf-8")

    result = onboarding.apply_selection(config_path, ["claude", "codex"])

    assert result["providers"] == {"schema_version": 1, "selected": ["claude", "codex"]}
    ext = result["external_providers"]
    assert ext["enabled"] is True
    assert ext["codex"]["enabled"] is True
    assert ext["glm"]["enabled"] is False
    assert ext["droid"]["enabled"] is False
    assert ext["antigravity"]["enabled"] is False
    assert ext["copilot"]["enabled"] is False
    # tier auto-set to multi-cli when 2+ providers are selected.
    assert result["tier"] == "multi-cli"
    # unrelated keys preserved byte-for-byte semantics.
    assert result["mode"] == "full"
    assert result["schedule_cache_hours"] == 3

    # persisted to disk identically.
    on_disk = json.loads(config_path.read_text(encoding="utf-8"))
    assert on_disk == result


def test_apply_selection_forces_claude_and_preserves_provider_subconfig(tmp_path):
    config_path = tmp_path / "statusline-config.json"
    config_path.write_text(
        json.dumps({"external_providers": {"glm": {"enabled": False, "base_url": "https://api.z.ai", "api_key": "secret"}}}),
        encoding="utf-8",
    )

    result = onboarding.apply_selection(config_path, ["glm"])

    # claude is implicit and forced to the front.
    assert result["providers"]["selected"] == ["claude", "glm"]
    # existing glm sub-config keys survive; only enabled flips on.
    assert result["external_providers"]["glm"]["base_url"] == "https://api.z.ai"
    assert result["external_providers"]["glm"]["api_key"] == "secret"
    assert result["external_providers"]["glm"]["enabled"] is True


def test_apply_selection_claude_only_from_multi_cli_falls_back_to_full(tmp_path):
    config_path = tmp_path / "statusline-config.json"
    config_path.write_text(json.dumps({"tier": "multi-cli"}), encoding="utf-8")

    result = onboarding.apply_selection(config_path, ["claude"])

    assert result["providers"]["selected"] == ["claude"]
    assert result["external_providers"]["enabled"] is False
    # Collapsed to claude-only while in multi-cli → drop to full.
    assert result["tier"] == "full"


def test_apply_selection_claude_only_keeps_existing_non_multi_cli_tier(tmp_path):
    config_path = tmp_path / "statusline-config.json"
    config_path.write_text(json.dumps({"tier": "standard"}), encoding="utf-8")

    result = onboarding.apply_selection(config_path, ["claude"])

    assert result["tier"] == "standard"


def test_apply_selection_is_atomic_no_tmp_left_behind(tmp_path):
    config_path = tmp_path / "statusline-config.json"
    config_path.write_text(json.dumps({"tier": "full"}), encoding="utf-8")

    onboarding.apply_selection(config_path, ["claude", "codex", "glm"])

    # tmp+replace: no stray temp files remain in the directory.
    leftovers = [p.name for p in tmp_path.iterdir() if p.name != "statusline-config.json"]
    assert leftovers == []


# ── detect_all_auth ───────────────────────────────────────────────────────────

def test_detect_all_auth_returns_status_for_every_provider_and_never_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    result = onboarding.detect_all_auth({"external_providers": {"glm": {}}})
    assert set(result.keys()) == {"claude", "codex", "glm", "droid", "antigravity", "copilot"}
    for status in result.values():
        assert status in {"ok", "missing", "unknown"}


def test_detect_all_auth_tolerates_garbage_config():
    # Non-dict config must not raise.
    assert isinstance(onboarding.detect_all_auth(None), dict)
    assert isinstance(onboarding.detect_all_auth(42), dict)


# ── _glm_key keychain-first ordering ──────────────────────────────────────────

def test_glm_key_prefers_keychain_over_env_and_config(monkeypatch):
    monkeypatch.setattr(providers, "_keychain_glm_key", lambda: "kc-key")
    monkeypatch.setenv("ZAI_API_KEY", "env-key")
    assert providers._glm_key({"api_key": "cfg-key"}) == "kc-key"


def test_glm_key_falls_through_to_env_when_keychain_empty(monkeypatch):
    monkeypatch.setattr(providers, "_keychain_glm_key", lambda: "")
    monkeypatch.setenv("ZAI_API_KEY", "env-key")
    assert providers._glm_key({"api_key": "cfg-key"}) == "env-key"


def test_glm_key_falls_through_to_config_when_keychain_and_env_empty(monkeypatch):
    monkeypatch.setattr(providers, "_keychain_glm_key", lambda: "")
    monkeypatch.delenv("ZAI_API_KEY", raising=False)
    monkeypatch.delenv("ZHIPU_API_KEY", raising=False)
    monkeypatch.setattr(providers, "_read_provider_env_key", lambda: "")
    assert providers._glm_key({"api_key": "cfg-key"}) == "cfg-key"


def test_keychain_glm_key_swallows_secret_store_errors(monkeypatch):
    # Even if the secret store raises, _keychain_glm_key returns "" (never raises)
    # so _glm_key can fall through the rest of the chain.
    from lib import secret_store as _secrets

    def boom(service, account):
        raise RuntimeError("no keychain")

    monkeypatch.setattr(_secrets, "secret_read", boom)
    assert providers._keychain_glm_key() == ""


# ── store_glm_key ─────────────────────────────────────────────────────────────

class _FakeSecrets:
    """In-memory stand-in for lib/secret_store with the same store/read surface."""

    def __init__(self, store=None):
        self.store = store if store is not None else {}

    def secret_store(self, service, account, value):
        self.store[(service, account)] = value
        return True

    def secret_read(self, service, account):
        return self.store.get((service, account), "")


def _raise(*a, **k):
    raise RuntimeError("unreachable")


def test_store_glm_key_validate_fail_stores_nothing_and_leaves_config(tmp_path, monkeypatch):
    config_path = tmp_path / "statusline-config.json"
    original = {"external_providers": {"glm": {"enabled": True, "api_key": "OLD-PLACEHOLDER"}}}
    config_path.write_text(json.dumps(original), encoding="utf-8")
    before = config_path.read_bytes()

    # Validation raises → the key is rejected.
    monkeypatch.setattr(providers, "_fetch_glm_response", _raise)
    store = {}
    monkeypatch.setattr(onboarding, "_load_secrets", lambda: _FakeSecrets(store))

    err = onboarding.store_glm_key(config_path, "BAD-PLACEHOLDER")
    assert err  # non-empty error string
    assert "BAD-PLACEHOLDER" not in err  # never echo the key
    assert store == {}  # nothing persisted
    assert config_path.read_bytes() == before  # config file untouched


def test_store_glm_key_rejects_unparseable_quota(tmp_path, monkeypatch):
    config_path = tmp_path / "statusline-config.json"
    config_path.write_text(json.dumps({"external_providers": {"glm": {}}}), encoding="utf-8")

    monkeypatch.setattr(providers, "_fetch_glm_response", lambda cfg, key: {"junk": 1})
    monkeypatch.setattr(providers, "parse_glm_quota_response", lambda resp, stale_seconds=None: {"available": False})
    store = {}
    monkeypatch.setattr(onboarding, "_load_secrets", lambda: _FakeSecrets(store))

    err = onboarding.store_glm_key(config_path, "BAD-PLACEHOLDER")
    assert err
    assert store == {}


def test_store_glm_key_success_stores_and_blanks_plaintext(tmp_path, monkeypatch):
    config_path = tmp_path / "statusline-config.json"
    config_path.write_text(
        json.dumps(
            {"external_providers": {"glm": {"enabled": True, "api_key": "OLD-PLACEHOLDER", "base_url": "https://api.z.ai"}}}
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(providers, "_fetch_glm_response", lambda cfg, key: {"ok": 1})
    monkeypatch.setattr(providers, "parse_glm_quota_response", lambda resp, stale_seconds=None: {"available": True})
    store = {}
    monkeypatch.setattr(onboarding, "_load_secrets", lambda: _FakeSecrets(store))

    err = onboarding.store_glm_key(config_path, "GOOD-PLACEHOLDER")
    assert err == ""
    # Stored only in the secret store.
    assert store == {("claude-statusline-glm", "glm"): "GOOD-PLACEHOLDER"}
    # Plaintext blanked in config, but sibling keys preserved.
    on_disk = json.loads(config_path.read_text(encoding="utf-8"))
    assert on_disk["external_providers"]["glm"]["api_key"] == ""
    assert on_disk["external_providers"]["glm"]["base_url"] == "https://api.z.ai"


def test_store_glm_key_empty_input_is_rejected(tmp_path):
    config_path = tmp_path / "statusline-config.json"
    config_path.write_text("{}", encoding="utf-8")
    assert onboarding.store_glm_key(config_path, "   ") != ""


# ── validate_provider (per-provider, mocked) ──────────────────────────────────

def test_validate_provider_unknown_name_returns_unknown():
    assert onboarding.validate_provider("bogus", {}) == "unknown"


def test_validate_claude_ok_when_cache_fresh(tmp_path, monkeypatch):
    (tmp_path / ".claude").mkdir(parents=True)
    (tmp_path / ".claude" / "statusline-usage-cache.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    assert onboarding.validate_provider("claude", {}) == "ok"


def test_validate_claude_unauth_without_cache_or_creds(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    assert onboarding.validate_provider("claude", {}) == "unauth"


def test_validate_codex_missing_without_rollout(monkeypatch):
    monkeypatch.setattr(providers, "_newest_codex_rollout", lambda: None)
    assert onboarding.validate_provider("codex", {}) == "missing"


def test_validate_codex_ok_with_recent_token_count(tmp_path, monkeypatch):
    rollout = tmp_path / "rollout-x.jsonl"
    rollout.write_text('{"payload":{"type":"token_count"}}\n', encoding="utf-8")
    monkeypatch.setattr(providers, "_newest_codex_rollout", lambda: rollout)
    assert onboarding.validate_provider("codex", {}) == "ok"


def test_validate_glm_ok(monkeypatch):
    monkeypatch.setattr(providers, "_glm_key", lambda cfg: "KEY-PLACEHOLDER")
    monkeypatch.setattr(providers, "_fetch_glm_response", lambda cfg, key: {"x": 1})
    monkeypatch.setattr(providers, "parse_glm_quota_response", lambda resp, stale_seconds=None: {"available": True})
    assert onboarding.validate_provider("glm", {}) == "ok"


def test_validate_glm_missing_without_key(monkeypatch):
    monkeypatch.setattr(providers, "_glm_key", lambda cfg: "")
    assert onboarding.validate_provider("glm", {}) == "missing"


def test_validate_glm_unauth_on_fetch_error(monkeypatch):
    monkeypatch.setattr(providers, "_glm_key", lambda cfg: "KEY-PLACEHOLDER")
    monkeypatch.setattr(providers, "_fetch_glm_response", _raise)
    assert onboarding.validate_provider("glm", {}) == "unauth"


def test_validate_antigravity_missing_without_binary(monkeypatch):
    monkeypatch.setattr(onboarding.shutil, "which", lambda name: None)
    assert onboarding.validate_provider("antigravity", {}) == "missing"


def test_validate_antigravity_ok(monkeypatch):
    monkeypatch.setattr(onboarding.shutil, "which", lambda name: "/usr/bin/antigravity-usage")

    class _P:
        stdout = '{"models": []}'

    monkeypatch.setattr(onboarding.subprocess, "run", lambda *a, **k: _P())
    monkeypatch.setattr(providers, "_map_antigravity_snapshot", lambda snap: [{"label": "Opus"}])
    assert onboarding.validate_provider("antigravity", {}) == "ok"


def test_validate_copilot_ok_when_cache_fresh(tmp_path, monkeypatch):
    (tmp_path / ".claude").mkdir(parents=True)
    (tmp_path / ".claude" / "statusline-usage-copilot.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    assert onboarding.validate_provider("copilot", {}) == "ok"


def test_validate_copilot_missing_when_org_config_incomplete_even_with_cache(tmp_path, monkeypatch):
    (tmp_path / ".claude").mkdir(parents=True)
    (tmp_path / ".claude" / "statusline-usage-copilot.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))

    config = {"external_providers": {"copilot": {"mode": "org", "org": "acme"}}}

    assert onboarding.validate_provider("copilot", config) == "missing"


def test_validate_copilot_missing_without_gh(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.setattr(onboarding.shutil, "which", lambda name: None)
    assert onboarding.validate_provider("copilot", {}) == "missing"


def test_validate_copilot_unauth_when_gh_status_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.setattr(onboarding.shutil, "which", lambda name: "/usr/bin/gh")

    class _P:
        returncode = 1

    monkeypatch.setattr(onboarding.subprocess, "run", lambda *a, **k: _P())
    assert onboarding.validate_provider("copilot", {}) == "unauth"


def test_validate_droid_ok(monkeypatch):
    monkeypatch.setattr(providers, "get_droid_usage", lambda cfg=None: {"available": True})
    assert onboarding.validate_provider("droid", {}) == "ok"


def test_validate_droid_missing(monkeypatch):
    monkeypatch.setattr(providers, "get_droid_usage", lambda cfg=None: {"available": False})
    assert onboarding.validate_provider("droid", {}) == "missing"


# ── Degraded rows (selection path) + legacy-path parity ───────────────────────

_CODEX_COMPACT = {
    "provider": "codex", "label": "Codex", "available": True, "display": "compact",
    "metrics": [{"label": "5h", "used_pct": 10, "resets_at": None}], "stale_seconds": 0,
}


def _only_unavailable(config, only=None):
    return [providers.unavailable(p) for p in (only or [])]


def test_degraded_row_for_selected_unavailable_provider(monkeypatch):
    _require_engine()
    monkeypatch.setattr(engine._usage_providers, "collect_external_usage", _only_unavailable)
    out = engine.build_external_usage_lines(
        {
            "config": {
                "tier": "multi-cli",
                "providers": {"schema_version": 1, "selected": ["claude", "codex"]},
                "external_providers": {"enabled": True},
            },
            "is_full": True, "is_multi_cli": True, "render_width": 0,
        }
    )
    assert _strip(out) == "│ ▸ Codex  no data — /statusline-onboarding │"


def test_degraded_rows_silenced_by_show_unavailable_false(monkeypatch):
    _require_engine()
    monkeypatch.setattr(engine._usage_providers, "collect_external_usage", _only_unavailable)
    out = engine.build_external_usage_lines(
        {
            "config": {
                "tier": "multi-cli",
                "providers": {"schema_version": 1, "selected": ["claude", "codex"], "show_unavailable": False},
                "external_providers": {"enabled": True},
            },
            "is_full": True, "is_multi_cli": True, "render_width": 0,
        }
    )
    assert out == ""


def test_selection_interleaves_available_and_degraded_in_order(monkeypatch):
    _require_engine()

    def collect(config, only=None):
        return [dict(_CODEX_COMPACT) if p == "codex" else providers.unavailable(p) for p in (only or [])]

    monkeypatch.setattr(engine._usage_providers, "collect_external_usage", collect)
    out = engine.build_external_usage_lines(
        {
            "config": {
                "tier": "multi-cli",
                "providers": {"schema_version": 1, "selected": ["claude", "codex", "antigravity"]},
                "external_providers": {"enabled": True},
            },
            "is_full": True, "is_multi_cli": True, "render_width": 0,
        }
    )
    rows = _strip(out).split("\n")
    assert rows == [
        "│ ▸ Codex  5h 10% │",
        "│ ▸ AGY    no data — /statusline-onboarding │",
    ]


def test_legacy_path_renders_available_only_no_degraded_rows(monkeypatch):
    """No providers block → the legacy render path. It must NOT pass only=,
    must drop unavailable providers silently (byte-identical to pre-change),
    and must never emit a degraded row."""
    _require_engine()

    def collect(config, only=None):
        assert only is None  # legacy path never uses the selection arg
        return [dict(_CODEX_COMPACT), providers.unavailable("glm")]

    monkeypatch.setattr(engine._usage_providers, "collect_external_usage", collect)
    out = engine.build_external_usage_lines(
        {
            "config": {
                "tier": "multi-cli",
                "external_providers": {"enabled": True, "codex": {"enabled": True}, "glm": {"enabled": True}},
            },
            "is_full": True, "is_multi_cli": True, "render_width": 0,
        }
    )
    stripped = _strip(out)
    # Exactly one row: available codex renders; unavailable glm vanished; no "no data".
    assert stripped == "│ ▸ Codex  5h 10% │"
    assert "no data" not in stripped
    assert "GLM" not in stripped
