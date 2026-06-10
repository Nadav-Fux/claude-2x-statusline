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

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _require_engine():
    if not _IMPORT_OK:
        pytest.skip(f"engine import failed: {_IMPORT_ERR}")


def _ctx(session_dir: Path) -> dict:
    # Real layout: the transcript <sid>.jsonl is a SIBLING of the session dir
    # <sid>/, both inside the project slug dir.
    return {
        "stdin": {"transcript_path": str(session_dir.with_suffix(".jsonl"))},
        "schedule": {},
        "local_time": datetime(2026, 6, 10, 12, 0, 0),
        "config": {"tier": "standard"},
    }


def test_project_slug_matches_claude_code_convention():
    # Verified against a real ~/.claude/projects entry.
    assert (
        workflows.project_slug("C:\\Users\\nadav\\github\\Nadav-Plugins&Skils")
        == "C--Users-nadav-github-Nadav-Plugins-Skils"
    )


def test_find_session_dir_uses_transcript_sibling_dir(tmp_path):
    session_dir = tmp_path / "abc-session-id"
    session_dir.mkdir()
    transcript = tmp_path / "abc-session-id.jsonl"
    transcript.write_text("{}\n", encoding="utf-8")

    found = workflows.find_session_dir({"transcript_path": str(transcript)})

    assert found == session_dir


def test_live_workflow_uses_last_usage_block_only(tmp_path):
    _require_engine()
    session_dir = tmp_path / "session"
    live_dir = session_dir / "subagents" / "workflows" / "wf_test"
    live_dir.mkdir(parents=True)
    agent_file = live_dir / "agent-001.jsonl"
    shutil.copyfile(_FIXTURES / "agent_sample.jsonl", agent_file)

    assert workflows.read_agent_last_usage_tokens(agent_file) == 62_000

    result = engine.seg_workflows(_ctx(session_dir))

    assert "1 agents ctx" in result
    assert "ctx" in result
    assert "62K" in result


def test_last_usage_returns_last_real_format_block_not_stale(tmp_path):
    # The final real-format block is followed by ',"server_tool_use":{...}'
    # (no '}' or '\n' in the next 20 chars); the heuristic must still accept
    # it instead of falling back to the stale matches[-2] block (57_826).
    agent_file = tmp_path / "agent-001.jsonl"
    shutil.copyfile(_FIXTURES / "agent_sample.jsonl", agent_file)

    assert workflows.read_agent_last_usage_tokens(agent_file) == 62_000


def test_last_usage_falls_back_when_final_block_truncated(tmp_path):
    agent_file = tmp_path / "agent-001.jsonl"
    text = (_FIXTURES / "agent_sample.jsonl").read_text(encoding="utf-8")
    truncated = (
        '{"type":"assistant","message":{"usage":{"input_tokens":9,'
        '"cache_creation_input_tokens":9,"cache_read_input_tokens":9,'
        '"output_tokens":12'
    )
    agent_file.write_text(text + truncated, encoding="utf-8")

    # Final number truncated mid-write -> use the previous complete block.
    assert workflows.read_agent_last_usage_tokens(agent_file) == 62_000


def test_last_usage_returns_zero_when_only_match_truncated(tmp_path):
    agent_file = tmp_path / "agent-001.jsonl"
    agent_file.write_text(
        '{"type":"assistant","message":{"usage":{"input_tokens":5,'
        '"cache_creation_input_tokens":5,"cache_read_input_tokens":5,'
        '"output_tokens":7',
        encoding="utf-8",
    )

    assert workflows.read_agent_last_usage_tokens(agent_file) == 0


def test_completed_workflow_summary(tmp_path):
    _require_engine()
    session_dir = tmp_path / "session"
    completed_dir = session_dir / "workflows"
    completed_dir.mkdir(parents=True)
    shutil.copyfile(_FIXTURES / "wf_sample.json", completed_dir / "wf_sample.json")

    result = engine.seg_workflows(_ctx(session_dir))

    assert "wf:" in result
    assert "287K" in result
    assert "1 runs" in result


def test_workflows_segment_hides_without_session(tmp_path, monkeypatch):
    _require_engine()
    # Keep the cwd-based sessions fallback away from the real ~/.claude.
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    ctx = {"stdin": {}, "schedule": {}, "local_time": datetime(2026, 6, 10, 12, 0, 0)}

    assert engine.seg_workflows(ctx) == ""
