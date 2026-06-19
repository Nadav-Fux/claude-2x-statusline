"""Responsive-width reflow tests for the statusline engine (line-1 wrapping)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_ENGINE_PATH = Path(__file__).resolve().parent.parent / "engines" / "python-engine.py"
_spec = importlib.util.spec_from_file_location("engine", _ENGINE_PATH)
engine = importlib.util.module_from_spec(_spec)
try:
    _spec.loader.exec_module(engine)
    _IMPORT_ERR = None
except Exception as exc:  # pragma: no cover
    _IMPORT_ERR = exc


def _require_engine():
    if _IMPORT_ERR is not None:
        pytest.skip(f"engine import failed: {_IMPORT_ERR}")


def test_visible_width_ignores_ansi_and_counts_wide():
    _require_engine()
    assert engine.visible_width("\x1b[31mabc\x1b[0m") == 3
    # a wide (full-width) char counts as 2 columns
    assert engine.visible_width("ｗ") == 2


def test_resolve_render_width_prefers_columns(monkeypatch):
    _require_engine()
    monkeypatch.setenv("COLUMNS", "100")
    assert engine.resolve_render_width({}) == 100


def test_resolve_render_width_caps_with_max_width(monkeypatch):
    _require_engine()
    monkeypatch.setenv("COLUMNS", "200")
    assert engine.resolve_render_width({"max_width": 120}) == 120


def test_resolve_render_width_disabled_by_config(monkeypatch):
    _require_engine()
    monkeypatch.setenv("COLUMNS", "100")
    assert engine.resolve_render_width({"reflow": False}) == 0


def test_resolve_render_width_zero_when_unknown(monkeypatch):
    _require_engine()
    monkeypatch.delenv("COLUMNS", raising=False)
    assert engine.resolve_render_width({}) == 0


def test_reflow_packs_then_wraps():
    _require_engine()
    parts = ["aaaa", "bbbb", "cccc"]  # 4 cols each
    # width 11 fits "aaaa | bbbb" (4+3+4), then "cccc" wraps to its own line
    assert engine.reflow_parts(parts, " | ", 11) == ["aaaa | bbbb", "cccc"]


def test_reflow_keeps_overlong_single_part():
    _require_engine()
    # a single part wider than the width is never split or dropped
    assert engine.reflow_parts(["averylongsegment"], " | ", 5) == ["averylongsegment"]


def test_dashboard_line_single_row_when_it_fits():
    _require_engine()
    out = engine.render_dashboard_line(["aaa", "bbb"], 100)
    assert "\n" not in out
    assert "aaa" in out and "bbb" in out


def test_dashboard_line_wraps_into_bordered_rows_when_narrow():
    _require_engine()
    parts = ["window-one-aaaa", "window-two-bbbb", "window-three-cccc"]
    out = engine.render_dashboard_line(parts, 24)
    rows = out.split("\n")
    assert len(rows) >= 2, "narrow width should wrap to multiple rows"
    # every wrapped row keeps the │ border
    for row in rows:
        assert "│" in engine._ANSI_RE.sub("", row)


def test_dashboard_line_keeps_trailing_on_last_row():
    _require_engine()
    out = engine.render_dashboard_line(["aaaaa", "bbbbb", "ccccc"], 16, trailing="TRAIL")
    assert "TRAIL" in out.split("\n")[-1]
