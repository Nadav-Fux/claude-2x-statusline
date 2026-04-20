import json
import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
WIRE_JSON_PS1 = REPO_ROOT / "lib" / "Wire-Json.ps1"


def _find_powershell() -> str | None:
    candidates = [
        shutil.which("powershell"),
        r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
        shutil.which("pwsh"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return None


POWERSHELL = _find_powershell()


@pytest.mark.skipif(not POWERSHELL, reason="PowerShell not available")
def test_wire_json_ps1_preserves_singleton_hook_arrays(tmp_path):
    settings_path = tmp_path / "settings.json"
    merge_json = json.dumps(
        {
            "statusLine": {
                "type": "command",
                "command": "powershell -File statusline.ps1",
            },
            "hooks": {
                "SessionStart": [
                    {
                        "hooks": [
                            {
                                "type": "command",
                                "command": "session-start.sh",
                            }
                        ]
                    }
                ],
                "UserPromptSubmit": [
                    {
                        "hooks": [
                            {
                                "type": "command",
                                "command": "prompt-submit.sh",
                            }
                        ]
                    }
                ],
            },
        }
    )

    subprocess.run(
        [
            POWERSHELL,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(WIRE_JSON_PS1),
            "-Path",
            str(settings_path),
            "-MergeJson",
            merge_json,
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    merged = json.loads(settings_path.read_text(encoding="utf-8"))
    assert merged["statusLine"]["command"] == "powershell -File statusline.ps1"
    assert merged["hooks"]["SessionStart"] == [
        {"hooks": [{"type": "command", "command": "session-start.sh"}]}
    ]
    assert merged["hooks"]["UserPromptSubmit"] == [
        {"hooks": [{"type": "command", "command": "prompt-submit.sh"}]}
    ]