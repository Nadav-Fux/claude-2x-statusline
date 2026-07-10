"""seg_tool_count: this session's tool-call count (owner-approved adoption
item 2). Counts literal '"type":"tool_use"' occurrences in the transcript
JSONL named by stdin's transcript_path, cached by session_id + transcript
mtime under $TMPDIR/claude/ (never ~/.claude/). A missing/unreadable
transcript omits the whole segment; a legitimate zero-events reading still
renders (it is not "missing data").
"""
from __future__ import annotations

import importlib.util
import json
import re
import tempfile
from pathlib import Path

import pytest

_ENGINE = Path(__file__).resolve().parent.parent / "engines" / "python-engine.py"
_spec = importlib.util.spec_from_file_location("engine", _ENGINE)
engine = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(engine)

_strip = lambda s: re.sub(r"\x1b\[[0-9;]*m", "", s)

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_TRANSCRIPT_WITH_TOOLS = _FIXTURES / "transcript_tool_calls.jsonl"
_TRANSCRIPT_NO_TOOLS = _FIXTURES / "transcript_no_tools.jsonl"


@pytest.fixture(autouse=True)
def _isolated_tmpdir(tmp_path, monkeypatch):
    """Redirect tempfile.gettempdir() so the tool-count cache never touches
    the real $TMPDIR/claude/ (or collides between test runs)."""
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    return tmp_path


def _ctx(session_id, transcript_path):
    return {"stdin": {"session_id": session_id, "transcript_path": str(transcript_path)}}


def test_counts_tool_use_events_in_transcript():
    out = _strip(engine.seg_tool_count(_ctx("sess-a", _TRANSCRIPT_WITH_TOOLS)))
    assert out == "⚒ 5"


def test_zero_tool_use_events_still_renders_the_segment():
    # A legitimate "no tool calls yet" reading is not the same as missing
    # data -- it must render "⚒ 0", not be omitted.
    out = _strip(engine.seg_tool_count(_ctx("sess-b", _TRANSCRIPT_NO_TOOLS)))
    assert out == "⚒ 0"


def test_missing_transcript_omits_the_whole_segment():
    missing = Path("/nonexistent/path/does-not-exist.jsonl")
    assert engine.seg_tool_count(_ctx("sess-c", missing)) == ""


def test_missing_session_id_omits_the_whole_segment():
    assert engine.seg_tool_count({"stdin": {"transcript_path": str(_TRANSCRIPT_WITH_TOOLS)}}) == ""


def test_missing_transcript_path_omits_the_whole_segment():
    assert engine.seg_tool_count({"stdin": {"session_id": "sess-d"}}) == ""


def test_unreadable_transcript_omits_the_whole_segment(tmp_path):
    # Exists but is a directory, not a file -- read_text() must fail cleanly.
    bogus = tmp_path / "not-a-file.jsonl"
    bogus.mkdir()
    assert engine.seg_tool_count(_ctx("sess-e", bogus)) == ""


def test_writes_cache_under_tmpdir_claude_not_home_claude(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))

    engine.seg_tool_count(_ctx("sess-cache", _TRANSCRIPT_WITH_TOOLS))

    cache_dir = tmp_path / "claude"
    cache_files = list(cache_dir.glob("statusline-toolcount-*.json"))
    assert len(cache_files) == 1
    payload = json.loads(cache_files[0].read_text(encoding="utf-8"))
    assert payload["count"] == 5

    # Never under ~/.claude/ -- seg_tool_count doesn't touch it at all.
    assert not (fake_home / ".claude").exists()


def test_cache_is_reused_when_transcript_mtime_is_unchanged(tmp_path):
    # Point a session at a private copy of the fixture so we can rewrite the
    # cache file under it without disturbing other tests' cache entries.
    transcript = tmp_path / "session.jsonl"
    transcript.write_text(_TRANSCRIPT_WITH_TOOLS.read_text(encoding="utf-8"), encoding="utf-8")

    first = engine.seg_tool_count(_ctx("sess-reuse", transcript))
    assert _strip(first) == "⚒ 5"

    # Tamper with the cached count directly (keeping mtime untouched) to prove
    # a second render reads the cache instead of recomputing from the file.
    import hashlib
    h = hashlib.sha256("sess-reuse".encode()).hexdigest()[:16]
    cache_file = tmp_path / "claude" / f"statusline-toolcount-{h}.json"
    payload = json.loads(cache_file.read_text(encoding="utf-8"))
    payload["count"] = 999
    cache_file.write_text(json.dumps(payload), encoding="utf-8")

    second = engine.seg_tool_count(_ctx("sess-reuse", transcript))
    assert _strip(second) == "⚒ 999"


def test_cache_is_invalidated_when_transcript_mtime_changes(tmp_path):
    import os
    import time

    transcript = tmp_path / "session2.jsonl"
    transcript.write_text(_TRANSCRIPT_NO_TOOLS.read_text(encoding="utf-8"), encoding="utf-8")

    first = engine.seg_tool_count(_ctx("sess-invalidate", transcript))
    assert _strip(first) == "⚒ 0"

    # Append a tool_use event and bump mtime forward -- the cache must miss
    # and recompute rather than serving the stale zero count.
    with open(transcript, "a", encoding="utf-8") as fh:
        fh.write('{"type":"assistant","message":{"content":[{"type":"tool_use","id":"t1","name":"Bash","input":{}}]}}\n')
    future = time.time() + 5
    os.utime(transcript, (future, future))

    second = engine.seg_tool_count(_ctx("sess-invalidate", transcript))
    assert _strip(second) == "⚒ 1"
