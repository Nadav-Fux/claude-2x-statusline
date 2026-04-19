"""narrator.memory — persistent memory for cross-session narrator state.

File: ~/.claude/narrator-memory.json

Shape
-----
{
  "current": {
    "session_id": str,
    "started_at": float,          # epoch seconds
    "last_emit_at": float,        # epoch seconds (0 if never)
    "last_haiku_at": float,       # epoch seconds (0 if never)
    "rolling_observations": [...], # list of snapshots with "ts" field
    "delivered_narratives": [...], # last 8, each {text, template_key, ts}
    "cost_milestones_hit": [...],  # list of milestone floats hit this session
    "prompt_count": int
  },
  "prior_sessions": [            # ≤ 3 entries, most-recent first
    {
      "session_id": str,
      "ended_at": float,
      "narratives": [...]         # top-5 from that session
    }
  ]
}
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

_MEMORY_PATH = Path.home() / ".claude" / "narrator-memory.json"
_TMP_PATH = Path.home() / ".claude" / "narrator-memory.json.tmp"

_OBS_MAX_AGE_SECS = 2 * 3600  # 2 hours
_MAX_PRIOR_SESSIONS = 3
_MAX_DELIVERED_NARRATIVES = 8


# ---------------------------------------------------------------------------
# Default structures
# ---------------------------------------------------------------------------

def _default_current(session_id: str = "") -> dict:
    return {
        "session_id": session_id,
        "started_at": time.time(),
        "last_emit_at": 0.0,
        "last_haiku_at": 0.0,
        "rolling_observations": [],
        "delivered_narratives": [],
        "cost_milestones_hit": [],
        "prompt_count": 0,
    }


def _default_memory() -> dict:
    return {
        "current": _default_current(),
        "prior_sessions": [],
    }


# ---------------------------------------------------------------------------
# load / save
# ---------------------------------------------------------------------------

def load() -> dict:
    """Read narrator memory from disk.

    Returns default structure on FileNotFoundError or JSONDecodeError.
    """
    # Allow tests / callers to override path via module-level attribute
    path = _get_memory_path()
    try:
        text = path.read_text(encoding="utf-8")
        data = json.loads(text)
        # Basic shape validation
        if not isinstance(data, dict) or "current" not in data:
            return _default_memory()
        # Ensure all required keys exist in current
        current = data.setdefault("current", _default_current())
        for key, default in _default_current().items():
            current.setdefault(key, default)
        data.setdefault("prior_sessions", [])
        return data
    except FileNotFoundError:
        return _default_memory()
    except (json.JSONDecodeError, ValueError):
        return _default_memory()
    except Exception:
        return _default_memory()


def save(data: dict) -> None:
    """Atomically write narrator memory to disk (tmpfile + os.replace)."""
    path = _get_memory_path()
    tmp_path = path.with_suffix(".json.tmp")
    text = json.dumps(data, separators=(",", ":"))
    try:
        # Ensure parent directory exists
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path.write_text(text, encoding="utf-8")
        os.replace(str(tmp_path), str(path))
    except OSError:
        # Never crash the calling hook
        pass


# ---------------------------------------------------------------------------
# Session rotation
# ---------------------------------------------------------------------------

def rotate_session(data: dict, new_session_id: str) -> dict:
    """Push current session to prior_sessions, start a fresh current.

    Keeps only top-5 narratives from the rotated session.
    Truncates prior_sessions to 3 entries.
    """
    old_current = data.get("current", _default_current())

    # Build the prior-session record
    old_narratives = old_current.get("delivered_narratives", [])
    # Keep last 5
    top_narratives = old_narratives[-5:]

    prior_entry = {
        "session_id": old_current.get("session_id", ""),
        "ended_at": time.time(),
        "narratives": top_narratives,
    }

    prior_sessions = data.get("prior_sessions", [])
    prior_sessions.insert(0, prior_entry)
    prior_sessions = prior_sessions[:_MAX_PRIOR_SESSIONS]

    return {
        "current": _default_current(session_id=new_session_id),
        "prior_sessions": prior_sessions,
    }


# ---------------------------------------------------------------------------
# Observation eviction
# ---------------------------------------------------------------------------

def evict_old_observations(data: dict) -> dict:
    """Drop observations older than 2 hours from current.rolling_observations."""
    cutoff = time.time() - _OBS_MAX_AGE_SECS
    current = data.get("current", {})
    rolling = current.get("rolling_observations", [])
    current["rolling_observations"] = [
        o for o in rolling
        if isinstance(o, dict) and o.get("ts", 0) >= cutoff
    ]
    return data


# ---------------------------------------------------------------------------
# Helpers for engine
# ---------------------------------------------------------------------------

def append_observation(data: dict, obs_snapshot: dict) -> dict:
    """Append an observation snapshot to current.rolling_observations."""
    current = data.setdefault("current", _default_current())
    rolling = current.setdefault("rolling_observations", [])
    rolling.append(obs_snapshot)
    return data


def append_narrative(data: dict, entry: dict) -> dict:
    """Append a delivered narrative entry; keep last 8."""
    current = data.setdefault("current", _default_current())
    delivered = current.setdefault("delivered_narratives", [])
    delivered.append(entry)
    current["delivered_narratives"] = delivered[-_MAX_DELIVERED_NARRATIVES:]
    return data


# ---------------------------------------------------------------------------
# Path helper (allows tests to override)
# ---------------------------------------------------------------------------

def _get_memory_path() -> Path:
    """Return the memory file path. Tests can override _MEMORY_PATH."""
    # Module-level override (tests do: narrator.memory._MEMORY_PATH = tmp_path)
    import narrator.memory as _self
    return Path(_self._MEMORY_PATH)
