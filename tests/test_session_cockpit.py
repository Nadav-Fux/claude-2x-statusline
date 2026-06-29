import json
from pathlib import Path

from lib import session_cockpit


def _write_session(path: Path, status: str, updated_at):
    path.write_text(
        json.dumps({"sessionId": path.stem, "cwd": "/tmp/project", "status": status, "updatedAt": updated_at}),
        encoding="utf-8",
    )


def test_session_counts_live_busy_and_stale(tmp_path):
    sessions = tmp_path / ".claude" / "sessions"
    sessions.mkdir(parents=True)
    now_ms = 1_800_000_000_000

    _write_session(sessions / "busy-1.json", "busy", now_ms)
    _write_session(sessions / "busy-2.json", "busy", now_ms - 5 * 60 * 1000)
    _write_session(sessions / "idle.json", "idle", now_ms - 14 * 60 * 1000)
    _write_session(sessions / "stale.json", "busy", now_ms - 16 * 60 * 1000)

    counts = session_cockpit.collect_session_counts(sessions_dir=sessions, now_ms=now_ms)

    assert counts == {"live": 3, "busy": 2, "error": False}
    assert session_cockpit.render_session_summary(counts) == "◉ 3 sess · 2 busy"


def test_session_summary_hides_single_live_session():
    assert session_cockpit.render_session_summary({"live": 1, "busy": 1}) == ""
    assert session_cockpit.render_session_summary({"live": 0, "busy": 0}) == ""
