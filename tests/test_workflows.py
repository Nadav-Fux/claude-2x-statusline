"""Workflow segment tests."""

from __future__ import annotations

import importlib.util
import shutil
from datetime import datetime
from pathlib import Path

import pytest

from lib import workflows

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


def _ctx(session_dir: Path) -> dict:
    return {
        "stdin": {"transcript_path": str(session_dir / "session.jsonl")},
        "schedule": {},
        "local_time": datetime(2026, 6, 10, 12, 0, 0),
        "config": {"tier": "standard"},
    }


def test_live_workflow_uses_last_usage_block_only(tmp_path):
    _require_engine()
    session_dir = tmp_path / "session"
    live_dir = session_dir / "subagents" / "workflows" / "wf_test"
    live_dir.mkdir(parents=True)
    fixture = Path(__file__).resolve().parent / "fixtures" / "agent_sample.jsonl"
    agent_file = live_dir / "agent-001.jsonl"
    shutil.copyfile(fixture, agent_file)

    assert workflows.read_agent_last_usage_tokens(agent_file) == 57_826

    result = engine.seg_workflows(_ctx(session_dir))

    assert "1 agents ctx" in result
    assert "ctx" in result
    assert "57K" in result


def test_completed_workflow_summary(tmp_path):
    _require_engine()
    session_dir = tmp_path / "session"
    completed_dir = session_dir / "workflows"
    completed_dir.mkdir(parents=True)
    shutil.copyfile(
        Path(__file__).resolve().parent / "fixtures" / "wf_sample.json",
        completed_dir / "wf_sample.json",
    )

    result = engine.seg_workflows(_ctx(session_dir))

    assert "wf:" in result
    assert "287K" in result
    assert "1 runs" in result


def test_workflows_segment_hides_without_session():
    _require_engine()
    ctx = {"stdin": {}, "schedule": {}, "local_time": datetime(2026, 6, 10, 12, 0, 0)}

    assert engine.seg_workflows(ctx) == ""
