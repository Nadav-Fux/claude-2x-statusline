"""Tests for lib/wire-json.sh helpers.

These tests exercise the shared shell helper the installers now use for:
  1. Recursive JSON merge with idempotent array entries.
  2. Reading scalar JSON paths via ``json_get``.
  3. Collecting failed doctor check IDs via ``json_fail_ids``.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
WIRE_JSON = REPO_ROOT / "lib" / "wire-json.sh"


def _find_bash() -> str | None:
    candidates = [
        shutil.which("bash"),
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files\Git\usr\bin\bash.exe",
        r"C:\Program Files (x86)\Git\bin\bash.exe",
        r"C:\Program Files (x86)\Git\usr\bin\bash.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return None


BASH = _find_bash()
if not BASH:
    pytestmark = pytest.mark.skip(reason="bash not available")


def _run_bash(script: str, env: dict[str, str] | None = None) -> str:
    completed = subprocess.run(
        [BASH, "-lc", script],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    return completed.stdout.strip()


def test_wire_json_merges_nested_objects_and_dedupes_arrays(tmp_path):
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [{"type": "command", "command": "/existing"}],
                    "UserPromptSubmit": [{"type": "command", "command": "/same"}],
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    merge_json = json.dumps(
        {
            "statusLine": {"type": "command", "command": "bash /tmp/statusline.sh"},
            "hooks": {
                "SessionStart": [{"type": "command", "command": "/existing"}],
                "UserPromptSubmit": [
                    {"type": "command", "command": "/same"},
                    {"type": "command", "command": "/new"},
                ],
            },
        }
    )

    script = f'. "{WIRE_JSON.as_posix()}"; wire_json "{settings_path.as_posix()}" \
\'{merge_json}\''
    _run_bash(script)

    merged = json.loads(settings_path.read_text(encoding="utf-8"))
    assert merged["statusLine"]["command"] == "bash /tmp/statusline.sh"
    assert merged["hooks"]["SessionStart"] == [{"type": "command", "command": "/existing"}]
    assert merged["hooks"]["UserPromptSubmit"] == [
        {"type": "command", "command": "/same"},
        {"type": "command", "command": "/new"},
    ]


def test_json_get_reads_scalar_values(tmp_path):
    config_path = tmp_path / "statusline-config.json"
    config_path.write_text(
        json.dumps({"tier": "full", "mode": "full", "schedule_cache_hours": 6}),
        encoding="utf-8",
    )

    script = f'. "{WIRE_JSON.as_posix()}"; json_get "{config_path.as_posix()}" tier'
    assert _run_bash(script) == "full"


def test_json_fail_ids_returns_failed_checks(tmp_path):
    doctor_path = tmp_path / "doctor.json"
    doctor_path.write_text(
        json.dumps(
            {
                "ok": 7,
                "warn": 1,
                "fail": 2,
                "checks": [
                    {"status": "ok", "id": "runtime"},
                    {"status": "fail", "id": "settings_missing"},
                    {"status": "warn", "id": "narrator_unavailable"},
                    {"status": "fail", "id": "statusline_missing"},
                ],
            }
        ),
        encoding="utf-8",
    )

    script = f'. "{WIRE_JSON.as_posix()}"; json_fail_ids "{doctor_path.as_posix()}"'
    assert _run_bash(script).split() == ["settings_missing", "statusline_missing"]