"""Workflow manifest and live-agent readers for the statusline."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

_USAGE_PATTERN = re.compile(
    r'"usage"\s*:\s*\{\s*"input_tokens"\s*:\s*(\d+)\s*,\s*'
    r'"cache_creation_input_tokens"\s*:\s*(\d+)\s*,\s*'
    r'"cache_read_input_tokens"\s*:\s*(\d+)\s*,\s*'
    r'"output_tokens"\s*:\s*(\d+)'
)


def project_slug(cwd: str) -> str:
    return cwd.replace("/", "-").replace("\\", "-").replace(":", "").lstrip("-")


def find_session_dir(stdin_data: dict) -> Path | None:
    """Derive the Claude Code session directory from hook stdin or PID state."""
    transcript_path = stdin_data.get("transcript_path", "")
    if transcript_path:
        path = Path(transcript_path)
        if path.suffix == ".jsonl":
            path = path.parent
        if path.is_dir():
            return path

    session_id = stdin_data.get("session_id", "")
    cwd = stdin_data.get("cwd", "")
    if session_id and cwd:
        candidate = Path.home() / ".claude" / "projects" / project_slug(cwd) / session_id
        if candidate.is_dir():
            return candidate

    sessions_dir = Path.home() / ".claude" / "sessions"
    if sessions_dir.is_dir():
        pid = str(os.getpid())
        for file_path in sessions_dir.glob("*.json"):
            try:
                data = json.loads(file_path.read_text(encoding="utf-8"))
                if str(data.get("pid", "")) == pid or file_path.stem == pid:
                    sid = data.get("sessionId", "")
                    cwd2 = data.get("cwd", "")
                    if sid and cwd2:
                        candidate = Path.home() / ".claude" / "projects" / project_slug(cwd2) / sid
                        if candidate.is_dir():
                            return candidate
            except Exception:
                pass

    return None


def workflow_cache_key(session_dir: Path) -> tuple:
    wf_dir = session_dir / "workflows"
    live_dir = session_dir / "subagents" / "workflows"
    try:
        mtime1 = wf_dir.stat().st_mtime if wf_dir.is_dir() else 0
        count1 = sum(1 for _ in wf_dir.glob("wf_*.json")) if wf_dir.is_dir() else 0
    except Exception:
        mtime1 = count1 = 0
    try:
        mtime2 = live_dir.stat().st_mtime if live_dir.is_dir() else 0
        count2 = sum(1 for _ in live_dir.glob("wf_*")) if live_dir.is_dir() else 0
    except Exception:
        mtime2 = count2 = 0
    return (str(session_dir), mtime1, count1, mtime2, count2)


def read_agent_last_usage_tokens(jsonl_path: Path) -> int:
    """Return input+cache tokens from the last complete usage block.

    Never sum all usage blocks: cache_read_input_tokens is re-billed each turn,
    while this segment reports current context footprint.
    """
    try:
        size = jsonl_path.stat().st_size
        chunk_size = min(65536, size)
        with open(jsonl_path, "rb") as handle:
            if size > chunk_size:
                handle.seek(-chunk_size, 2)
            tail_text = handle.read().decode("utf-8", errors="replace")

        matches = list(_USAGE_PATTERN.finditer(tail_text))
        if not matches:
            return 0

        last = matches[-1]
        after_match = tail_text[last.end():last.end() + 20]
        if after_match and not any(char in after_match for char in ("}", "\n")):
            if len(matches) >= 2:
                last = matches[-2]
            else:
                return 0

        return int(last.group(1)) + int(last.group(2)) + int(last.group(3))
    except Exception:
        return 0


def detect_live_workflows(session_dir: Path) -> list[dict]:
    """Return in-flight workflow dicts with agent count and context tokens."""
    live_base = session_dir / "subagents" / "workflows"
    completed_dir = session_dir / "workflows"
    if not live_base.is_dir():
        return []

    results = []
    for wf_subdir in live_base.iterdir():
        if not wf_subdir.is_dir() or not wf_subdir.name.startswith("wf_"):
            continue
        if (completed_dir / f"{wf_subdir.name}.json").exists():
            continue

        agent_count = 0
        total_tokens = 0
        for jsonl_file in wf_subdir.glob("agent-*.jsonl"):
            if jsonl_file.name.endswith(".meta.json"):
                continue
            agent_count += 1
            total_tokens += read_agent_last_usage_tokens(jsonl_file)

        if agent_count > 0:
            results.append({"name": wf_subdir.name, "agents": agent_count, "tokens": total_tokens})

    return results


def read_completed_workflows(session_dir: Path) -> dict:
    """Aggregate completed workflow manifests in the session directory."""
    wf_dir = session_dir / "workflows"
    if not wf_dir.is_dir():
        return {"total_tokens": 0, "run_count": 0, "agent_count": 0}

    total_tokens = 0
    run_count = 0
    agent_count = 0
    for wf_file in wf_dir.glob("wf_*.json"):
        try:
            data = json.loads(wf_file.read_text(encoding="utf-8"))
            if data.get("status") != "completed":
                continue
            total_tokens += int(data.get("totalTokens", 0))
            run_count += 1
            agent_count += int(data.get("agentCount", 0))
        except Exception:
            pass

    return {"total_tokens": total_tokens, "run_count": run_count, "agent_count": agent_count}
