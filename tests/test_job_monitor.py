import json
import os
import time
from pathlib import Path

from lib import job_monitor


def _write_job(home: Path, job_id: str, payload: dict, age_seconds: int = 0) -> Path:
    state_path = home / ".claude" / "jobs" / job_id / "state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(payload), encoding="utf-8")
    ts = time.time() - age_seconds
    os.utime(state_path, (ts, ts))
    return state_path


def test_collect_active_jobs_ignores_finished_and_stale(monkeypatch, tmp_path):
    home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))

    _write_job(home, "finished", {"state": "done", "tempo": "idle", "inFlight": {"tasks": 0}})
    _write_job(home, "running", {"state": "running", "tempo": "active", "inFlight": {"tasks": 3}})
    _write_job(
        home,
        "stale",
        {"state": "running", "tempo": "active", "inFlight": {"tasks": 5}},
        age_seconds=30 * 60,
    )

    summary = job_monitor.collect_active_jobs()

    assert summary == {"count": 1, "inflight": 3, "workers": 0, "name": ""}
    assert job_monitor.render_jobs_summary(summary) == "↻ 1 job · 3 inflight"


def test_jobs_summary_hides_when_nothing_active(monkeypatch, tmp_path):
    home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))

    _write_job(home, "finished", {"state": "done", "tempo": "idle", "inFlight": {"tasks": 0}})

    assert job_monitor.collect_active_jobs() == {"count": 0, "inflight": 0, "workers": 0, "name": ""}
    assert job_monitor.render_jobs_summary(job_monitor.collect_active_jobs()) == ""
