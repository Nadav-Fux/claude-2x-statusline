"""Background job monitor helpers for Claude Code daemon state."""

from __future__ import annotations

import json
import time
from pathlib import Path


FINISHED_STATES = {
    "done",
    "finished",
    "complete",
    "completed",
    "failed",
    "error",
    "errored",
    "cancelled",
    "canceled",
    "stopped",
    "idle",
}

RUNNING_STATES = {
    "running",
    "active",
    "busy",
    "working",
    "processing",
    "in_progress",
    "in-progress",
    "started",
    "starting",
    "pending",
    "queued",
}


def jobs_root(home: Path | None = None) -> Path:
    return (home or Path.home()) / ".claude" / "jobs"


def roster_file(home: Path | None = None) -> Path:
    return (home or Path.home()) / ".claude" / "daemon" / "roster.json"


def _to_count(value) -> int:
    try:
        n = int(float(value))
        return n if n > 0 else 0
    except (TypeError, ValueError):
        return 0


def _short_name(value) -> str:
    text = str(value or "").strip()
    return text if text and len(text) <= 24 else ""


def _read_roster_workers(path: Path) -> int:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        workers = data.get("workers") if isinstance(data, dict) else None
        return len(workers) if isinstance(workers, dict) else 0
    except Exception:
        return 0


def _active_job(data, mtime_ms: float, now_ms: float, max_age_ms: int) -> dict | None:
    if not isinstance(data, dict):
        return None
    if now_ms - mtime_ms > max_age_ms:
        return None

    state = str(data.get("state") or "").strip().lower()
    if state in FINISHED_STATES:
        return None

    tempo = str(data.get("tempo") or "").strip().lower()
    in_flight = data.get("inFlight") if isinstance(data.get("inFlight"), dict) else {}
    tasks = _to_count(in_flight.get("tasks"))
    queued = _to_count(in_flight.get("queued"))
    has_tempo_or_in_flight = "tempo" in data or "inFlight" in data
    shows_life = (
        tempo == "active"
        or tasks > 0
        or queued > 0
        or (not has_tempo_or_in_flight and state in RUNNING_STATES)
    )
    if not shows_life:
        return None

    return {"tasks": tasks, "name": _short_name(data.get("name"))}


def collect_active_jobs(
    jobs_dir: Path | None = None,
    roster_path: Path | None = None,
    now_ms: float | None = None,
    max_age_ms: int = 15 * 60 * 1000,
) -> dict:
    jobs_dir = jobs_dir or jobs_root()
    roster_path = roster_path or roster_file()
    now_ms = time.time() * 1000 if now_ms is None else now_ms
    active_jobs = 0
    inflight = 0
    only_name = ""

    try:
        for job_dir in jobs_dir.iterdir():
            if not job_dir.is_dir():
                continue
            state_path = job_dir / "state.json"
            try:
                active = _active_job(
                    json.loads(state_path.read_text(encoding="utf-8")),
                    state_path.stat().st_mtime * 1000,
                    now_ms,
                    max_age_ms,
                )
                if not active:
                    continue
                active_jobs += 1
                inflight += active["tasks"]
                only_name = active["name"]
            except Exception:
                pass
    except Exception:
        pass

    workers = _read_roster_workers(roster_path)
    count = active_jobs + workers
    name = only_name if active_jobs == 1 and workers == 0 else ""
    return {"count": count, "inflight": inflight, "workers": workers, "name": name}


def render_jobs_summary(summary: dict | None) -> str:
    count = _to_count((summary or {}).get("count"))
    if count <= 0:
        return ""

    inflight = _to_count((summary or {}).get("inflight"))
    name = _short_name((summary or {}).get("name"))
    base = f"↻ {name}" if name and count == 1 else f"↻ {count} job{'s' if count != 1 else ''}"
    return f"{base} · {inflight} inflight" if inflight > 0 else base
