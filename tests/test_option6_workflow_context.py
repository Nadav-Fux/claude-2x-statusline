"""Option 6 narrator and VS Code workflow context tests."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import narrator.observations as observations
from narrator.observations import Observation
from narrator.scoring import _build_insights

_ROOT = Path(__file__).resolve().parent.parent


def _make_live_session(tmp_path: Path) -> Path:
    session_dir = tmp_path / "session"
    live_dir = session_dir / "subagents" / "workflows" / "wf_test"
    live_dir.mkdir(parents=True)
    shutil.copyfile(
        _ROOT / "tests" / "fixtures" / "agent_sample.jsonl",
        live_dir / "agent-001.jsonl",
    )
    return session_dir


def test_seg_workflows_spend_persists_after_manifest_gone(tmp_path, monkeypatch):
    """The workflow Σ must survive the completion manifest disappearing.

    Reproduces the user-visible bug: workflow spend vanished when a run finished
    without a manifest (interrupt) or on a tier switch. The per-session
    high-water-mark keeps it visible (dimmed, labelled idle).
    """
    import re

    engine = observations._load_python_engine_module()
    session_dir = tmp_path / "session"
    session_dir.mkdir()
    monkeypatch.setattr(engine, "_wf_find_session_dir", lambda stdin: session_dir)

    def render():
        engine._WF_CACHE.clear()
        return re.sub(r"\x1b\[[0-9;]*m", "", engine.seg_workflows({"stdin": {}}))

    # Nothing yet → segment self-hides.
    assert render() == ""

    # A completed workflow manifest → idle Σ is shown.
    wf_dir = session_dir / "workflows"
    wf_dir.mkdir()
    (wf_dir / "wf_a.json").write_text(
        json.dumps({"status": "completed", "totalTokens": 2_300_000, "agentCount": 4})
    )
    out = render()
    assert "wf idle" in out and "2.3M" in out, out

    # Manifest removed (interrupt / cleanup) → spend STILL shown from the peak file.
    shutil.rmtree(wf_dir)
    out2 = render()
    assert "2.3M" in out2, f"spend must persist after manifest gone, got: {out2!r}"
    assert (session_dir / ".statusline-wf-peak.json").is_file()


def test_observation_populates_live_workflow_fields(tmp_path, monkeypatch):
    session_dir = _make_live_session(tmp_path)
    monkeypatch.setattr(
        observations,
        "_read_stdin_json",
        lambda: {
            # Real layout: transcript <sid>.jsonl is a sibling of the session dir.
            "transcript_path": str(session_dir) + ".jsonl",
            "context_window": {
                "context_window_size": 200000,
                "current_usage": {"input_tokens": 10},
            },
            "cost": {},
        },
    )
    monkeypatch.setattr(observations, "_is_peak_hours", lambda: False)
    monkeypatch.setattr(observations, "_load_statusline_state", lambda: {"samples": []})
    monkeypatch.setattr(observations, "_load_usage_cache", lambda: {})

    obs = observations.build({"current": {}})

    assert obs.active_workflow_agents == 1
    assert obs.subagent_tokens_live == 62_000


def test_workflow_background_drain_template_fires():
    obs = Observation(active_workflow_agents=3, subagent_tokens_live=180_000)

    insights = _build_insights(obs, {"current": {}})

    assert any(item.template_key == "workflow_background_drain" for item in insights)


def test_python_engine_writes_vscode_context_file(tmp_path):
    session_dir = _make_live_session(tmp_path)
    fake_home = tmp_path / "home"
    claude_dir = fake_home / ".claude"
    claude_dir.mkdir(parents=True)
    (claude_dir / "statusline-config.json").write_text(
        json.dumps({"tier": "standard", "schedule_url": "", "schedule_cache_hours": 999}),
        encoding="utf-8",
    )
    (claude_dir / "statusline-schedule.json").write_text(
        json.dumps({"mode": "normal", "banner": {}, "release": {}, "features": {}}),
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["HOME"] = str(fake_home)
    env["USERPROFILE"] = str(fake_home)
    env["TMP"] = str(tmp_path)
    env["TEMP"] = str(tmp_path)
    env["TMPDIR"] = str(tmp_path)
    subprocess.run(
        [sys.executable, "engines/python-engine.py", "--tier=standard"],
        input=json.dumps(
            {
                "transcript_path": str(session_dir) + ".jsonl",
                "model": {"display_name": "Sonnet"},
                "cost": {"total_cost_usd": 1.25},
                "context_window": {
                    "context_window_size": 200000,
                    "current_usage": {"input_tokens": 50000},
                },
            }
        ),
        text=True,
        cwd=_ROOT,
        env=env,
        capture_output=True,
        timeout=10,
        check=True,
    )

    payload = json.loads((tmp_path / "claude" / "statusline-context.json").read_text(encoding="utf-8"))
    assert payload["active_workflow_agents"] == 1
    assert payload["subagent_tokens_live"] == 62_000
    assert payload["current_usage"] == 50_000
    assert payload["pct"] == 25
