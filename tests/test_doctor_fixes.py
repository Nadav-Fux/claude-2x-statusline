"""Tests for doctor/fixes.sh's settings.json backup behavior.

fixes.sh's set_statusline_command() patches ~/.claude/settings.json outside
of lib/wire-json.sh's wire_json() (it has its own python/naive-rewrite write
path), so it needs its own settings.json.bak.<epoch> safety copy — see
backup_settings() in doctor/fixes.sh. This mirrors the wire_json backup
coverage in tests/test_wire_json.py.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
FIXES_SH = REPO_ROOT / "doctor" / "fixes.sh"


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


def _run_fix(hint: str, settings_path: Path, config_path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [BASH, str(FIXES_SH), hint, str(settings_path), str(config_path), str(REPO_ROOT)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_restore_statusline_backs_up_existing_settings(tmp_path):
    settings_path = tmp_path / "settings.json"
    config_path = tmp_path / "statusline-config.json"
    original = {"statusLine": {"type": "command", "command": "/some/hijacked/thing"}, "other": True}
    settings_path.write_text(json.dumps(original), encoding="utf-8")

    result = _run_fix("restore-statusline", settings_path, config_path)
    assert result.returncode == 0, result.stderr or result.stdout

    backups = list(tmp_path.glob("settings.json.bak.*"))
    assert len(backups) == 1
    assert json.loads(backups[0].read_text(encoding="utf-8")) == original

    # The other key survives the patch (python branch merges; naive branch
    # only runs when python/settings are both absent, which isn't this case).
    merged = json.loads(settings_path.read_text(encoding="utf-8"))
    assert merged["statusLine"]["command"] != original["statusLine"]["command"]


def test_add_statusline_does_not_back_up_a_missing_settings_file(tmp_path):
    settings_path = tmp_path / "settings.json"
    config_path = tmp_path / "statusline-config.json"
    assert not settings_path.exists()

    result = _run_fix("add-statusline", settings_path, config_path)
    assert result.returncode == 0, result.stderr or result.stdout

    assert settings_path.exists()
    assert list(tmp_path.glob("settings.json.bak.*")) == []
