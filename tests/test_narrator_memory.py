"""Unit tests for narrator.memory I/O.

Covers:
- load() on missing file returns default structure
- load() on corrupt JSON returns default structure (no raise)
- save() is atomic — partial writes don't leave half files
- rotate_session pushes current to prior_sessions[0], truncates at 3
- evict_old_observations drops items > 2h old
"""

import json
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import narrator.memory as mem_mod
from narrator.memory import (
    load,
    save,
    rotate_session,
    evict_old_observations,
    append_observation,
    append_narrative,
    _default_current,
    _default_memory,
)


# ---------------------------------------------------------------------------
# Fixture: redirect memory path to tmp dir
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def tmp_memory_path(tmp_path, monkeypatch):
    """Redirect narrator.memory._MEMORY_PATH to a temp file for each test."""
    fake_mem = tmp_path / "narrator-memory.json"
    monkeypatch.setattr(mem_mod, "_MEMORY_PATH", fake_mem)
    return fake_mem


# ---------------------------------------------------------------------------
# 1. load() on missing file
# ---------------------------------------------------------------------------

class TestLoad:
    def test_missing_file_returns_default(self, tmp_memory_path):
        """load() on a non-existent file returns the default structure."""
        assert not tmp_memory_path.exists()
        data = load()
        assert "current" in data
        assert "prior_sessions" in data
        assert isinstance(data["prior_sessions"], list)
        current = data["current"]
        assert "session_id" in current
        assert "delivered_narratives" in current
        assert "rolling_observations" in current
        assert "cost_milestones_hit" in current
        assert "prompt_count" in current

    def test_corrupt_json_returns_default(self, tmp_memory_path):
        """load() on corrupt JSON file returns default, does not raise."""
        tmp_memory_path.write_text("{{not valid json}}", encoding="utf-8")
        data = load()  # should not raise
        assert "current" in data
        assert "prior_sessions" in data

    def test_empty_file_returns_default(self, tmp_memory_path):
        """load() on empty file returns default."""
        tmp_memory_path.write_text("", encoding="utf-8")
        data = load()
        assert "current" in data

    def test_wrong_shape_returns_default(self, tmp_memory_path):
        """load() on a JSON array (wrong shape) returns default."""
        tmp_memory_path.write_text("[]", encoding="utf-8")
        data = load()
        assert "current" in data

    def test_valid_file_loads_correctly(self, tmp_memory_path):
        """load() on a valid file returns the stored data."""
        stored = {
            "current": {
                "session_id": "sess-abc",
                "started_at": 1000.0,
                "last_emit_at": 2000.0,
                "last_haiku_at": 0.0,
                "rolling_observations": [],
                "delivered_narratives": [{"text": "hi", "template_key": "x", "ts": 999}],
                "cost_milestones_hit": [5.0],
                "prompt_count": 3,
            },
            "prior_sessions": [],
        }
        tmp_memory_path.write_text(json.dumps(stored), encoding="utf-8")
        data = load()
        assert data["current"]["session_id"] == "sess-abc"
        assert data["current"]["prompt_count"] == 3
        assert data["current"]["cost_milestones_hit"] == [5.0]


# ---------------------------------------------------------------------------
# 2. save() atomicity
# ---------------------------------------------------------------------------

class TestSave:
    def test_save_writes_valid_json(self, tmp_memory_path):
        """save() writes valid JSON that load() can read back."""
        original = _default_memory()
        original["current"]["session_id"] = "test-atomic"
        save(original)
        assert tmp_memory_path.exists()
        data = load()
        assert data["current"]["session_id"] == "test-atomic"

    def test_save_no_tmp_file_left(self, tmp_memory_path):
        """save() cleans up the .tmp file after writing."""
        save(_default_memory())
        tmp_file = tmp_memory_path.with_suffix(".json.tmp")
        assert not tmp_file.exists(), "Tmp file should be cleaned up after atomic replace"

    def test_save_roundtrip(self, tmp_memory_path):
        """Data saved and loaded back is identical."""
        original = _default_memory()
        original["current"]["prompt_count"] = 42
        original["current"]["cost_milestones_hit"] = [5.0, 10.0]
        save(original)
        loaded = load()
        assert loaded["current"]["prompt_count"] == 42
        assert loaded["current"]["cost_milestones_hit"] == [5.0, 10.0]

    def test_save_overwrites_previous(self, tmp_memory_path):
        """Calling save() twice replaces the first write."""
        data1 = _default_memory()
        data1["current"]["session_id"] = "first"
        save(data1)

        data2 = _default_memory()
        data2["current"]["session_id"] = "second"
        save(data2)

        loaded = load()
        assert loaded["current"]["session_id"] == "second"


# ---------------------------------------------------------------------------
# 3. rotate_session
# ---------------------------------------------------------------------------

