"""Option 3 rate-limit line tests."""

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


def test_offloop_drain_warning(monkeypatch):
    _require_engine()
    ctx = {"_prev_fh_pct": 40.0, "_prev_fh_time": 1_000.0}
    usage = {"five_hour": {"utilization": 45.0}}
    monkeypatch.setattr(engine.time, "time", lambda: 1_120.0)
    monkeypatch.setattr(engine, "_rs_rate", lambda _minutes: 0.32)

    assert "off-loop drain" in engine._check_offloop_drain(ctx, usage)


def test_rate_limits_line_renders_sonnet_and_schedule_labels(monkeypatch):
    _require_engine()
    monkeypatch.setattr(engine, "_check_offloop_drain", lambda _ctx, _usage: "")
    ctx = {
        "schedule": {"labels": {"five_hour": "5h interactive", "weekly": "weekly interactive"}},
        "usage_data": {
            "five_hour": {"utilization": 20, "resets_at": "2026-06-10T12:00:00Z"},
            "seven_day": {"utilization": 30, "resets_at": "2026-06-11T12:00:00Z"},
            "seven_day_sonnet": {"utilization": 35, "resets_at": "2026-06-12T12:00:00Z"},
        },
    }

    line = engine.build_rate_limits_line(ctx)

    assert "5h interactive" in line
    assert "weekly interactive" in line
    assert "sonnet" in line
    assert "35%" in line
