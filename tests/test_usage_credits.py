"""Usage credits / overflow segment tests."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_ENGINE_PATH = Path(__file__).resolve().parent.parent / "engines" / "python-engine.py"
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


def test_usage_credits_renders_enabled_limit():
    _require_engine()
    result = engine.seg_usage_credits(
        {"usage_data": {"extra_usage": {"enabled": True, "consumed_usd": 5.50, "limit_usd": 20.0}}}
    )

    assert "overflow" in result
    assert "$5.50/$20" in result


def test_usage_credits_hides_when_inactive():
    _require_engine()
    assert engine.seg_usage_credits(
        {"usage_data": {"extra_usage": {"enabled": False, "consumed_usd": 0}}}
    ) == ""


def test_usage_credits_reports_disabled_after_consumption():
    _require_engine()
    assert "overflow: off" in engine.seg_usage_credits(
        {"usage_data": {"extra_usage": {"enabled": False, "consumed_usd": 1.0}}}
    )


def test_usage_credits_survives_null_cache_values():
    _require_engine()
    # float(None) used to raise; null/garbage cache values must coerce safely
    result = engine.seg_usage_credits(
        {"usage_data": {"extra_usage": {"enabled": True, "consumed_usd": None, "limit_usd": None}}}
    )
    assert isinstance(result, str)
    assert engine.seg_usage_credits({"usage_data": {"extra_usage": "garbage"}}) == ""
