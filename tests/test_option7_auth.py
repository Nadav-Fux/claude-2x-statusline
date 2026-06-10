"""Option 7 auth badge and SDK meter tests."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_ENGINE_PATH = _ROOT / "engines" / "python-engine.py"
_spec = importlib.util.spec_from_file_location("engine", _ENGINE_PATH)
engine = importlib.util.module_from_spec(_spec)
try:
    _spec.loader.exec_module(engine)
    _IMPORT_OK = True
except Exception as _exc:
    _IMPORT_OK = False
    _IMPORT_ERR = str(_exc)


def _require_engine():
    if not _IMPORT_OK:
        pytest.skip(f"engine import failed: {_IMPORT_ERR}")


def test_auth_mode_warns_on_exported_api_key(monkeypatch):
    _require_engine()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    assert "API-KEY EXPORTED" in engine.seg_auth_mode({})


def test_auth_mode_detects_oauth_token(monkeypatch):
    _require_engine()
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "oauth-token")

    assert "auth:oauth" in engine.seg_auth_mode({})


def test_api_key_warning_is_unconditional_in_main(tmp_path):
    fake_home = tmp_path / "home"
    claude_dir = fake_home / ".claude"
    claude_dir.mkdir(parents=True)
    (claude_dir / "statusline-config.json").write_text(
        json.dumps({"tier": "minimal", "schedule_url": "", "schedule_cache_hours": 999}),
        encoding="utf-8",
    )
    (claude_dir / "statusline-schedule.json").write_text(
        json.dumps({"mode": "normal", "banner": {}, "release": {}, "features": {}}),
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["USERPROFILE"] = str(fake_home)
    env["HOME"] = str(fake_home)
    env["ANTHROPIC_API_KEY"] = "test-key"
    proc = subprocess.run(
        [sys.executable, "engines/python-engine.py", "--tier=minimal"],
        input=json.dumps(
            {
                "context_window": {
                    "context_window_size": 200000,
                    "current_usage": {"input_tokens": 10},
                }
            }
        ),
        text=True,
        capture_output=True,
        cwd=_ROOT,
        env=env,
        timeout=10,
        check=True,
    )

    assert "API-KEY EXPORTED" in proc.stdout


def test_sdk_meter_reads_ledger(tmp_path, monkeypatch):
    _require_engine()
    fake_home = tmp_path / "home"
    claude_dir = fake_home / ".claude"
    claude_dir.mkdir(parents=True)
    (claude_dir / "statusline-sdk-ledger.json").write_text(
        json.dumps({"month_total_usd": 15.0, "plan_ceiling_usd": 20.0}),
        encoding="utf-8",
    )
    monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))

    rendered = engine.seg_sdk_meter({"usage_data": {"extra_usage": {"enabled": True}}})

    assert "sdk" in rendered
    assert "$15.00/$20" in rendered
    assert "~per-machine approx" in rendered


def test_sdk_meter_marks_blocked(tmp_path, monkeypatch):
    _require_engine()
    fake_home = tmp_path / "home"
    claude_dir = fake_home / ".claude"
    claude_dir.mkdir(parents=True)
    (claude_dir / "statusline-sdk-ledger.json").write_text(
        json.dumps({"month_total_usd": 21.0, "plan_ceiling_usd": 20.0}),
        encoding="utf-8",
    )
    monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))

    assert "BLOCKED" in engine.seg_sdk_meter({"usage_data": {"extra_usage": {"enabled": False}}})
