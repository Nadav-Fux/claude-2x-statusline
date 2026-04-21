import os
import shlex
import shutil
import subprocess
import time
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
DOCTOR_PATH = REPO_ROOT / "doctor" / "doctor.sh"


def _msys_path(path: Path) -> str:
    resolved = path.resolve().as_posix()
    if len(resolved) >= 3 and resolved[1:3] == ":/":
        return f"/{resolved[0].lower()}{resolved[2:]}"
    return resolved


def _write_fake_curl(bin_dir: Path) -> None:
    script = bin_dir / "curl"
    script.write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' \"$*\" > \"$STATUSLINE_TEST_CURL_MARKER\"\n"
        "exit 0\n",
        encoding="utf-8",
    )
    script.chmod(0o755)


def _wait_for_marker(marker: Path, timeout: float = 1.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if marker.exists() and marker.read_text(encoding="utf-8").strip():
            return True
        time.sleep(0.05)
    return marker.exists() and bool(marker.read_text(encoding="utf-8").strip())


@pytest.fixture
def bash_exe() -> str:
    bash = shutil.which("bash")
    if not bash:
        pytest.skip("bash not available")
    return bash


@pytest.fixture
def doctor_env(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    marker = tmp_path / "curl-marker.txt"
    _write_fake_curl(bin_dir)
    return home, bin_dir, marker


def _run_doctor_report(
    bash_exe: str,
    home: Path,
    bin_dir: Path,
    marker: Path,
    extra_env=None,
):
    command = " ; ".join(
        [
            f"export HOME={shlex.quote(_msys_path(home))}",
            f"export USERPROFILE={shlex.quote(_msys_path(home))}",
            f"export STATUSLINE_TEST_CURL_MARKER={shlex.quote(_msys_path(marker))}",
            f"export PATH={shlex.quote(_msys_path(bin_dir))}:$PATH",
            f"{shlex.quote(_msys_path(DOCTOR_PATH))} --report",
        ]
    )
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [bash_exe, "-lc", command],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def test_doctor_report_uses_curl_when_enabled(bash_exe: str, doctor_env) -> None:
    home, bin_dir, marker = doctor_env

    result = _run_doctor_report(bash_exe, home, bin_dir, marker)

    assert result.returncode == 0, result.stderr or result.stdout
    assert _wait_for_marker(marker), result.stdout
    payload = marker.read_text(encoding="utf-8")
    assert "statusline-telemetry.nadavf.workers.dev/ping" in payload
    assert '"event":"doctor"' in payload


def test_doctor_report_respects_env_opt_out(bash_exe: str, doctor_env) -> None:
    home, bin_dir, marker = doctor_env

    result = _run_doctor_report(
        bash_exe,
        home,
        bin_dir,
        marker,
        extra_env={"STATUSLINE_DISABLE_TELEMETRY": "1"},
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert not _wait_for_marker(marker, timeout=0.2), result.stdout