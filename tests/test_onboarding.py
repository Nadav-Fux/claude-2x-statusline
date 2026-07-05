from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from lib import onboarding
from lib import usage_providers as providers


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
