"""Tests for the tasks segment and responsive timeline feature.

Covers:
  - seg_tasks: hidden when no session_id / no dir / no task files
  - seg_tasks: correct done/total counting with mixed statuses
  - seg_tasks: all-done shows ✓ form, in-progress shows ◔ form
  - seg_tasks: non-numeric filenames (.lock, .highwatermark, README) ignored
  - build_timeline: hidden when wider than render_width
  - build_timeline: kept when narrower than render_width or render_width is 0
"""

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
    _IMPORT_ERR = None
except Exception as exc:  # pragma: no cover
    _IMPORT_ERR = exc


def _require_engine():
    if _IMPORT_ERR is not None:
        pytest.skip(f"engine import failed: {_IMPORT_ERR}")


ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def strip_ansi(s: str) -> str:
    return ANSI_RE.sub("", s)


# ─── seg_tasks ───────────────────────────────────────────────────────────────

def test_tasks_hidden_when_no_session_id():
    _require_engine()
    assert engine.seg_tasks({"stdin": {}}) == ""
    assert engine.seg_tasks({"stdin": {"session_id": ""}}) == ""


def test_tasks_hidden_when_no_tasks_dir(tmp_path, monkeypatch):
    _require_engine()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    # home is tmp_path but ~/.claude/tasks/<sid> does not exist
    ctx = {"stdin": {"session_id": "no-such-session"}}
    assert engine.seg_tasks(ctx) == ""


def test_tasks_hidden_when_zero_task_files(tmp_path, monkeypatch):
    """A tasks dir with only .lock/.highwatermark files → hidden."""
    _require_engine()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    sid = "test-session-zero"
    tasks_dir = tmp_path / ".claude" / "tasks" / sid
    tasks_dir.mkdir(parents=True)
    # Non-numeric files that must be ignored
    (tasks_dir / ".lock").write_text("")
    (tasks_dir / ".highwatermark").write_text("3")
    (tasks_dir / "README.md").write_text("notes")
    ctx = {"stdin": {"session_id": sid}}
    assert engine.seg_tasks(ctx) == ""


def test_tasks_done_total_counting_mixed_statuses(tmp_path, monkeypatch):
    """done counts only 'completed'; pending/in_progress do not count."""
    _require_engine()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    sid = "test-session-mixed"
    tasks_dir = tmp_path / ".claude" / "tasks" / sid
    tasks_dir.mkdir(parents=True)

    statuses = [
        ("1.json", "completed"),
        ("2.json", "in_progress"),
        ("3.json", "pending"),
        ("4.json", "completed"),
    ]
    for fname, status in statuses:
        (tasks_dir / fname).write_text(json.dumps({"status": status, "subject": "task"}))
    # Ignored non-numeric files
    (tasks_dir / ".lock").write_text("")
    (tasks_dir / ".highwatermark").write_text("4")

    ctx = {"stdin": {"session_id": sid}}
    result = engine.seg_tasks(ctx)
    plain = strip_ansi(result)
    assert "2/4 tasks" in plain, f"expected 2/4 tasks in {plain!r}"
    # In-progress (not all done) → ◔ indicator
    assert "◔" in plain, f"expected ◔ in {plain!r}"


def test_tasks_all_done_shows_checkmark(tmp_path, monkeypatch):
    """When done == total, output uses ✓ instead of ◔."""
    _require_engine()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    sid = "test-session-alldone"
    tasks_dir = tmp_path / ".claude" / "tasks" / sid
    tasks_dir.mkdir(parents=True)

    for i in range(1, 4):
        (tasks_dir / f"{i}.json").write_text(json.dumps({"status": "completed"}))

    ctx = {"stdin": {"session_id": sid}}
    result = engine.seg_tasks(ctx)
    plain = strip_ansi(result)
    assert "3/3 tasks" in plain, f"expected 3/3 tasks in {plain!r}"
    assert "✓" in plain, f"expected ✓ in {plain!r}"


def test_tasks_ignores_corrupt_file(tmp_path, monkeypatch):
    """Corrupt JSON in one task file must not raise; that file is skipped."""
    _require_engine()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    sid = "test-session-corrupt"
    tasks_dir = tmp_path / ".claude" / "tasks" / sid
    tasks_dir.mkdir(parents=True)

    (tasks_dir / "1.json").write_text(json.dumps({"status": "completed"}))
    (tasks_dir / "2.json").write_text("NOT JSON {{{{")  # corrupt

    ctx = {"stdin": {"session_id": sid}}
    result = engine.seg_tasks(ctx)
    plain = strip_ansi(result)
    # total=2 (both numeric), done=1 (only the valid completed one)
    assert "1/2 tasks" in plain, f"expected 1/2 tasks in {plain!r}"


# ─── build_timeline responsive hide ──────────────────────────────────────────

def _make_timeline_ctx(render_width: int) -> dict:
    """Return a minimal ctx that drives build_timeline into the legend path."""
    from datetime import datetime, timezone
    now = datetime(2026, 6, 19, 10, 0, tzinfo=timezone.utc).astimezone()
    return {
        "schedule": {"mode": "peak_hours"},
        "local_time": now,
        "peak_start_local": 5,
        "peak_end_local": 11,
        "peak_days": [1, 2, 3, 4, 5],  # weekday coverage for any test day
        "render_width": render_width,
    }


def test_timeline_hidden_when_wider_than_render_width():
    """A narrow render_width (e.g. 70) must hide the ~130-col timeline."""
    _require_engine()
    ctx = _make_timeline_ctx(render_width=70)
    result = engine.build_timeline(ctx)
    assert result == "", f"expected '' for narrow terminal, got: {result!r}"


def test_timeline_kept_when_render_width_is_zero():
    """render_width == 0 means 'unknown' → never hide (preserve old behaviour)."""
    _require_engine()
    ctx = _make_timeline_ctx(render_width=0)
    result = engine.build_timeline(ctx)
    assert result != "", "timeline should not be hidden when render_width is 0"


def test_timeline_kept_when_wide_enough():
    """A very wide terminal (300 cols) must keep the timeline."""
    _require_engine()
    ctx = _make_timeline_ctx(render_width=300)
    result = engine.build_timeline(ctx)
    assert result != "", "timeline should be shown on a wide terminal"
