"""Option 3 rate-limit line tests."""

from __future__ import annotations

import importlib.util
import json
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


def test_offloop_drain_warning(monkeypatch, tmp_path):
    _require_engine()
    fake_home = tmp_path / "home"
    (fake_home / ".claude").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))
    monkeypatch.setattr(engine, "_rs_rate", lambda _minutes: 0.32)

    # First call seeds the persistent state file (no prior reading yet)
    monkeypatch.setattr(engine.time, "time", lambda: 1_000.0)
    assert engine._check_offloop_drain({}, {"five_hour": {"utilization": 40.0}}) == ""

    state_path = fake_home / ".claude" / "statusline-offloop-state.json"
    seeded = json.loads(state_path.read_text(encoding="utf-8"))
    assert set(seeded) == {"utilization", "session_cost", "t"}
    assert seeded["utilization"] == 40.0
    assert seeded["t"] == 1_000.0

    # Second call 2 minutes later with mutated cache trips the indicator
    monkeypatch.setattr(engine.time, "time", lambda: 1_120.0)
    result = engine._check_offloop_drain({}, {"five_hour": {"utilization": 45.0}})
    assert "off-loop drain" in result

    # The check re-anchors the state file after evaluating
    reanchored = json.loads(state_path.read_text(encoding="utf-8"))
    assert reanchored["utilization"] == 45.0
    assert reanchored["t"] == 1_120.0


def test_offloop_drain_keeps_anchor_within_window(monkeypatch, tmp_path):
    _require_engine()
    fake_home = tmp_path / "home"
    (fake_home / ".claude").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))
    monkeypatch.setattr(engine, "_rs_rate", lambda _minutes: 0.32)

    monkeypatch.setattr(engine.time, "time", lambda: 1_000.0)
    engine._check_offloop_drain({}, {"five_hour": {"utilization": 40.0}})

    # <2min later: no warning, and the anchor must NOT be overwritten —
    # otherwise frequent renders would make a >=2min delta impossible.
    monkeypatch.setattr(engine.time, "time", lambda: 1_030.0)
    assert engine._check_offloop_drain({}, {"five_hour": {"utilization": 45.0}}) == ""
    state_path = fake_home / ".claude" / "statusline-offloop-state.json"
    assert json.loads(state_path.read_text(encoding="utf-8"))["t"] == 1_000.0


def test_offloop_drain_treats_corrupt_state_as_no_prior(monkeypatch, tmp_path):
    _require_engine()
    fake_home = tmp_path / "home"
    (fake_home / ".claude").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))
    state_path = fake_home / ".claude" / "statusline-offloop-state.json"
    state_path.write_text("{not json", encoding="utf-8")

    monkeypatch.setattr(engine.time, "time", lambda: 1_000.0)
    assert engine._check_offloop_drain({}, {"five_hour": {"utilization": 40.0}}) == ""
    # Corrupt file replaced with a fresh seed
    assert json.loads(state_path.read_text(encoding="utf-8"))["utilization"] == 40.0


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
