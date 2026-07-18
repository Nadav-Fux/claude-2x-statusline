"""Option 3 rate-limit line tests."""

from __future__ import annotations

import importlib.util
import json
import re
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


def test_fable_meter_rides_the_codex_row(monkeypatch):
    """The model-scoped weekly meter (e.g. Fable) is appended to the RIGHT of the
    Codex external row -- never a standalone row under the Claude line -- and
    carries no reset stamp (it shares the Anthropic weekly clock)."""
    _require_engine()

    limits = [
        {
            "kind": "weekly_scoped",
            "group": "weekly",
            "percent": 24,
            "is_active": True,
            "resets_at": "2026-07-25T02:00:00.396083+00:00",
            "scope": {"model": {"id": None, "display_name": "Fable"}, "surface": None},
        }
    ]

    # (a) The Claude rate-limit line must NOT carry Fable anymore.
    monkeypatch.setattr(engine, "_check_offloop_drain", lambda _ctx, _usage: "")
    claude_line = engine.build_rate_limits_line(
        {
            "usage_data": {
                "five_hour": {"utilization": 5, "resets_at": "2026-06-10T12:00:00Z"},
                "seven_day": {"utilization": 17, "resets_at": "2026-06-11T12:00:00Z"},
                "limits": limits,
            }
        }
    )
    assert "Fable" not in claude_line

    # (b) Fable rides the Codex external row, to its right, with no reset stamp.
    def _fake_collect(config, only=None):
        return [{"provider": "codex", "available": True}]

    def _fake_row(record, now_sec, **kwargs):
        return {
            "label": "Codex",
            "parts": [
                {"kind": "label", "label": "Codex", "plan": "team"},
                {"kind": "window", "label": "7d", "pct": 27, "reset_text": ""},
            ],
        }

    monkeypatch.setattr(engine._usage_providers, "collect_external_usage", _fake_collect)
    monkeypatch.setattr(engine._usage_providers, "format_provider_row_parts", _fake_row)

    ctx = {
        "config": {"external_providers": {"enabled": True, "codex": {"enabled": True}}},
        "is_multi_cli": True,
        "render_width": 0,
        "usage_data": {"limits": limits},
    }
    plain = re.sub(r"\x1b\[[0-9;]*m", "", engine.build_external_usage_lines(ctx))
    codex_lines = [line for line in plain.splitlines() if "Codex" in line]

    assert len(codex_lines) == 1, plain
    assert "Fable" in codex_lines[0]
    assert "wk" in codex_lines[0]
    assert "24%" in codex_lines[0]
    # No reset stamp on the Fable segment.
    assert "⟳" not in codex_lines[0].split("Fable", 1)[1]
    # Fable only ever appears on the Codex line -- never a standalone row.
    assert all("Codex" in line for line in plain.splitlines() if "Fable" in line)