class TestRotateSession:
    def test_rotate_pushes_current_to_prior(self):
        """Current session becomes prior_sessions[0] after rotation."""
        data = _default_memory()
        data["current"]["session_id"] = "old-session"
        data["current"]["delivered_narratives"] = [
            {"text": f"text{i}", "template_key": f"k{i}", "ts": float(i)}
            for i in range(3)
        ]

        new_data = rotate_session(data, "new-session")

        assert new_data["current"]["session_id"] == "new-session"
        assert len(new_data["prior_sessions"]) == 1
        assert new_data["prior_sessions"][0]["session_id"] == "old-session"

    def test_rotate_keeps_top_5_narratives(self):
        """rotate_session keeps only the last 5 narratives from the old session."""
        data = _default_memory()
        data["current"]["delivered_narratives"] = [
            {"text": f"text{i}", "template_key": f"k{i}", "ts": float(i)}
            for i in range(8)  # 8 narratives
        ]

        new_data = rotate_session(data, "new-sess")
        prior = new_data["prior_sessions"][0]
        assert len(prior["narratives"]) <= 5

    def test_rotate_truncates_prior_sessions_at_3(self):
        """Prior sessions list is truncated to 3 entries."""
        data = _default_memory()
        # Pre-populate with 3 prior sessions
        data["prior_sessions"] = [
            {"session_id": f"s{i}", "ended_at": float(i), "narratives": []}
            for i in range(3)
        ]
        data["current"]["session_id"] = "current-session"

        new_data = rotate_session(data, "newest")
        assert len(new_data["prior_sessions"]) == 3  # truncated from 4

    def test_rotate_creates_fresh_current(self):
        """After rotation, current has zeroed counters."""
        data = _default_memory()
        data["current"]["prompt_count"] = 50
        data["current"]["cost_milestones_hit"] = [5.0, 10.0]

        new_data = rotate_session(data, "fresh-session")
        assert new_data["current"]["prompt_count"] == 0
        assert new_data["current"]["cost_milestones_hit"] == []

    def test_rotate_new_session_has_started_at(self):
        """After rotation, new current has a started_at timestamp."""
        data = _default_memory()
        new_data = rotate_session(data, "brand-new")
        assert new_data["current"]["started_at"] > 0


# ---------------------------------------------------------------------------
# 4. evict_old_observations
# ---------------------------------------------------------------------------

class TestEvictOldObservations:
    def test_evict_removes_old_observations(self):
        """Observations older than 2 hours are removed."""
        now = time.time()
        data = _default_memory()
        data["current"]["rolling_observations"] = [
            {"ts": now - 3 * 3600, "cost_usd": 1.0},  # 3h old → evict
            {"ts": now - 1.5 * 3600, "cost_usd": 2.0},  # 1.5h old → keep
            {"ts": now - 100, "cost_usd": 3.0},         # 100s old → keep
        ]

        result = evict_old_observations(data)
        remaining = result["current"]["rolling_observations"]
        assert len(remaining) == 2
        assert all(o["ts"] >= now - 2 * 3600 for o in remaining)

    def test_evict_keeps_recent_observations(self):
        """Observations within 2 hours are kept."""
        now = time.time()
        data = _default_memory()
        data["current"]["rolling_observations"] = [
            {"ts": now - 60, "cost_usd": 1.0},
            {"ts": now - 3600, "cost_usd": 2.0},
            {"ts": now - 7300, "cost_usd": 3.0},   # just over 2h (7200s) → evict
        ]

        result = evict_old_observations(data)
        remaining = result["current"]["rolling_observations"]
        assert len(remaining) == 2

    def test_evict_empty_observations_ok(self):
        """evict_old_observations on empty list doesn't crash."""
        data = _default_memory()
        data["current"]["rolling_observations"] = []
        result = evict_old_observations(data)
        assert result["current"]["rolling_observations"] == []

    def test_evict_all_old_leaves_empty(self):
        """If all observations are old, rolling_observations becomes empty."""
        now = time.time()
        data = _default_memory()
        data["current"]["rolling_observations"] = [
            {"ts": now - 3 * 3600, "cost_usd": 1.0},
            {"ts": now - 5 * 3600, "cost_usd": 2.0},
        ]
        result = evict_old_observations(data)
        assert result["current"]["rolling_observations"] == []


# ---------------------------------------------------------------------------
# 5. append_observation and append_narrative helpers
# ---------------------------------------------------------------------------

class TestAppendHelpers:
    def test_append_observation_grows_list(self):
        data = _default_memory()
        data = append_observation(data, {"ts": 1000.0, "cost_usd": 0.5})
        data = append_observation(data, {"ts": 2000.0, "cost_usd": 1.0})
        assert len(data["current"]["rolling_observations"]) == 2

    def test_append_narrative_keeps_last_8(self):
        data = _default_memory()
        for i in range(12):
            data = append_narrative(data, {"text": f"t{i}", "template_key": f"k{i}", "ts": float(i)})
        assert len(data["current"]["delivered_narratives"]) == 8

    def test_append_narrative_preserves_order(self):
        data = _default_memory()
        for i in range(3):
            data = append_narrative(data, {"text": f"msg{i}", "template_key": f"k{i}", "ts": float(i)})
        texts = [n["text"] for n in data["current"]["delivered_narratives"]]
        assert texts == ["msg0", "msg1", "msg2"]
