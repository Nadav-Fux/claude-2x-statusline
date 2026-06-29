"""Multi-session cockpit helpers for Claude Code session registry files."""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path


def session_registry_dir(home: Path | None = None) -> Path:
    return (home or Path.home()) / ".claude" / "sessions"


def parse_updated_at(value) -> float | None:
    if value is None or value == "":
        return None
    try:
        if isinstance(value, (int, float)) or str(value).replace(".", "", 1).isdigit():
            n = float(value)
            if n <= 0:
                return None
            return n if n > 1e11 else n * 1000
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp() * 1000
    except Exception:
        return None


def collect_session_counts(sessions_dir: Path | None = None, now_ms: float | None = None, max_age_ms: int = 15 * 60 * 1000) -> dict:
    sessions_dir = sessions_dir or session_registry_dir()
    now_ms = time.time() * 1000 if now_ms is None else now_ms
    live = 0
    busy = 0
    try:
        for file_path in sessions_dir.glob("*.json"):
            try:
                data = json.loads(file_path.read_text(encoding="utf-8"))
                updated_ms = parse_updated_at(data.get("updatedAt"))
                if updated_ms is None or now_ms - updated_ms > max_age_ms:
                    continue
                live += 1
                if str(data.get("status", "")).lower() == "busy":
                    busy += 1
            except Exception:
                pass
    except Exception:
        return {"live": 0, "busy": 0, "error": True}
    return {"live": live, "busy": busy, "error": False}


def render_session_summary(counts: dict | None) -> str:
    live = int((counts or {}).get("live") or 0)
    if live <= 1:
        return ""
    busy = int((counts or {}).get("busy") or 0)
    return f"◉ {live} sess · {busy} busy"
